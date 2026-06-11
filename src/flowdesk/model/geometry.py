"""Geometry stage model (PRD §4.2)."""

from __future__ import annotations

from typing import Annotated, Literal

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


# --- In-app authored primitives (PRD §13 was "no CAD"; these are parametric
# surfaces generated to STL, not a CAD kernel). A Surface carrying a primitive
# spec can be re-edited and regenerated; imported STLs carry primitive=None. ---


class BoxPrimitive(BaseModel):
    shape: Literal["box"] = "box"
    min: Vec3 = (0.0, 0.0, 0.0)
    max: Vec3 = (1.0, 1.0, 1.0)


class SpherePrimitive(BaseModel):
    shape: Literal["sphere"] = "sphere"
    centre: Vec3 = (0.0, 0.0, 0.0)
    radius: float = 0.5


class CylinderPrimitive(BaseModel):
    shape: Literal["cylinder"] = "cylinder"
    point1: Vec3 = (0.0, 0.0, 0.0)
    point2: Vec3 = (0.0, 0.0, 1.0)
    radius: float = 0.5


class ConePrimitive(BaseModel):
    shape: Literal["cone"] = "cone"
    base_centre: Vec3 = (0.0, 0.0, 0.0)
    direction: Vec3 = (0.0, 0.0, 1.0)
    radius: float = 0.5
    height: float = 1.0


class PlanePrimitive(BaseModel):
    shape: Literal["plane"] = "plane"
    centre: Vec3 = (0.0, 0.0, 0.0)
    normal: Vec3 = (0.0, 0.0, 1.0)
    i_size: float = 1.0
    j_size: float = 1.0


Primitive = Annotated[
    BoxPrimitive | SpherePrimitive | CylinderPrimitive | ConePrimitive | PlanePrimitive,
    Field(discriminator="shape"),
]


class Surface(BaseModel):
    """One STL surface — imported or authored in-app. Name must be an OpenFOAM
    word (validated in validate_full)."""

    name: str
    stl_path: str  # original source file (case copy lives at constant/triSurface/<name>.stl)
    scale: float = 1.0  # applied to the copy; original untouched (§4.2)
    diagnostics: SurfaceDiagnostics = Field(default_factory=SurfaceDiagnostics)
    # Set for in-app primitives so they can be re-edited/regenerated; None = import
    primitive: Primitive | None = None


class GeometryModel(BaseModel):
    surfaces: list[Surface] = Field(default_factory=list)
    # blockMesh-only workflow is legal with zero surfaces if explicitly chosen (§4.2)
    blockmesh_only: bool = False
