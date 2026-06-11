"""Write controls (controlDict UI) + BC-selection viewer highlight."""

from __future__ import annotations

import pytest

from flowdesk.app import projects
from flowdesk.foam import generators
from flowdesk.platform.commands import Environment
from flowdesk.ui.stages.run import RunStage

_ENV = Environment(False, True, None, "test")


@pytest.fixture
def aero(tmp_path):
    return projects.create_project("aero", tmp_path, "External aero")


@pytest.fixture
def vortex(tmp_path):
    return projects.create_project("vx", tmp_path, "Vortex shedding (transient)")


# ------------------------------------------------------------- model/generator


def test_steady_purge_zero_keeps_all(aero) -> None:
    aero.model.run.purge_write = 0
    aero.model.run.write_interval_steady = 50
    text = generators.control_dict(aero.model)
    assert "purgeWrite      0;" in text
    assert "writeInterval   50;" in text


def test_transient_purge_and_format(vortex) -> None:
    vortex.model.run.purge_write_transient = 5
    vortex.model.run.write_format = "ascii"
    vortex.model.run.write_precision = 10
    text = generators.control_dict(vortex.model)
    assert "purgeWrite      5;" in text
    assert "writeFormat     ascii;" in text
    assert "writePrecision  10;" in text


def test_transient_default_keeps_all_frames(vortex) -> None:
    text = generators.control_dict(vortex.model)
    assert "purgeWrite      0;" in text  # animation frames survive by default


# ------------------------------------------------------------------ Run stage UI


def test_run_stage_collects_steady_write_controls(qtbot, aero) -> None:
    stage = RunStage(aero, _ENV)
    qtbot.addWidget(stage)
    assert "iterations" in stage.write_every_label.text()
    stage.write_interval.setValue(25)
    stage.purge.setValue(0)
    stage.write_format.setCurrentText("ascii")
    stage.write_precision.setValue(9)
    stage.collect()
    run = aero.model.run
    assert run.write_interval_steady == 25
    assert run.purge_write == 0
    assert run.write_format == "ascii"
    assert run.write_precision == 9


def test_run_stage_collects_transient_write_controls(qtbot, vortex) -> None:
    stage = RunStage(vortex, _ENV)
    qtbot.addWidget(stage)
    assert "seconds" in stage.write_every_label.text()
    stage.write_interval.setValue(0.5)
    stage.purge.setValue(3)
    stage.collect()
    assert vortex.model.physics.time.output_interval == 0.5
    assert vortex.model.run.purge_write_transient == 3


def test_disk_estimate_appears_with_mesh(qtbot, aero) -> None:
    from flowdesk.model.mesh import MeshResult, QualityReport

    aero.model.mesh.result = MeshResult(cell_count=1_000_000,
                                        quality=QualityReport(mesh_ok=True))
    stage = RunStage(aero, _ENV)
    qtbot.addWidget(stage)
    assert "GB on disk" in stage.disk_estimate.text()


# -------------------------------------------------------------- patch highlight


def test_bc_selection_emits_and_viewer_tolerates(qtbot, aero) -> None:
    from PyQt6.QtCore import Qt

    from flowdesk.ui.stages.boundaries import BoundariesStage
    from flowdesk.ui.viewer import ViewerWidget

    bcs = BoundariesStage(aero)
    qtbot.addWidget(bcs)
    received: list[set] = []
    bcs.selection_changed.connect(received.append)
    for i in range(bcs.patch_list.count()):
        item = bcs.patch_list.item(i)
        if item.data(Qt.ItemDataRole.UserRole) in ("inlet", "outlet"):
            item.setSelected(True)
    assert received and received[-1] == {"inlet", "outlet"}

    viewer = ViewerWidget()
    qtbot.addWidget(viewer)
    viewer.highlight_patches({"inlet"})  # no patches loaded: must be a no-op
    viewer.highlight_patches(set())
