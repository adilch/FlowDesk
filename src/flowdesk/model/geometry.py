"""Geometry stage model (PRD §4.2)."""

from __future__ import annotations

from pydantic import BaseModel, Field

Vec3 = tuple[float, float, float]


class SurfaceDiagnostics(BaseModel):
    """Import-time diagnostics, recorded for staleness and validation."""

    triangle_count: int = 0
    bounds_min: Vec3 = (0.0, 0.0, 0.0)
    bounds_max: Vec3 = (0.0, 0.0, 0.0)
    watertight: bool = False
    self_intersecting: bool = False
    normals_outward: bool = True


class Surface(BaseModel):
    """One imported STL surface. Name must be an OpenFOAM word (validated in validate_full)."""

    name: str
    stl_path: str  # original source file (case copy lives at constant/triSurface/<name>.stl)
    scale: float = 1.0  # applied to the copy; original untouched (§4.2)
    diagnostics: SurfaceDiagnostics = Field(default_factory=SurfaceDiagnostics)


class GeometryModel(BaseModel):
    surfaces: list[Surface] = Field(default_factory=list)
    # blockMesh-only workflow is legal with zero surfaces if explicitly chosen (§4.2)
    blockmesh_only: bool = False
