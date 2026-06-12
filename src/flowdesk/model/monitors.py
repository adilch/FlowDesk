"""Runtime monitors (PRD §11 Phase-2 / §4.7 function-object slot).

User-requested quantities written during the solve via OpenFOAM function
objects: forces & coefficients, flow rate through patches, field min/max/
average, and point probes. Each writes a postProcessing/<name>/ time series
that FlowDesk plots live and in Results.

Headless model only; flowdesk.foam.generators emits the function-object dicts
and flowdesk.exec.monitors_io reads the output files back.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field

from flowdesk.model.geometry import Vec3


class ForcesMonitor(BaseModel):
    """Forces & force coefficients (drag/lift/moment) on patches.

    Incompressible (kinematic) solvers use a constant reference density rho_inf.
    Coefficients need the freestream speed and reference area/length."""

    kind: Literal["forces"] = "forces"
    name: str = "forces"
    patches: list[str] = Field(default_factory=list)
    rho_inf: float = 1.225  # kg/m^3 reference density (incompressible)
    u_inf: float = 1.0  # m/s freestream speed (for coefficients)
    a_ref: float = 1.0  # m^2 reference area
    l_ref: float = 1.0  # m reference length
    lift_dir: Vec3 = (0.0, 0.0, 1.0)
    drag_dir: Vec3 = (1.0, 0.0, 0.0)
    pitch_axis: Vec3 = (0.0, 1.0, 0.0)
    centre_of_rotation: Vec3 = (0.0, 0.0, 0.0)


class FlowRateMonitor(BaseModel):
    """Volumetric flow rate through a patch (sum of phi)."""

    kind: Literal["flowRate"] = "flowRate"
    name: str = "flowRate"
    patch: str = ""


class FieldValueMonitor(BaseModel):
    """A whole-domain reduction of a field (average / min / max)."""

    kind: Literal["fieldValue"] = "fieldValue"
    name: str = "fieldValue"
    field: str = "U"
    operation: Literal["volAverage", "max", "min"] = "volAverage"


class ProbesMonitor(BaseModel):
    """Sample field(s) at fixed points over time."""

    kind: Literal["probes"] = "probes"
    name: str = "probes"
    fields: list[str] = Field(default_factory=lambda: ["U", "p"])
    locations: list[Vec3] = Field(default_factory=list)


Monitor = Annotated[
    ForcesMonitor | FlowRateMonitor | FieldValueMonitor | ProbesMonitor,
    Field(discriminator="kind"),
]
