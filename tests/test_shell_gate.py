"""M2 gate: blockMesh-only cavity meshed and quality-reported entirely in-GUI.

Drives the real MeshStage widget (Generate Mesh button path) and asserts the
quality panel and model are populated. Needs OpenFOAM (WSL or native).
"""

from __future__ import annotations

import os
import sys

import pytest

from flowdesk.app import projects
from flowdesk.model.findings import Stage
from flowdesk.platform.commands import probe_environment
from flowdesk.ui.drawer import RunDrawer
from flowdesk.ui.stages.mesh import MeshStage

_ENV = probe_environment()

requires_openfoam = pytest.mark.skipif(
    not _ENV.available, reason=f"OpenFOAM not reachable: {_ENV.detail}")


@requires_openfoam
def test_cavity_meshed_and_quality_reported_in_gui(qtbot, tmp_path) -> None:
    session = projects.create_project("cavity-gate", tmp_path, "Lid-driven cavity")
    stage = MeshStage(session, _ENV)
    qtbot.addWidget(stage)
    drawer = RunDrawer()
    qtbot.addWidget(drawer)

    stage.generate()
    assert stage.runner is not None
    drawer.attach(stage.runner)

    with qtbot.waitSignal(stage.mesh_completed, timeout=180_000) as blocker:
        pass
    assert blocker.args == [True], "mesh pipeline failed - see drawer log"

    # Model holds the result
    result = session.model.mesh.result
    assert result is not None
    assert result.cell_count == 400
    assert result.quality.mesh_ok
    assert result.quality.max_non_ortho is not None
    assert {p.name for p in result.patches} == {"movingWall", "fixedWalls", "frontAndBack"}

    # Quality panel rendered traffic lights (§4.3.3)
    labels = [w.text() for w in stage.findChildren(type(stage.cell_estimate))]
    joined = " ".join(labels)
    assert "400 cells" in joined
    assert "Mesh OK" in joined

    # Drawer log captured the pipeline
    log_text = drawer.log.toPlainText()
    assert "blockMesh" in log_text
    assert "checkMesh" in log_text or "Mesh OK" in log_text

    # Stage statuses: mesh complete, persisted to sidecar
    statuses = session.stage_statuses()
    assert statuses[Stage.MESH] in ("complete", "warnings")
    reloaded = projects.open_project(session.case_dir)
    assert reloaded.model.mesh.result is not None
    assert reloaded.model.mesh.result.cell_count == 400


@requires_openfoam
def test_mesh_failure_is_surfaced_honestly(qtbot, tmp_path) -> None:
    """A broken blockMeshDict must produce a Failed state + banner, never silence."""
    session = projects.create_project("cavity-broken", tmp_path, "Lid-driven cavity")
    # Sabotage the case on disk after writing: detach-proof direct break
    bmd = session.case_dir / "system" / "blockMeshDict"
    bmd.write_text(bmd.read_text().replace("hex (0 1 2 3 4 5 6 7)",
                                           "hex (0 1 2 3 4 5 6 99)"),
                   encoding="utf-8", newline="\n")
    # Mark user-owned so Apply doesn't regenerate it back to a working state

    session.model.ownership.files["system/blockMeshDict"].detached = True

    stage = MeshStage(session, _ENV)
    qtbot.addWidget(stage)
    stage.generate()
    assert stage.runner is not None
    with qtbot.waitSignal(stage.mesh_completed, timeout=180_000) as blocker:
        pass
    assert blocker.args == [False]


@pytest.mark.skipif(os.environ.get("QT_QPA_PLATFORM") == "offscreen"
                    and sys.platform != "win32",
                    reason="VTK viewer needs a display; skipped on headless CI")
def test_shell_constructs_with_viewer(qtbot, tmp_path) -> None:
    from flowdesk.ui.shell import ProjectShell

    session = projects.create_project("cavity-shell", tmp_path, "Lid-driven cavity")
    shell = ProjectShell(session, _ENV)
    qtbot.addWidget(shell)
    shell.show_stage(Stage.MESH)
    assert shell._stack.currentWidget() is shell.mesh_stage
