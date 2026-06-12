"""Explicit Save project + the generated mesh reappearing on return to Mesh."""

from __future__ import annotations

import subprocess

import pytest

from flowdesk.app import projects
from flowdesk.model.findings import Stage
from flowdesk.platform.commands import Environment, openfoam_argv, probe_environment

_ENV = probe_environment()
_TEST_ENV = Environment(False, True, None, "test")

requires_openfoam = pytest.mark.skipif(
    not _ENV.available, reason=f"OpenFOAM not reachable: {_ENV.detail}")


def _shell(session):
    from flowdesk.ui.shell import ProjectShell

    return ProjectShell(session, _TEST_ENV)


# ------------------------------------------------------------------ Save project


def test_save_project_writes_case_and_sidecar(qtbot, tmp_path) -> None:
    session = projects.create_project("save-valid", tmp_path, "Lid-driven cavity")
    # blow away generated files to prove Save rewrites them
    (session.case_dir / "system" / "controlDict").unlink()
    shell = _shell(session)
    qtbot.addWidget(shell)

    shell.save_project()
    assert (session.case_dir / "flowdesk.json").exists()
    assert (session.case_dir / "system" / "controlDict").exists()  # rewritten
    assert "saved" in shell.status_bar.text().lower()
    assert "case files written" in shell.status_bar.text()


def test_save_project_invalid_saves_sidecar_only(qtbot, tmp_path) -> None:
    session = projects.create_project("save-invalid", tmp_path, "Empty case")
    shell = _shell(session)
    qtbot.addWidget(shell)
    shell.save_project()
    # empty case is invalid: sidecar persists, no system/ written
    assert (session.case_dir / "flowdesk.json").exists()
    assert "saved" in shell.status_bar.text().lower()
    assert "sidecar only" in shell.status_bar.text()


def test_ctrl_s_bound_to_save(qtbot, tmp_path) -> None:
    session = projects.create_project("ctrls", tmp_path, "Lid-driven cavity")
    shell = _shell(session)
    qtbot.addWidget(shell)
    # the alias used to wire Ctrl+S resolves to the explicit save
    assert shell._force_save == shell.save_project


# ------------------------------------------------------------------ mesh on return


def _actor_names(shell) -> set[str]:
    return set(shell.viewer.plotter.renderer.actors.keys())


def test_unmeshed_mesh_stage_shows_inputs(qtbot, tmp_path) -> None:
    session = projects.create_project("nomesh", tmp_path, "Lid-driven cavity")
    shell = _shell(session)
    qtbot.addWidget(shell)
    shell.show_stage(Stage.MESH)
    assert "_domain_box" in _actor_names(shell)
    assert "_mesh_preview" not in _actor_names(shell)


@requires_openfoam
def test_generated_mesh_reappears_on_return_to_mesh(qtbot, tmp_path) -> None:
    session = projects.create_project("meshview", tmp_path, "Lid-driven cavity")

    from flowdesk.foam import writer

    writer.write_case(session.model.validated(), session.case_dir)
    result = subprocess.run(openfoam_argv("blockMesh", session.case_dir, _ENV),
                            capture_output=True, text=True, timeout=300)
    assert result.returncode == 0, result.stdout[-1500:]
    from flowdesk.exec.parsers import read_boundary_patches
    from flowdesk.model.mesh import MeshResult, QualityReport

    session.model.mesh.result = MeshResult(
        cell_count=400, patches=read_boundary_patches(session.case_dir),
        quality=QualityReport(mesh_ok=True))

    shell = _shell(session)
    qtbot.addWidget(shell)
    # navigate away, then back to Mesh: the generated mesh must be shown
    shell.show_stage(Stage.PHYSICS)
    shell.show_stage(Stage.MESH)
    assert "_mesh_preview" in _actor_names(shell), \
        "the generated mesh did not reappear on return to the Mesh stage"
