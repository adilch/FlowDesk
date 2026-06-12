"""Monitors panel (config) + Run-stage live monitor plot."""

from __future__ import annotations

from flowdesk.app import projects
from flowdesk.model.monitors import FlowRateMonitor
from flowdesk.platform.commands import Environment

_ENV = Environment(False, True, None, "test")


def test_monitors_panel_add_and_remove(qtbot, tmp_path) -> None:
    from flowdesk.ui.stages.monitors_panel import MonitorsPanel

    session = projects.create_project("p", tmp_path, "Pipe flow")
    panel = MonitorsPanel(session)
    qtbot.addWidget(panel)
    assert panel.list.count() == 0

    panel._commit(FlowRateMonitor(name="q", patch="outlet"))
    assert panel.list.count() == 1
    assert len(session.model.monitors) == 1

    # duplicate names are made unique
    panel._commit(FlowRateMonitor(name="q", patch="inlet"))
    assert session.model.monitors[1].name == "q2"

    panel.list.setCurrentRow(0)
    panel._remove()
    assert len(session.model.monitors) == 1
    assert session.model.monitors[0].name == "q2"


def test_run_stage_shows_monitor_plot_when_configured(qtbot, tmp_path) -> None:
    from flowdesk.ui.stages.run import RunStage

    session = projects.create_project("r", tmp_path, "Pipe flow")
    stage = RunStage(session, _ENV)
    qtbot.addWidget(stage)
    assert not stage.monitor_plot.isVisible()  # no monitors yet

    stage.monitors_panel._commit(FlowRateMonitor(name="q", patch="outlet"))
    assert stage.monitor_plot.isVisibleTo(stage)


def test_run_stage_plots_monitor_series(qtbot, tmp_path) -> None:
    from flowdesk.ui.stages.run import RunStage

    session = projects.create_project("r", tmp_path, "Pipe flow")
    session.model.monitors = [FlowRateMonitor(name="q", patch="outlet")]
    # fake postProcessing output
    out = session.case_dir / "postProcessing" / "q" / "0" / "surfaceFieldValue.dat"
    out.parent.mkdir(parents=True)
    out.write_text("# Time sum(phi)\n1 0.5\n2 0.6\n3 0.65\n", encoding="utf-8")

    stage = RunStage(session, _ENV)
    qtbot.addWidget(stage)
    stage._refresh_monitor_plot()
    assert any("flow rate" in k for k in stage._monitor_curves)
