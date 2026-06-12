"""Mesh visualization: per-patch actors + click-to-highlight (distinct colours)."""

from __future__ import annotations

import subprocess

import pytest

from flowdesk.app import projects
from flowdesk.platform.commands import Environment, openfoam_argv, probe_environment

_ENV = probe_environment()
_TEST_ENV = Environment(False, True, None, "test")

requires_openfoam = pytest.mark.skipif(
    not _ENV.available, reason=f"OpenFOAM not reachable: {_ENV.detail}")


def test_patch_selection_emits_names(qtbot, tmp_path) -> None:
    from flowdesk.exec.parsers import read_boundary_patches
    from flowdesk.model.mesh import MeshResult, PatchInfo, QualityReport
    from flowdesk.ui.stages.mesh import MeshStage

    session = projects.create_project("p", tmp_path, "Lid-driven cavity")
    session.model.mesh.result = MeshResult(
        cell_count=400, quality=QualityReport(mesh_ok=True),
        patches=[PatchInfo(name="movingWall", n_faces=20),
                 PatchInfo(name="fixedWalls", n_faces=60)])
    stage = MeshStage(session, _TEST_ENV)
    qtbot.addWidget(stage)
    stage._show_quality()
    assert stage.patch_view_list.count() == 2

    received: list[list] = []
    stage.patches_selected.connect(received.append)
    stage.patch_view_list.item(0).setSelected(True)
    assert received and received[-1] == ["movingWall"]
    assert read_boundary_patches  # imported for parity with the gate path


def test_viewer_color_selected_is_safe_without_patches(qtbot) -> None:
    from flowdesk.ui.viewer import ViewerWidget

    viewer = ViewerWidget()
    qtbot.addWidget(viewer)
    viewer.color_selected_patches(["x"])  # no patches loaded -> no-op
    viewer.color_selected_patches([])


def test_hex_rgb() -> None:
    from flowdesk.ui.viewer import ViewerWidget

    assert ViewerWidget._hex_rgb("#FFFFFF") == (1.0, 1.0, 1.0)
    r, g, b = ViewerWidget._hex_rgb("#0072B2")
    assert 0.0 <= r < 0.1 and 0.4 < g < 0.5 and 0.6 < b < 0.8


@requires_openfoam
def test_mesh_patches_load_and_highlight(qtbot, tmp_path) -> None:
    from flowdesk.ui.viewer import ViewerWidget

    session = projects.create_project("mv", tmp_path, "Lid-driven cavity")
    from flowdesk.foam import writer

    writer.write_case(session.model.validated(), session.case_dir)
    result = subprocess.run(openfoam_argv("blockMesh", session.case_dir, _ENV),
                            capture_output=True, text=True, timeout=300)
    assert result.returncode == 0, result.stdout[-1500:]

    viewer = ViewerWidget()
    qtbot.addWidget(viewer)
    names = viewer.show_mesh_patches(session.case_dir)
    assert set(names) == {"movingWall", "fixedWalls", "frontAndBack"}
    assert len(viewer._mesh_patch_actors) == 3

    # highlight two patches -> each gets a distinct palette colour, others fade
    viewer.color_selected_patches(["movingWall", "fixedWalls"])
    c0 = viewer._mesh_patch_actors["movingWall"].GetProperty().GetColor()
    c1 = viewer._mesh_patch_actors["fixedWalls"].GetProperty().GetColor()
    faded = viewer._mesh_patch_actors["frontAndBack"].GetProperty().GetOpacity()
    assert c0 != c1, "multiple selected patches must get different colours"
    assert faded < 0.5, "unselected patches must fade"

    # clearing restores full opacity
    viewer.color_selected_patches([])
    assert viewer._mesh_patch_actors["frontAndBack"].GetProperty().GetOpacity() == 1.0
