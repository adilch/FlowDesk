"""Results stage: play/pause animation through time steps + color-range filter."""

from __future__ import annotations

import subprocess

import pytest

from flowdesk.app import projects, results_io
from flowdesk.platform.commands import Environment, openfoam_argv, probe_environment
from flowdesk.ui.stages.results import ResultsStage
from flowdesk.ui.viewer import ViewerWidget

_ENV = probe_environment()
_TEST_ENV = Environment(False, True, None, "test")

requires_openfoam = pytest.mark.skipif(
    not _ENV.available, reason=f"OpenFOAM not reachable: {_ENV.detail}")


def _stage(qtbot, tmp_path):
    session = projects.create_project("anim", tmp_path, "Lid-driven cavity")
    viewer = ViewerWidget()
    qtbot.addWidget(viewer)
    stage = ResultsStage(session, viewer)
    qtbot.addWidget(stage)
    return stage


def test_play_toggles_and_advances(qtbot, tmp_path) -> None:
    stage = _stage(qtbot, tmp_path)
    stage.time_combo.addItems(["0", "0.1", "0.2", "0.3"])
    assert not stage._anim_timer.isActive()

    stage._toggle_play()
    assert stage._anim_timer.isActive()
    assert stage.play_btn.text() == "⏸"

    start = stage.time_combo.currentIndex()
    stage._advance_frame()
    assert stage.time_combo.currentIndex() == start + 1

    stage._toggle_play()  # pause
    assert not stage._anim_timer.isActive()
    assert stage.play_btn.text() == "▶"


def test_advance_loops_or_stops(qtbot, tmp_path) -> None:
    stage = _stage(qtbot, tmp_path)
    stage.time_combo.addItems(["0", "0.1", "0.2"])
    stage.time_combo.setCurrentIndex(2)

    stage.loop_chk.setChecked(True)
    stage._anim_timer.start()
    stage._advance_frame()
    assert stage.time_combo.currentIndex() == 0  # wrapped

    stage.time_combo.setCurrentIndex(2)
    stage.loop_chk.setChecked(False)
    stage._advance_frame()
    assert stage.time_combo.currentIndex() == 2  # held at last
    assert not stage._anim_timer.isActive()  # stopped at the end


def test_play_noop_with_one_frame(qtbot, tmp_path) -> None:
    stage = _stage(qtbot, tmp_path)
    stage.time_combo.addItems(["0"])
    stage._toggle_play()
    assert not stage._anim_timer.isActive()


def test_speed_sets_interval(qtbot, tmp_path) -> None:
    stage = _stage(qtbot, tmp_path)
    stage.speed_slider.setValue(10)
    assert stage._anim_timer.interval() == 100  # 10 fps -> 100 ms


def test_hiding_stops_animation(qtbot, tmp_path) -> None:
    from PyQt6.QtGui import QHideEvent

    stage = _stage(qtbot, tmp_path)
    stage.time_combo.addItems(["0", "0.1"])
    stage._anim_timer.start()
    stage.hideEvent(QHideEvent())  # navigating away from the stage
    assert not stage._anim_timer.isActive()


def test_range_controls_enable_with_manual(qtbot, tmp_path) -> None:
    stage = _stage(qtbot, tmp_path)
    assert stage.auto_range_chk.isChecked()
    assert not stage.range_min.isEnabled()  # disabled while auto

    stage.auto_range_chk.setChecked(False)
    assert stage.range_min.isEnabled()
    assert stage.range_max.isEnabled()
    assert stage.reset_range_btn.isEnabled()


@requires_openfoam
def test_field_range_and_reset(qtbot, tmp_path) -> None:
    session = projects.create_project("rng", tmp_path, "Lid-driven cavity")
    session.model.run.max_iterations = 150
    from flowdesk.foam import writer

    writer.write_case(session.model.validated(), session.case_dir)
    r = subprocess.run(openfoam_argv("blockMesh && simpleFoam", session.case_dir, _ENV),
                       capture_output=True, text=True, timeout=600)
    assert r.returncode == 0, r.stdout[-1500:]

    loaded = results_io.load(session.case_dir)
    rng = results_io.field_range(loaded, "U magnitude")
    assert rng is not None
    lo, hi = rng
    assert hi > lo and hi > 0.1  # moving lid drives nonzero speed

    viewer = ViewerWidget()
    qtbot.addWidget(viewer)
    stage = ResultsStage(session, viewer)
    qtbot.addWidget(stage)
    stage.refresh()
    stage.field_combo.setCurrentText("U magnitude")
    stage._reset_range()  # fills min/max from the data
    assert stage.range_min.value() == pytest.approx(lo, abs=1e-6)
    assert stage.range_max.value() == pytest.approx(hi, abs=1e-6)
