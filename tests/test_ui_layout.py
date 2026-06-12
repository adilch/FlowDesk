"""UI/UX layout pass: collapsible rail, stage header breadcrumb, clickable
validation status, unified panel width."""

from __future__ import annotations

from flowdesk.app import projects
from flowdesk.model.findings import Stage
from flowdesk.platform.commands import Environment

_ENV = Environment(False, True, None, "test")


def _shell(session):
    from flowdesk.ui.shell import ProjectShell

    return ProjectShell(session, _ENV)


def test_rail_collapses_to_icon_width(qtbot, tmp_path) -> None:
    from flowdesk.ui.rail import WorkflowRail
    from flowdesk.ui.theme import RAIL_COLLAPSED_WIDTH, RAIL_WIDTH

    rail = WorkflowRail()
    qtbot.addWidget(rail)
    assert rail.width() == RAIL_WIDTH
    rail.toggle_collapsed()
    assert rail.is_collapsed
    assert rail.width() == RAIL_COLLAPSED_WIDTH
    rail.toggle_collapsed()
    assert not rail.is_collapsed
    assert rail.width() == RAIL_WIDTH


def test_rail_item_collapsed_text_is_compact(qtbot, tmp_path) -> None:
    from flowdesk.ui.rail import RailItem

    item = RailItem(Stage.BOUNDARIES)
    qtbot.addWidget(item)
    expanded = item.text()
    assert "Boundary Conditions" in expanded
    item.set_collapsed(True)
    assert "Boundary Conditions" not in item.text()
    assert "4" in item.text()  # the stage number remains
    assert "Boundary Conditions" in item.toolTip()  # full name in tooltip


def test_shell_collapses_save_close_with_rail(qtbot, tmp_path) -> None:
    session = projects.create_project("c", tmp_path, "Lid-driven cavity")
    shell = _shell(session)
    qtbot.addWidget(shell)
    assert "Save project" in shell._save_btn.text()
    shell.rail.set_collapsed(True)
    assert "Save project" not in shell._save_btn.text()
    assert "Close project" not in shell._close_btn.text()


def test_header_breadcrumb_tracks_stage(qtbot, tmp_path) -> None:
    session = projects.create_project("b", tmp_path, "Lid-driven cavity")
    shell = _shell(session)
    qtbot.addWidget(shell)
    assert session.model.meta.name in shell._crumb_project.text()
    shell.show_stage(Stage.RUN)
    assert "Run" in shell._crumb_stage.text()
    shell.show_stage(Stage.RESULTS)
    assert "Results" in shell._crumb_stage.text()


def test_validation_summary_and_jump(qtbot, tmp_path) -> None:
    # Empty case is invalid (no geometry): the status bar must offer a jump
    session = projects.create_project("v", tmp_path, "Empty case")
    shell = _shell(session)
    qtbot.addWidget(shell)
    assert "error" in shell._validation_btn.text().lower()
    shell.show_stage(Stage.RUN)
    shell._jump_to_first_finding()  # jumps to the first finding's stage
    # the first error is the missing geometry -> Geometry stage
    assert "Geometry" in shell._crumb_stage.text()


def test_valid_project_shows_no_issues(qtbot, tmp_path) -> None:
    session = projects.create_project("ok", tmp_path, "Lid-driven cavity")
    shell = _shell(session)
    qtbot.addWidget(shell)
    assert "no issues" in shell._validation_btn.text().lower()


def test_stages_have_resizable_side_panels(qtbot, tmp_path) -> None:
    from PyQt6.QtWidgets import QSplitter

    session = projects.create_project("rs", tmp_path, "Lid-driven cavity")
    shell = _shell(session)
    qtbot.addWidget(shell)
    for stage in (Stage.GEOMETRY, Stage.MESH, Stage.PHYSICS,
                  Stage.BOUNDARIES, Stage.RESULTS):
        shell.show_stage(stage)
        splitters = shell._stages[stage].findChildren(QSplitter)
        assert splitters, f"{stage.value} stage has no resizable splitter"


def test_drawer_is_vertically_resizable(qtbot, tmp_path) -> None:
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QSplitter

    session = projects.create_project("dr", tmp_path, "Lid-driven cavity")
    shell = _shell(session)
    qtbot.addWidget(shell)
    vsplits = [s for s in shell.findChildren(QSplitter)
               if s.orientation() == Qt.Orientation.Vertical]
    assert vsplits, "no vertical splitter for the run drawer"
    # the drawer is a child of the vertical splitter
    assert any(shell.drawer in (s.widget(i) for i in range(s.count()))
               for s in vsplits)


def test_split_helper_clamps_panel(qtbot) -> None:
    from PyQt6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

    from flowdesk.ui.components import split_viewer_panel

    host = QWidget()
    qtbot.addWidget(host)
    root = QHBoxLayout(host)
    viewer_slot = QVBoxLayout()
    panel = QWidget()
    sp = split_viewer_panel(root, viewer_slot, panel)
    assert sp.count() == 2
    assert not sp.childrenCollapsible()
    assert panel.minimumWidth() >= 300


def test_panel_widths_unified() -> None:
    """Every stage's side panel uses the one width constant (no ragged +N)."""
    from pathlib import Path

    import flowdesk.ui.stages.boundaries as bnd
    import flowdesk.ui.stages.mesh as mesh
    import flowdesk.ui.stages.results as res
    from flowdesk.ui.theme import RIGHT_PANEL_WIDTH

    src = (mesh.__file__, bnd.__file__, res.__file__)
    for path in src:
        text = Path(path).read_text(encoding="utf-8")
        assert "RIGHT_PANEL_WIDTH + " not in text, f"{path} still pads the panel width"
    assert RIGHT_PANEL_WIDTH == 420
