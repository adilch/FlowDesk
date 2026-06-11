"""STL import + diagnostics (PRD §4.2). Headless: pyvista/VTK only, no Qt."""

from __future__ import annotations

import re
from pathlib import Path

import pyvista as pv

from flowdesk.model.geometry import Surface, SurfaceDiagnostics

# §4.2 units-sanity heuristic bounds (meters)
UNITS_SUSPECT_LARGE = 1000.0
UNITS_SUSPECT_SMALL = 0.001

SCALE_PRESETS = {"mm": 0.001, "cm": 0.01, "in": 0.0254}


def surface_name_from(path: Path) -> str:
    """Filename stem sanitized into an OpenFOAM word."""
    stem = path.stem
    word = re.sub(r"[^A-Za-z0-9_]", "_", stem)
    if not word or not word[0].isalpha():
        word = "s_" + word
    return word


def analyze(path: Path) -> SurfaceDiagnostics:
    """Triangle count, bounds, watertightness, normal orientation (§4.2 table)."""
    mesh = pv.read(str(path))
    surface = mesh.extract_surface().triangulate()
    edges = surface.extract_feature_edges(
        boundary_edges=True, non_manifold_edges=False,
        feature_edges=False, manifold_edges=False,
    )
    watertight = edges.n_cells == 0
    bounds = surface.bounds
    signed_volume = surface.volume if watertight else 0.0
    return SurfaceDiagnostics(
        triangle_count=surface.n_cells,
        bounds_min=(bounds[0], bounds[2], bounds[4]),
        bounds_max=(bounds[1], bounds[3], bounds[5]),
        watertight=watertight,
        normals_outward=signed_volume >= 0,
    )


def units_suspect(diag: SurfaceDiagnostics) -> str | None:
    """Returns a §4.2 prompt string when the extent suggests wrong export units."""
    extent = max(
        hi - lo for lo, hi in zip(diag.bounds_min, diag.bounds_max, strict=True)
    )
    if extent > UNITS_SUSPECT_LARGE or (0 < extent < UNITS_SUSPECT_SMALL):
        return (f"This geometry is {extent:g} m across. Was it exported in "
                "mm/cm/in?")
    return None


def import_surface(stl_path: Path, case_dir: Path, scale: float = 1.0,
                   name: str | None = None) -> Surface:
    """Copy (scaled) into constant/triSurface/<name>.stl; original untouched (§4.2)."""
    name = name or surface_name_from(stl_path)
    dest = case_dir / "constant" / "triSurface" / f"{name}.stl"
    dest.parent.mkdir(parents=True, exist_ok=True)

    mesh = pv.read(str(stl_path)).extract_surface().triangulate()
    if scale != 1.0:
        mesh = mesh.scale(scale)
    mesh.save(str(dest), binary=True)

    diag = analyze(dest)
    return Surface(name=name, stl_path=str(stl_path), scale=scale, diagnostics=diag)
