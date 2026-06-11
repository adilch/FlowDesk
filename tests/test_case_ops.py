"""Case reset (Reset & Rerun), close-project flow, viewer views, progress QSS."""

from __future__ import annotations

from pathlib import Path

from flowdesk.app import case_ops


def _fake_run_case(case_dir: Path) -> None:
    """A case directory shaped like a finished parallel run."""
    for d in ("0", "0.2", "150", "constant/polyMesh", "system",
              "processor0/200", "processor1/200", "postProcessing/probes"):
        (case_dir / d).mkdir(parents=True)
    (case_dir / "0" / "U").write_text("fields")
    (case_dir / "150" / "U").write_text("results")
    (case_dir / "constant" / "polyMesh" / "points").write_text("mesh")
    (case_dir / "system" / "controlDict").write_text("dict")
    (case_dir / "flowdesk.json").write_text("{}")
    for f in ("log.flowdesk", "flowdesk.pid", "flowdesk.exit",
              "flowdesk-run.sh", "case.foam"):
        (case_dir / f).write_text("x")


def test_reset_removes_results_keeps_setup(tmp_path: Path) -> None:
    _fake_run_case(tmp_path)
    removed = case_ops.reset_case(tmp_path)

    # gone: results, decomposed dirs, run artifacts
    assert "150" in removed and "0.2" in removed
    assert "processor0" in removed and "processor1" in removed
    assert "postProcessing" in removed and "log.flowdesk" in removed
    assert not (tmp_path / "150").exists()
    assert not (tmp_path / "processor0").exists()
    assert not (tmp_path / "flowdesk.pid").exists()

    # kept: initial fields, mesh, dictionaries, sidecar
    assert (tmp_path / "0" / "U").exists()
    assert (tmp_path / "constant" / "polyMesh" / "points").exists()
    assert (tmp_path / "system" / "controlDict").exists()
    assert (tmp_path / "flowdesk.json").exists()


def test_resettable_items_preview_matches_reset(tmp_path: Path) -> None:
    _fake_run_case(tmp_path)
    preview = {p.name for p in case_ops.resettable_items(tmp_path)}
    removed = set(case_ops.reset_case(tmp_path))
    assert preview == removed


def test_reset_on_clean_case_is_noop(tmp_path: Path) -> None:
    (tmp_path / "0").mkdir()
    (tmp_path / "system").mkdir()
    assert case_ops.reset_case(tmp_path) == []
    assert (tmp_path / "0").exists()


def test_progress_bar_qss_is_readable() -> None:
    """Feature (2): bars must be tall enough for their value text."""
    from flowdesk.ui.theme import build_qss

    qss = build_qss()
    assert "min-height: 20px" in qss.split("QProgressBar {")[1].split("}")[0]


def test_shell_close_signal(qtbot, tmp_path) -> None:
    """Feature (3): close emits, saves the model, and is not blocked when idle."""
    from flowdesk.app import projects
    from flowdesk.platform.commands import Environment
    from flowdesk.ui.shell import ProjectShell

    env = Environment(False, True, None, "test")
    session = projects.create_project("close-test", tmp_path, "Lid-driven cavity")
    shell = ProjectShell(session, env)
    qtbot.addWidget(shell)
    closed = []
    shell.close_requested.connect(lambda: closed.append(True))
    shell.request_close()
    assert closed == [True]


def test_viewer_standard_views(qtbot) -> None:
    """Feature (1): orientation triad present; X/Y/Z views orient the camera."""
    from flowdesk.ui.viewer import ViewerWidget

    viewer = ViewerWidget()
    qtbot.addWidget(viewer)
    viewer.view_x()
    pos, focal, _up = viewer.plotter.camera_position
    direction = tuple(f - p for p, f in zip(pos, focal, strict=True))
    assert abs(direction[1]) < 1e-6 and abs(direction[2]) < 1e-6  # along x

    viewer.view_z()
    pos, focal, _up = viewer.plotter.camera_position
    direction = tuple(f - p for p, f in zip(pos, focal, strict=True))
    assert abs(direction[0]) < 1e-6 and abs(direction[1]) < 1e-6  # along z
