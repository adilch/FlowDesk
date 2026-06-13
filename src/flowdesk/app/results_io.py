"""Results loading & extraction (PRD §4.8). Headless pyvista; no Qt.

Reads via POpenFOAMReader on case.foam - handles reconstructed and decomposed
cases alike (§2.4). Known reader quirk (derived-BC patch display) is accepted
at preview fidelity; ParaView is the escape hatch for everything else.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pyvista as pv

# §4.8 rendering guardrails
PREVIEW_BUSY_CELLS = 5_000_000
PREVIEW_DISABLED_CELLS = 15_000_000

COLORMAPS = {"Viridis": "viridis", "CoolWarm": "coolwarm", "Turbo": "turbo"}

FIELD_LABELS = {
    "U magnitude": ("U", "magnitude"),
    "Ux": ("U", 0), "Uy": ("U", 1), "Uz": ("U", 2),
    "p": ("p", None), "k": ("k", None), "omega": ("omega", None),
    "epsilon": ("epsilon", None), "nut": ("nut", None),
    # free surface (interFoam)
    "alpha.water": ("alpha.water", None),
    "p_rgh": ("p_rgh", None),
}


@dataclass
class LoadedResults:
    mesh: pv.DataSet  # internalMesh at the active time
    boundaries: pv.MultiBlock | None
    time_values: list[float]
    active_time: float
    n_cells: int

    def available_fields(self) -> list[str]:
        present = set(self.mesh.cell_data.keys()) | set(self.mesh.point_data.keys())
        out = []
        known: set[str] = set()
        for label, (array, _comp) in FIELD_LABELS.items():
            known.add(array)
            if array in present:
                out.append(label)
        # extra scalar fields (e.g. a transported tracer 's') the user added
        for name in sorted(present - known):
            data = self.mesh.point_data.get(name)
            if data is None:
                data = self.mesh.cell_data.get(name)
            if data is not None and data.ndim == 1:  # scalar only
                out.append(name)
                FIELD_LABELS.setdefault(name, (name, None))
        return out


def list_time_values(case_dir: Path) -> list[float]:
    reader = _reader(case_dir)
    return list(reader.time_values)


def _reader(case_dir: Path) -> pv.POpenFOAMReader:
    foam = case_dir / "case.foam"
    foam.touch()
    reader = pv.POpenFOAMReader(str(foam))
    # decomposed read if reconstruct was skipped/failed (§4.8)
    has_processors = any(p.name.startswith("processor")
                         for p in case_dir.iterdir() if p.is_dir())
    has_root_times = any(p.name.replace(".", "").isdigit() and p.name != "0"
                         for p in case_dir.iterdir() if p.is_dir())
    if has_processors and not has_root_times:
        reader.case_type = "decomposed"
    return reader


def load(case_dir: Path, time_value: float | None = None) -> LoadedResults:
    reader = _reader(case_dir)
    times = list(reader.time_values)
    active = time_value if time_value is not None else (times[-1] if times else 0.0)
    if times:
        reader.set_active_time_value(active)
    reader.enable_all_patch_arrays()
    data = reader.read()
    internal = data["internalMesh"]
    block_names = data.keys()  # MultiBlock: .keys() is the only name API
    boundaries = data["boundary"] if "boundary" in block_names else None
    return LoadedResults(
        mesh=internal,
        boundaries=boundaries,
        time_values=times,
        active_time=active,
        n_cells=internal.n_cells,
    )


def scalar_array(dataset: pv.DataSet, field_label: str) -> tuple[str, np.ndarray]:
    """Resolve a UI field label to a scalar array on the dataset; returns the
    array name it was stored under (for color mapping)."""
    array_name, component = FIELD_LABELS[field_label]
    data = dataset.point_data.get(array_name)
    if data is None:
        data = dataset.cell_data.get(array_name)
    if data is None:
        raise KeyError(f"field '{array_name}' not in results")
    values = np.asarray(data)
    if component == "magnitude":
        values = np.linalg.norm(values, axis=1)
    elif isinstance(component, int):
        values = values[:, component]
    key = f"_flowdesk_{field_label.replace(' ', '_')}"
    if data.shape[0] == dataset.n_points:
        dataset.point_data[key] = values
    else:
        dataset.cell_data[key] = values
    return key, values


def field_range(results: LoadedResults, field_label: str) -> tuple[float, float] | None:
    """(min, max) of a scalar field over the internal mesh, for the color range
    controls. None when the field is absent."""
    try:
        _key, values = scalar_array(results.mesh.copy(), field_label)
    except KeyError:
        return None
    if values.size == 0:
        return None
    return (float(values.min()), float(values.max()))


def slice_plane(results: LoadedResults, origin, normal) -> pv.PolyData:
    return results.mesh.slice(normal=normal, origin=origin)


def glyphs_on_slice(slice_mesh: pv.PolyData, every_nth: int = 10,
                    scale: float = 1.0) -> pv.PolyData | None:
    """Vector glyphs on a slice plane (§4.8): every-Nth-point arrows, scaled."""
    if "U" not in slice_mesh.point_data and "U" not in slice_mesh.cell_data:
        return None
    source = slice_mesh if "U" in slice_mesh.point_data \
        else slice_mesh.cell_data_to_point_data()
    idx = np.arange(0, source.n_points, max(1, every_nth))
    if idx.size == 0:
        return None
    cloud = pv.PolyData(np.asarray(source.points)[idx])
    cloud["U"] = np.asarray(source.point_data["U"])[idx]
    return cloud.glyph(orient="U", scale="U", factor=scale)


def probe_point(results: LoadedResults, point) -> dict[str, float | tuple]:
    """All field values at a point (§4.8 probe)."""
    probe = pv.PolyData(np.array([point], dtype=float))
    sampled = probe.sample(results.mesh)
    out: dict[str, float | tuple] = {}
    for name in sampled.point_data:
        if name.startswith("vtk") or name.startswith("_flowdesk"):
            continue
        values = np.asarray(sampled.point_data[name])[0]
        out[name] = tuple(float(v) for v in values) if values.ndim else float(values)
    return out


def preview_guard(n_cells: int) -> str | None:
    """§4.8 guardrail message, or None when in-app preview is fine."""
    if n_cells > PREVIEW_DISABLED_CELLS:
        return (f"Large case ({n_cells:,} cells) — in-app preview disabled, "
                "use ParaView.")
    if n_cells > PREVIEW_BUSY_CELLS:
        return f"{n_cells:,} cells — extraction may take a moment."
    return None
