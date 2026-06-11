"""STL import + diagnostics (PRD §4.2). Headless: pyvista/VTK only, no Qt."""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pyvista as pv

from flowdesk.model.geometry import (
    BoxPrimitive,
    ConePrimitive,
    CylinderPrimitive,
    PlanePrimitive,
    Primitive,
    SpherePrimitive,
    Surface,
    SurfaceDiagnostics,
)

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


# --- In-app primitive geometries ------------------------------------------------


def primitive_mesh(spec: Primitive) -> pv.PolyData:
    """A triangulated surface for an authored primitive (no CAD kernel)."""
    if isinstance(spec, BoxPrimitive):
        (x0, y0, z0), (x1, y1, z1) = spec.min, spec.max
        mesh = pv.Box(bounds=(min(x0, x1), max(x0, x1), min(y0, y1), max(y0, y1),
                              min(z0, z1), max(z0, z1)))
    elif isinstance(spec, SpherePrimitive):
        mesh = pv.Sphere(center=spec.centre, radius=spec.radius,
                         theta_resolution=48, phi_resolution=48)
    elif isinstance(spec, CylinderPrimitive):
        p1 = np.array(spec.point1, dtype=float)
        p2 = np.array(spec.point2, dtype=float)
        axis = p2 - p1
        height = float(np.linalg.norm(axis)) or 1e-9
        mesh = pv.Cylinder(center=tuple((p1 + p2) / 2), direction=tuple(axis),
                           radius=spec.radius, height=height, resolution=48,
                           capping=True)
    elif isinstance(spec, ConePrimitive):
        # pv.Cone center is the centroid; place it half-height up the axis from base
        d = np.array(spec.direction, dtype=float)
        d = d / (np.linalg.norm(d) or 1e-9)
        center = np.array(spec.base_centre, dtype=float) + d * (spec.height / 2)
        mesh = pv.Cone(center=tuple(center), direction=tuple(d),
                       height=spec.height, radius=spec.radius, resolution=48,
                       capping=True)
    elif isinstance(spec, PlanePrimitive):
        mesh = pv.Plane(center=spec.centre, direction=spec.normal,
                        i_size=spec.i_size, j_size=spec.j_size)
    else:
        raise ValueError(f"unknown primitive: {spec!r}")
    return mesh.extract_surface().triangulate()


def write_primitive(spec: Primitive, case_dir: Path, name: str) -> Surface:
    """Generate (or regenerate) a primitive's STL into the case and analyze it.
    Overwrites constant/triSurface/<name>.stl, so editing is just re-writing."""
    dest = case_dir / "constant" / "triSurface" / f"{name}.stl"
    dest.parent.mkdir(parents=True, exist_ok=True)
    mesh = primitive_mesh(spec)
    mesh.save(str(dest), binary=True)
    diag = analyze(dest)
    return Surface(name=name, stl_path=f"(created in FlowDesk: {spec.shape})",
                   scale=1.0, diagnostics=diag, primitive=spec)


def unique_surface_name(existing: list[str], base: str) -> str:
    """base, base2, base3 … (OpenFOAM word), avoiding collisions."""
    word = re.sub(r"[^A-Za-z0-9_]", "_", base) or "geom"
    if not word[0].isalpha():
        word = "g_" + word
    if word not in existing:
        return word
    i = 2
    while f"{word}{i}" in existing:
        i += 1
    return f"{word}{i}"
