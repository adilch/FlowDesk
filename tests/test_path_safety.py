"""OpenFOAM-hostile case paths (user-reported: a project under 'New folder (2)'
died in surfaceFeatureExtract with fileName::stripInvalid, fatal at debug>=2)."""

from __future__ import annotations

from pathlib import PureWindowsPath

import pytest

from flowdesk.app.projects import openfoam_path_problem


def test_parentheses_in_parent_folder_flagged() -> None:
    # the user's exact path shape
    problem = openfoam_path_problem(
        PureWindowsPath(r"C:\Users\adilj\flowdesk\damadil\New folder (2)\Untitled-1"))
    assert problem is not None
    assert "space" in problem and "'('" in problem and "')'" in problem


def test_clean_path_is_fine() -> None:
    assert openfoam_path_problem(
        PureWindowsPath(r"C:\Users\adilj\flowdesk\dam-break_01")) is None


def test_wsl_unc_path_anchor_not_flagged() -> None:
    # the \\wsl$\Ubuntu-24.04\ anchor must not be flagged for its backslashes
    assert openfoam_path_problem(
        PureWindowsPath(r"\\wsl$\Ubuntu-24.04\home\adilj\flowdesk\weir")) is None


def test_wsl_unc_with_bad_component_flagged() -> None:
    problem = openfoam_path_problem(
        PureWindowsPath(r"\\wsl$\Ubuntu-24.04\home\adilj\my cases\dam"))
    assert problem is not None and "space" in problem


@pytest.mark.parametrize("bad", ["a(b", "a)b", "a b", "a'b", 'a"b', "a&b", "a;b",
                                 "a|b", "a{b", "a[b"])
def test_individual_hostile_chars(bad) -> None:
    assert openfoam_path_problem(PureWindowsPath(rf"C:\of\{bad}\case")) is not None


def test_separators_never_flagged() -> None:
    # deep clean path: only components are checked, never the many separators
    assert openfoam_path_problem(
        PureWindowsPath(r"C:\a\b\c\d\e\f\g\case_final")) is None


def test_new_project_dialog_blocks_bad_location(qtbot, tmp_path) -> None:
    from flowdesk.app.settings import AppSettings
    from flowdesk.platform.commands import Environment
    from flowdesk.ui.home import NewProjectDialog

    env = Environment(False, True, None, "test")
    dialog = NewProjectDialog(env, AppSettings(), None)
    qtbot.addWidget(dialog)
    dialog.name_edit.setText("Untitled-1")
    dialog.location_edit.setText(str(tmp_path / "New folder (2)"))
    accepted = []
    dialog.accepted.connect(lambda: accepted.append(True))
    dialog._validate_and_accept()
    assert not accepted, "dialog accepted an OpenFOAM-hostile path"


def test_mesh_generate_blocks_bad_path(qtbot, tmp_path) -> None:
    """An already-opened project at a bad path is caught before the pipeline."""
    from flowdesk.app import projects
    from flowdesk.platform.commands import Environment
    from flowdesk.ui.stages.mesh import MeshStage

    env = Environment(True, True, None, "test (pretend available)")
    bad_dir = tmp_path / "New folder (2)"
    session = projects.create_project("Untitled-1", bad_dir, "Lid-driven cavity")
    stage = MeshStage(session, env)
    qtbot.addWidget(stage)
    stage.generate()
    assert stage.runner is None, "mesh pipeline started despite hostile path"
    banners = stage.findChildren(type(stage._banner_slot.itemAt(0).widget())) \
        if stage._banner_slot.count() else []
    assert banners, "no error banner shown for hostile path"
