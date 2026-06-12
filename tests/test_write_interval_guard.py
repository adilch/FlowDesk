"""Guard against write-interval-past-endTime producing zero results.

User hit this: an interFoam run reached endTime=10 s but writeInterval was 200 s
(the steady default leaked into the transient run), so adjustableRunTime never
saved a frame and reconstructPar reported 'No times selected'.
"""

from __future__ import annotations

from flowdesk.app import projects
from flowdesk.exec.errors import explain
from flowdesk.foam import generators
from flowdesk.model.findings import Severity, Stage
from flowdesk.model.physics import TransientTime


def _foam_value(text: str, key: str) -> str:
    for line in text.splitlines():
        line = line.strip()
        if line.startswith(key + " ") or line.startswith(key + "\t"):
            return line.split(maxsplit=1)[1].rstrip(";").strip()
    raise AssertionError(f"{key} not found")


def test_validation_flags_interval_past_endtime(tmp_path) -> None:
    session = projects.create_project("g", tmp_path, "Dam break (3D breach)")
    session.model.physics.time = TransientTime(end_time=10.0, output_interval=200.0)
    findings = session.model.validate_full()
    blocking = [f for f in findings
                if f.severity is Severity.ERROR and f.stage is Stage.RUN
                and "without writing any results" in f.message]
    assert blocking, "interval > endTime must be a blocking error"


def test_generator_clamps_transient_write_interval(tmp_path) -> None:
    session = projects.create_project("c", tmp_path, "Dam break (3D breach)")
    session.model.physics.time = TransientTime(end_time=10.0, output_interval=200.0)
    control = generators.control_dict(session.model)
    # safety net: the final frame is always written
    assert float(_foam_value(control, "writeInterval")) == 10.0
    assert _foam_value(control, "writeControl") == "adjustableRunTime"


def test_normal_interval_unchanged(tmp_path) -> None:
    session = projects.create_project("n", tmp_path, "Dam break (3D breach)")
    session.model.physics.time = TransientTime(end_time=10.0, output_interval=0.25)
    control = generators.control_dict(session.model)
    assert float(_foam_value(control, "writeInterval")) == 0.25


def test_run_stage_refresh_resyncs_to_transient(qtbot, tmp_path) -> None:
    from flowdesk.platform.commands import Environment
    from flowdesk.ui.stages.run import RunStage

    env = Environment(False, True, None, "test")
    # start steady: write control shows 200 "iterations"
    session = projects.create_project("r", tmp_path, "Lid-driven cavity")
    stage = RunStage(session, env)
    qtbot.addWidget(stage)
    assert "iterations" in stage.write_every_label.text()
    assert stage.write_interval.value() == session.model.run.write_interval_steady

    # switch to interFoam/transient, then re-enter the Run stage
    from flowdesk.app import scenario

    scenario.apply_manual_solver(session.model, "interFoam")
    stage.refresh_write_controls()
    assert "seconds" in stage.write_every_label.text()
    assert stage.write_interval.value() == session.model.physics.time.output_interval
    assert stage.write_interval.value() != 200  # the steady value did not leak


def test_no_times_error_explained() -> None:
    log = ("--> FOAM Warning :\n    in file reconstructPar.C at line 271\n"
           "    No times selected")
    explanation = explain(log)
    assert "write interval" in explanation.lower()
    assert "end time" in explanation.lower()
