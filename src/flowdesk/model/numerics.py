"""Numerics stage model (PRD §4.6): presets resolve to explicit values; Custom = any touch."""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class Preset(Enum):
    ROBUST = "robust"
    BALANCED = "balanced"
    ACCURATE = "accurate"
    CUSTOM = "custom"


class SolverSettings(BaseModel):
    tolerance: float
    rel_tol: float


class ResidualTargets(BaseModel):
    p: float = 1e-4
    u: float = 1e-5
    turb: float = 1e-5


class Relaxation(BaseModel):
    p: float = 0.3
    u: float = 0.5
    turb: float = 0.5


class FirstOrderStart(BaseModel):
    """Two-leg managed run: upwind to iteration N, then preset target schemes (§4.6)."""

    enabled: bool = True
    switch_iteration: int = 200


class TransientNumerics(BaseModel):
    ddt_scheme: str = "Euler"  # Robust: Euler; Accurate: backward
    n_outer_correctors: int = 1  # 1 = PISO-mode default
    n_correctors: int = 2
    momentum_predictor: bool = True


class NumericsModel(BaseModel):
    preset: Preset = Preset.ROBUST
    div_u: str = "bounded Gauss upwind"
    div_turb: str = "bounded Gauss upwind"
    grad_scheme: str = "cellLimited Gauss linear 1"
    laplacian_scheme: str = "Gauss linear limited 0.5"
    sn_grad_scheme: str = "limited 0.5"
    p_solver: SolverSettings = Field(
        default_factory=lambda: SolverSettings(tolerance=1e-7, rel_tol=0.01)
    )
    u_solver: SolverSettings = Field(
        default_factory=lambda: SolverSettings(tolerance=1e-8, rel_tol=0.1)
    )
    relaxation: Relaxation = Field(default_factory=Relaxation)
    simple_consistent: bool = False
    # None -> auto from checkMesh maxNonOrtho (cross-stage intelligence, §4.6)
    n_non_orthogonal_correctors: int | None = None
    residual_targets: ResidualTargets = Field(default_factory=ResidualTargets)
    first_order_start: FirstOrderStart = Field(default_factory=FirstOrderStart)
    transient: TransientNumerics = Field(default_factory=TransientNumerics)


def make_preset(preset: Preset) -> NumericsModel:
    """Resolve a preset to explicit values (§4.6 table). CUSTOM starts from ROBUST."""
    if preset in (Preset.ROBUST, Preset.CUSTOM):
        return NumericsModel(preset=preset)
    if preset is Preset.BALANCED:
        return NumericsModel(
            preset=preset,
            div_u="bounded Gauss linearUpwind grad(U)",
            div_turb="bounded Gauss upwind",
            grad_scheme="Gauss linear",
            laplacian_scheme="Gauss linear limited 0.777",
            sn_grad_scheme="limited 0.777",
            relaxation=Relaxation(p=0.7, u=0.9, turb=0.7),
            simple_consistent=True,
        )
    return NumericsModel(  # ACCURATE
        preset=preset,
        div_u="bounded Gauss linearUpwind grad(U)",
        div_turb="bounded Gauss limitedLinear 1",
        grad_scheme="Gauss linear",
        laplacian_scheme="Gauss linear corrected",
        sn_grad_scheme="corrected",
        p_solver=SolverSettings(tolerance=1e-7, rel_tol=0.001),
        relaxation=Relaxation(p=0.7, u=0.9, turb=0.7),
        simple_consistent=True,
        residual_targets=ResidualTargets(p=1e-5, u=1e-6, turb=1e-5),
        transient=TransientNumerics(ddt_scheme="backward"),
    )


def auto_non_orth_correctors(max_non_ortho: float | None) -> int:
    """§4.6 rule: 0 if maxNonOrtho<60, 1 if 60-70, 2 if >70; 1 when mesh not yet checked."""
    if max_non_ortho is None:
        return 1
    if max_non_ortho < 60:
        return 0
    if max_non_ortho <= 70:
        return 1
    return 2


class RunMode(Enum):
    SERIAL = "serial"
    PARALLEL = "parallel"


class RunModel(BaseModel):
    """Run stage (PRD §4.7)."""

    mode: RunMode = RunMode.PARALLEL
    cores: int = 4
    decomposition: Literal["scotch", "hierarchical", "simple"] = "scotch"
    hierarchical_n: tuple[int, int, int] = (2, 2, 1)
    max_iterations: int = 2000  # steady end criterion
    write_interval_steady: int = 200
    purge_write: int = 2
