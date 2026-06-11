"""Boundary Conditions stage model (PRD §4.5): physical BC types, an open union.

These classes know nothing about files; the adapter (flowdesk.foam.bc_matrix)
expands them into per-field entries per turbulence model.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field

from flowdesk.model.geometry import Vec3


class InletTurbulence(BaseModel):
    """Turbulence spec at an inlet: intensity+length (defaults from Physics) or direct values."""

    mode: Literal["intensity", "direct"] = "intensity"
    intensity: float | None = None  # percent; None -> Physics turb_ref
    length_scale: float | None = None  # m; None -> Physics turb_ref
    k: float | None = None  # used when mode == direct
    omega: float | None = None
    epsilon: float | None = None


class VelocityInlet(BaseModel):
    kind: Literal["velocityInlet"] = "velocityInlet"
    mode: Literal["normal", "vector"] = "normal"
    speed: float = 1.0  # m/s, used when mode == normal (positive into the domain)
    vector: Vec3 = (1.0, 0.0, 0.0)  # used when mode == vector
    turbulence: InletTurbulence = Field(default_factory=InletTurbulence)


class PressureOutlet(BaseModel):
    kind: Literal["pressureOutlet"] = "pressureOutlet"
    gauge_pressure: float = 0.0  # kinematic, m^2/s^2 (p/rho)


class Wall(BaseModel):
    kind: Literal["wall"] = "wall"
    moving_velocity: Vec3 | None = None  # None -> noSlip


class SlipWall(BaseModel):
    kind: Literal["slip"] = "slip"


class Symmetry(BaseModel):
    kind: Literal["symmetry"] = "symmetry"


class Outflow(BaseModel):
    kind: Literal["outflow"] = "outflow"  # zero-gradient; UI warns "prefer Pressure outlet"


class Empty(BaseModel):
    kind: Literal["empty"] = "empty"  # 2D cases


PhysicalBC = Annotated[
    VelocityInlet | PressureOutlet | Wall | SlipWall | Symmetry | Outflow | Empty,
    Field(discriminator="kind"),
]

# blockMeshDict boundary type implied by each physical BC (§4.3.1 / §4.5 consistency)
BLOCK_PATCH_TYPE = {
    "velocityInlet": "patch",
    "pressureOutlet": "patch",
    "wall": "wall",
    "slip": "patch",
    "symmetry": "symmetry",
    "outflow": "patch",
    "empty": "empty",
}
