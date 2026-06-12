"""Smart divergence diagnosis from parsed solver signals."""

from __future__ import annotations

from flowdesk.exec.diagnosis import DivergenceMonitor
from flowdesk.exec.residuals import SolverLogParser


def _parser_with_residuals(field: str, values: list[float]) -> SolverLogParser:
    p = SolverLogParser()
    for i, v in enumerate(values):
        p.feed(f"Time = {i + 1}")
        p.feed(f"smoothSolver:  Solving for {field}, Initial residual = {v}, "
               "Final residual = 1e-9, No Iterations 3")
    return p


def test_healthy_convergence_is_not_flagged() -> None:
    # residuals falling smoothly -> no diagnosis
    p = _parser_with_residuals("Ux", [1e-1, 3e-2, 1e-2, 3e-3, 1e-3, 3e-4, 1e-4, 1e-5])
    assert DivergenceMonitor(steady=True).diagnose(p) is None


def test_near_convergence_noise_is_not_flagged() -> None:
    # tiny residuals bouncing around 1e-6 must not look like a "climb"
    p = _parser_with_residuals("p", [1e-6, 2e-6, 1e-6, 3e-6, 1e-6, 2e-6, 4e-6])
    assert DivergenceMonitor(steady=True).diagnose(p) is None


def test_nan_residual_is_divergence() -> None:
    p = _parser_with_residuals("Ux", [1e-2, 1e-1, 1.0, float("nan"), float("nan"),
                                      float("nan")])
    d = DivergenceMonitor(steady=True).diagnose(p)
    assert d is not None
    assert "diverged" in d.headline.lower()
    assert d.action == "robust"
    assert any("Robust" in s for s in d.suggestions)


def test_huge_residual_is_divergence() -> None:
    p = _parser_with_residuals("p", [1.0, 10.0, 1e3, 1e5, 1e7, 1e9])
    d = DivergenceMonitor(steady=True).diagnose(p)
    assert d is not None and d.action == "robust"


def test_climbing_residuals_flagged() -> None:
    # falls a bit then climbs steadily toward O(1)
    p = _parser_with_residuals("Ux", [1e-2, 5e-3, 1e-2, 0.05, 0.2, 0.5, 1.0, 2.0])
    d = DivergenceMonitor(steady=True).diagnose(p)
    assert d is not None
    assert "climbing" in d.headline.lower()
    assert d.action == "robust"


def test_climbing_transient_suggests_courant() -> None:
    p = _parser_with_residuals("Ux", [1e-2, 5e-3, 1e-2, 0.05, 0.2, 0.5, 1.0, 2.0])
    d = DivergenceMonitor(steady=False).diagnose(p)
    assert d is not None
    assert any("Courant" in s for s in d.suggestions)


def test_courant_runaway_flagged() -> None:
    p = SolverLogParser()
    for i, c in enumerate([0.8, 1.5, 3.0, 6.0]):
        p.feed(f"Time = {i + 1}")
        p.feed(f"Courant Number mean: {c / 3:.3f} max: {c:.3f}")
    d = DivergenceMonitor(steady=False, courant_target=1.0).diagnose(p)
    assert d is not None
    assert "Courant" in d.headline
    assert d.action == "lower_courant"


def test_stable_courant_not_flagged() -> None:
    p = SolverLogParser()
    for i, c in enumerate([0.8, 0.9, 0.85, 0.9, 0.88]):
        p.feed(f"Time = {i + 1}")
        p.feed(f"Courant Number mean: {c / 3:.3f} max: {c:.3f}")
    assert DivergenceMonitor(steady=False, courant_target=1.0).diagnose(p) is None


def test_empty_parser_is_safe() -> None:
    assert DivergenceMonitor(steady=True).diagnose(SolverLogParser()) is None
