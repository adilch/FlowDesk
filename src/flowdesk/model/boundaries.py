"""Boundary Conditions stage model (PRD §4.5): physical BC types, an open union.

These classes know nothing about files; the adapter (flowdesk.foam.bc_matrix)
expands them into per-field entries per turbulence model / solver.

SimFlow-inspired two-layer system:
  1. a physical "character" (VelocityInlet, PressureOutlet, Wall, ...) that
     generates a consistent set of fields automatically, and
  2. optional per-field overrides (`overrides`) that replace the generated
     entry for one field with a user-chosen OpenFOAM patch-field type.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field

from flowdesk.model.geometry import Vec3


class FieldOverride(BaseModel):
    """A user override for one field at one patch: a raw OpenFOAM patch-field
    type plus its parameters, replacing the generated (managed) entry.

    `value` is the full RHS expression (e.g. 'uniform (2 0 0)'); empty omits the
    value line. `extra` carries any additional keyword entries the type needs
    (inletValue, p0, gradient, ...)."""

    patch_type: str
    value: str = ""
    extra: dict[str, str] = Field(default_factory=dict)


class _BC(BaseModel):
    """Common base: every physical BC can carry per-field overrides."""

    overrides: dict[str, FieldOverride] = Field(default_factory=dict)


class InletTurbulence(BaseModel):
    """Turbulence spec at an inlet: intensity+length (defaults from Physics) or direct values."""

    mode: Literal["intensity", "direct"] = "intensity"
    intensity: float | None = None  # percent; None -> Physics turb_ref
    length_scale: float | None = None  # m; None -> Physics turb_ref
    k: float | None = None  # used when mode == direct
    omega: float | None = None
    epsilon: float | None = None


# Inlet velocity specification (SimFlow-style sub-types)
InletSpec = Literal["normal", "vector", "volumetricFlowRate", "massFlowRate", "pressure"]


class VelocityInlet(_BC):
    kind: Literal["velocityInlet"] = "velocityInlet"
    mode: InletSpec = "normal"
    speed: float = 1.0  # m/s, used when mode == normal (positive into the domain)
    vector: Vec3 = (1.0, 0.0, 0.0)  # used when mode == vector
    volumetric_flow_rate: float = 0.1  # m^3/s, used when mode == volumetricFlowRate
    mass_flow_rate: float = 1.0  # kg/s, used when mode == massFlowRate
    # used when mode == pressure (kinematic m^2/s^2, or Pa for interFoam)
    inlet_pressure: float = 0.0
    turbulence: InletTurbulence = Field(default_factory=InletTurbulence)
    # Free-surface cases only: phase fraction carried in by the inflow.
    # 1.0 = pure water (submerged inlet); None = zeroGradient (the face spans
    # both phases - e.g. a reservoir inlet taller than the water level)
    alpha_water: float | None = 1.0


# Pressure-outlet sub-types
OutletType = Literal["fixedValue", "totalPressure", "fixedFlux"]


class PressureOutlet(_BC):
    kind: Literal["pressureOutlet"] = "pressureOutlet"
    outlet_type: OutletType = "fixedValue"
    gauge_pressure: float = 0.0  # kinematic, m^2/s^2 (p/rho); used by fixedValue
    total_pressure: float = 0.0  # stagnation pressure; used by totalPressure


class Wall(_BC):
    kind: Literal["wall"] = "wall"
    moving_velocity: Vec3 | None = None  # None -> noSlip


class SlipWall(_BC):
    kind: Literal["slip"] = "slip"


class Symmetry(_BC):
    kind: Literal["symmetry"] = "symmetry"


class Outflow(_BC):
    kind: Literal["outflow"] = "outflow"  # zero-gradient; UI warns "prefer Pressure outlet"


class Empty(_BC):
    kind: Literal["empty"] = "empty"  # 2D cases


class Atmosphere(_BC):
    """Open boundary to still air (free-surface cases, Phase 2): total pressure
    reference, air enters on backflow. The §4.5 union was left open for this."""

    kind: Literal["atmosphere"] = "atmosphere"


PhysicalBC = Annotated[
    VelocityInlet | PressureOutlet | Wall | SlipWall | Symmetry | Outflow | Empty
    | Atmosphere,
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
    "atmosphere": "patch",
}
