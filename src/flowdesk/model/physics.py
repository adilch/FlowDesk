"""Physics stage model (PRD §4.4): time treatment, turbulence, fluid, reference values."""

from __future__ import annotations

import math
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field

C_MU = 0.09


class Turbulence(Enum):
    LAMINAR = "laminar"
    K_EPSILON = "kEpsilon"
    K_OMEGA_SST = "kOmegaSST"


class SteadyTime(BaseModel):
    kind: Literal["steady"] = "steady"


class TransientTime(BaseModel):
    kind: Literal["transient"] = "transient"
    end_time: float = 1.0  # s; ERROR if <= 0
    output_interval: float = 0.1  # s
    max_courant: float = 1.0  # drives adjustTimeStep
    initial_dt: float = 1e-3  # s


class Fluid(BaseModel):
    """Kinematic viscosity presets (§4.4); name 'custom' allows arbitrary nu.

    rho is only consulted by multiphase solvers (interFoam needs phase
    densities); single-phase incompressible cases never write it."""

    name: str = "water"
    nu: float = 1.0e-6  # m^2/s
    rho: float = 1000.0  # kg/m^3


FLUID_PRESETS = {
    "water": Fluid(name="water", nu=1.0e-6, rho=1000.0),
    "air": Fluid(name="air", nu=1.48e-5, rho=1.0),
}


class FreeSurfaceModel(BaseModel):
    """Two-phase free surface via interFoam (Phase 2, PRD §1.3/§11).

    The primary Physics fluid is the heavy phase ('water'); this model adds
    the light phase, surface tension, gravity, and the initial water region
    (applied by setFields before the first solve)."""

    light_phase: Fluid = Field(default_factory=lambda: FLUID_PRESETS["air"].model_copy())
    sigma: float = 0.07  # surface tension, N/m (water-air)
    gravity: tuple[float, float, float] = (0.0, 0.0, -9.81)
    # initial water column (box, SI): alpha.water = 1 inside, 0 elsewhere
    water_column_min: tuple[float, float, float] = (0.0, 0.0, 0.0)
    water_column_max: tuple[float, float, float] = (0.1, 0.1, 0.1)


class ScalarTransportModel(BaseModel):
    """Passive scalar transport (mixing / tracers) on the existing flow.

    Solved as a scalarTransport function object riding on simpleFoam/pimpleFoam:
    a dimensionless concentration field is convected by the flow's flux and
    diffused with the given diffusivity. Injected at velocity inlets."""

    field: str = "s"  # OpenFOAM field name (a word)
    diffusivity: float = 1e-5  # m^2/s
    inlet_value: float = 1.0  # concentration carried in at velocity inlets


class TurbRef(BaseModel):
    """Reference values for turbulence initialization (§4.4)."""

    velocity_scale: float = 1.0  # m/s
    intensity: float = 5.0  # percent
    length_scale: float = 0.07  # m


class PhysicsModel(BaseModel):
    time: SteadyTime | TransientTime = Field(default_factory=SteadyTime, discriminator="kind")
    turbulence: Turbulence = Turbulence.K_OMEGA_SST
    fluid: Fluid = Field(default_factory=lambda: FLUID_PRESETS["water"].model_copy())
    turb_ref: TurbRef = Field(default_factory=TurbRef)
    # None = single-phase (MVP behavior); set = interFoam free surface (Phase 2)
    free_surface: FreeSurfaceModel | None = None
    # None = no passive scalar; set = transport a tracer on the flow (Phase 2)
    scalar_transport: ScalarTransportModel | None = None

    @property
    def solver(self) -> str:
        """Users think in physics; the solver name stays visible for transparency (§4.4)."""
        if self.free_surface is not None:
            return "interFoam"
        return "simpleFoam" if isinstance(self.time, SteadyTime) else "pimpleFoam"

    @property
    def is_steady(self) -> bool:
        return isinstance(self.time, SteadyTime)

    # Derived turbulence defaults (§4.4 formulas), from given U and the reference I, L.
    def k_from(self, velocity_scale: float | None = None) -> float:
        u = self.turb_ref.velocity_scale if velocity_scale is None else velocity_scale
        i = self.turb_ref.intensity / 100.0
        return 1.5 * (i * u) ** 2

    def omega_from(self, velocity_scale: float | None = None) -> float:
        k = self.k_from(velocity_scale)
        return math.sqrt(k) / (C_MU**0.25 * self.turb_ref.length_scale)

    def epsilon_from(self, velocity_scale: float | None = None) -> float:
        k = self.k_from(velocity_scale)
        return C_MU**0.75 * k**1.5 / self.turb_ref.length_scale
