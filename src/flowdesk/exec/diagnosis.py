"""Smart divergence diagnosis (PRD §4.7 honesty, grown into an advisor).

Watches the parsed solver signals (residuals, Courant, bounding) and, when a run
is going wrong, produces a plain-language diagnosis with concrete fixes - and a
machine `action` key the Run stage can offer as a one-click remedy for the next
run. Headless: no Qt; driven by a SolverLogParser.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from flowdesk.exec.residuals import SolverLogParser

_HUGE = 1e6
_TURB_FIELDS = {"k", "omega", "epsilon", "nut"}


@dataclass(frozen=True)
class Diagnosis:
    headline: str
    detail: str
    suggestions: list[str]
    action: str | None = None  # "robust" | "lower_courant" | None
    action_label: str = ""


def _bad(v: float) -> bool:
    return math.isnan(v) or math.isinf(v)


def _series_state(series: list[tuple[float, float]]) -> str | None:
    """'nan' | 'huge' | 'climbing' | None for one field's residual history."""
    if len(series) < 6:
        return None
    recent = [v for _t, v in series[-6:]]
    if any(_bad(v) for v in recent):
        return "nan"
    last = recent[-1]
    if last > _HUGE:
        return "huge"
    rising = recent[-1] > recent[-3] > recent[-5]
    # only flag a real climb: residual is non-trivial, well above its recent
    # floor, and trending up (near-convergence noise stays small and is ignored)
    if last > 0.1 and last > min(recent) * 20 and rising:
        return "climbing"
    return None


def _courant_runaway(courant_max: list[tuple[float, float]], target: float) -> bool:
    if len(courant_max) < 4:
        return False
    recent = [mx for _mean, mx in courant_max[-4:]]
    rising = recent[-1] > recent[-2] > recent[-3]
    return recent[-1] >= target * 3 and rising


class DivergenceMonitor:
    """Feed the parser periodically; diagnose() returns a Diagnosis or None."""

    def __init__(self, steady: bool, courant_target: float = 1.0):
        self.steady = steady
        self.courant_target = courant_target

    def diagnose(self, parser: SolverLogParser) -> Diagnosis | None:
        # 1. hard divergence: any field went NaN/inf or astronomically large
        states = {f: _series_state(s) for f, s in parser.residuals.items()}
        nan_fields = [f for f, st in states.items() if st in ("nan", "huge")]
        if nan_fields:
            return Diagnosis(
                headline="The solution diverged (a value became infinite).",
                detail=f"Field(s) {', '.join(sorted(nan_fields))} blew up.",
                suggestions=[
                    "Switch Numerics to the Robust preset (bounded upwind, lower "
                    "relaxation) and rerun.",
                    "Check the mesh: high non-orthogonality or skew cells often "
                    "trigger this (Mesh stage quality report).",
                    "Make sure boundary conditions are physical (e.g. a pressure "
                    "outlet exists, inlet velocity is sane).",
                ],
                action="robust", action_label="Apply Robust numerics")

        # 2. residuals climbing instead of falling
        climbing = [f for f, st in states.items() if st == "climbing"]
        if climbing:
            extra = []
            if not self.steady:
                extra.append("Lower the max Courant number and initial Δt "
                             "(Physics / Run) so each step is smaller.")
            return Diagnosis(
                headline="Residuals are climbing — the run is starting to diverge.",
                detail=f"{', '.join(sorted(climbing))} rising over the last steps "
                       "instead of falling.",
                suggestions=[
                    "Switch Numerics to the Robust preset and rerun.",
                    "Lower the relaxation factors (p and U) if you are on Custom.",
                    *extra,
                ],
                action="robust", action_label="Apply Robust numerics")

        # 3. transient Courant runaway
        if not self.steady and _courant_runaway(parser.courant_max, self.courant_target):
            peak = parser.courant_max[-1][1]
            return Diagnosis(
                headline=f"Courant number is running away (max ≈ {peak:.1f}).",
                detail="The time step is too large for the flow speed and cell "
                       "size; the interface/flow crosses several cells per step.",
                suggestions=[
                    "Lower the max Courant number (e.g. halve it) so adjustTimeStep "
                    "shrinks Δt.",
                    "Reduce the initial Δt.",
                    "Refine the mesh where velocities are highest.",
                ],
                action="lower_courant", action_label="Halve max Courant")

        # 4. turbulence fields repeatedly bounded
        bounded_turb = parser.bounding_fields & _TURB_FIELDS
        if len(bounded_turb) >= 1 and len(parser.times) >= 20 \
                and any(states.get(f) == "climbing" for f in _TURB_FIELDS):
            return Diagnosis(
                headline="Turbulence fields are being bounded repeatedly.",
                detail=f"{', '.join(sorted(bounded_turb))} keep hitting their "
                       "limiter — usually poor near-wall mesh or a bad turbulence "
                       "initial guess.",
                suggestions=[
                    "Use the Robust preset and a lower freestream turbulence "
                    "intensity to start.",
                    "Improve near-wall mesh quality / layer coverage (Mesh stage).",
                ],
                action="robust", action_label="Apply Robust numerics")

        return None
