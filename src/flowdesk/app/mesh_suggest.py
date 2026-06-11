"""Mesh auto-suggestions (PRD §4.3.1 defaults, §2.5 mitigation #1).

Headless: geometry diagnostics + pyvista point-in-solid tests, no Qt.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pyvista as pv

from flowdesk.model.case import CaseModel
from flowdesk.model.geometry import Vec3

EXTERNAL_PADDING = 1.0  # x bbox-diagonal each side (§4.3.1)
INTERNAL_PADDING = 0.05


def geometry_bbox(model: CaseModel) -> tuple[Vec3, Vec3] | None:
    """Combined bounding box of all imported surfaces, from stored diagnostics."""
    surfaces = model.geometry.surfaces
    if not surfaces:
        return None
    mins = [min(s.diagnostics.bounds_min[i] for s in surfaces) for i in range(3)]
    maxs = [max(s.diagnostics.bounds_max[i] for s in surfaces) for i in range(3)]
    return (tuple(mins), tuple(maxs))


def suggest_bounds(model: CaseModel, external: bool = True) -> tuple[Vec3, Vec3] | None:
    """Geometry bbox + padding: 1x diagonal each side external, 0.05x internal."""
    bbox = geometry_bbox(model)
    if bbox is None:
        return None
    lo, hi = bbox
    diag = math.dist(lo, hi)
    pad = diag * (EXTERNAL_PADDING if external else INTERNAL_PADDING)
    return (
        tuple(c - pad for c in lo),
        tuple(c + pad for c in hi),
    )


def suggest_cell_size(bounds_min: Vec3, bounds_max: Vec3) -> float:
    """§4.3.1 default: bbox-diagonal / 40."""
    return math.dist(bounds_min, bounds_max) / 40.0


def cells_from_size(bounds_min: Vec3, bounds_max: Vec3, size: float) -> tuple[int, int, int]:
    nx, ny, nz = (
        max(1, round((hi - lo) / size))
        for lo, hi in zip(bounds_min, bounds_max, strict=True)
    )
    return (nx, ny, nz)


def _load_watertight_surfaces(model: CaseModel, case_dir: Path) -> list[pv.PolyData]:
    meshes = []
    for s in model.geometry.surfaces:
        if not s.diagnostics.watertight:
            continue
        stl = case_dir / "constant" / "triSurface" / f"{s.name}.stl"
        if stl.exists():
            meshes.append(pv.read(str(stl)).extract_surface().triangulate())
    return meshes


def _inside_any(point: Vec3, solids: list[pv.PolyData]) -> bool:
    if not solids:
        return False
    probe = pv.PolyData(np.array([point], dtype=float))
    for solid in solids:
        enclosed = probe.select_enclosed_points(solid, check_surface=False)
        if bool(enclosed["SelectedPoints"][0]):
            return True
    return False


def _distance_to_surfaces(point: Vec3, solids: list[pv.PolyData]) -> float:
    if not solids:
        return math.inf
    p = np.array(point, dtype=float)
    best = math.inf
    for solid in solids:
        closest_id = solid.find_closest_point(p)
        best = min(best, float(np.linalg.norm(solid.points[closest_id] - p)))
    return best


def suggest_location_in_mesh(model: CaseModel, case_dir: Path) -> Vec3 | None:
    """A point inside the domain box, outside all watertight solids, far from
    surfaces (§4.3.2 'Suggest'). Returns None when no candidate qualifies."""
    b = model.mesh.block
    lo, hi = b.bounds_min, b.bounds_max
    solids = _load_watertight_surfaces(model, case_dir)
    cell = max((high - low) / n for low, high, n in zip(lo, hi, b.cells, strict=True))

    # Candidates: box centre, then fractions along the main diagonals and axes.
    fractions = (0.5, 0.25, 0.75, 0.125, 0.875, 0.375, 0.625)
    candidates: list[Vec3] = []
    for fx in fractions:
        for fy in fractions[:3]:
            for fz in fractions[:3]:
                candidates.append((
                    lo[0] + fx * (hi[0] - lo[0]),
                    lo[1] + fy * (hi[1] - lo[1]),
                    lo[2] + fz * (hi[2] - lo[2]),
                ))

    best: tuple[float, Vec3] | None = None
    for c in candidates:
        if _inside_any(c, solids):
            continue
        dist = _distance_to_surfaces(c, solids)
        if dist < cell:  # §4.3.2: within one cell of a surface is a bad point
            continue
        if best is None or dist > best[0]:
            best = (dist, c)
    return best[1] if best else None


def location_diagnosis(model: CaseModel, case_dir: Path, point: Vec3) -> str | None:
    """ERROR/WARN text for a chosen material point, or None when fine (§4.3.2)."""
    b = model.mesh.block
    if not all(lo < c < hi for c, lo, hi in
               zip(point, b.bounds_min, b.bounds_max, strict=True)):
        return "Material point is outside the background-mesh box."
    solids = _load_watertight_surfaces(model, case_dir)
    if _inside_any(point, solids):
        return "Material point is inside the solid geometry — snappy would mesh the solid."
    cell = max((high - low) / n for low, high, n in
               zip(b.bounds_min, b.bounds_max, b.cells, strict=True))
    if _distance_to_surfaces(point, solids) < cell:
        return "Material point is within one cell of a surface — move it into open fluid."
    return None
