"""Run stage surfaces the divergence diagnosis with a one-click fix."""

from __future__ import annotations

from types import SimpleNamespace

from PyQt6.QtWidgets import QLabel

from flowdesk.app import projects
from flowdesk.exec.residuals import SolverLogParser
from flowdesk.model.numerics import Preset
from flowdesk.platform.commands import Environment
from flowdesk.ui.components import Banner

_ENV = Environment(False, True, None, "test")


def _banner_text(stage) -> str:
    return " ".join(w.text() for b in stage.findChildren(Banner)
                    for w in b.findChildren(QLabel))


def _diverging_parser() -> SolverLogParser:
    p = SolverLogParser()
    for i, v in enumerate([1e-2, 5e-3, 1e-2, 0.05, 0.2, 0.5, 1.0, 2.0]):
        p.feed(f"Time = {i + 1}")
        p.feed(f"smoothSolver:  Solving for Ux, Initial residual = {v}, "
               "Final residual = 1e-9, No Iterations 5")
    return p


def test_run_stage_shows_diagnosis_and_applies_robust(qtbot, tmp_path) -> None:
    from flowdesk.ui.stages.run import RunStage

    session = projects.create_project("dv", tmp_path, "Lid-driven cavity")
    # start on an Accurate (non-robust) preset so the fix is a real change
    from flowdesk.model.numerics import make_preset

    session.model.numerics = make_preset(Preset.ACCURATE)
    stage = RunStage(session, _ENV)
    qtbot.addWidget(stage)
    stage._reset_monitoring()
    stage._run_started_at = None
    stage.supervisor = SimpleNamespace(parser=_diverging_parser())

    stage._refresh_monitoring()
    assert stage._diagnosis_shown, "a diverging run must be diagnosed"
    assert "climbing" in _banner_text(stage).lower()

    # the one-click fix sets Robust numerics for the rerun
    stage._apply_fix("robust")
    assert session.model.numerics.preset is Preset.ROBUST


def test_no_diagnosis_on_healthy_run(qtbot, tmp_path) -> None:
    from flowdesk.ui.stages.run import RunStage

    session = projects.create_project("ok", tmp_path, "Lid-driven cavity")
    stage = RunStage(session, _ENV)
    qtbot.addWidget(stage)
    stage._reset_monitoring()
    stage._run_started_at = None

    p = SolverLogParser()
    for i, v in enumerate([1e-1, 3e-2, 1e-2, 3e-3, 1e-3, 3e-4, 1e-4, 1e-5]):
        p.feed(f"Time = {i + 1}")
        p.feed(f"smoothSolver:  Solving for Ux, Initial residual = {v}, "
               "Final residual = 1e-9, No Iterations 5")
    stage.supervisor = SimpleNamespace(parser=p)
    stage._refresh_monitoring()
    assert not stage._diagnosis_shown
