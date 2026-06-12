"""Right-side panels must fit their width - no horizontal scrollbar.

Regression for the 'content too wide, needs scroll' report: each stage's
scrollable side panel must have a minimum content width <= the panel width.
"""

from __future__ import annotations

import pytest
from PyQt6.QtWidgets import QScrollArea

from flowdesk.app import projects
from flowdesk.platform.commands import Environment
from flowdesk.ui.theme import RIGHT_PANEL_WIDTH

_ENV = Environment(False, True, None, "test")


def _stage(name, session):
    from flowdesk.ui.stages.boundaries import BoundariesStage
    from flowdesk.ui.stages.mesh import MeshStage
    from flowdesk.ui.stages.physics import PhysicsStage
    from flowdesk.ui.stages.results import ResultsStage
    from flowdesk.ui.viewer import ViewerWidget

    if name == "mesh":
        return MeshStage(session, _ENV)
    if name == "physics":
        return PhysicsStage(session)
    if name == "boundaries":
        return BoundariesStage(session)
    return ResultsStage(session, ViewerWidget())


@pytest.mark.parametrize("stage_name", ["mesh", "physics", "boundaries", "results"])
def test_side_panel_fits_width(qtbot, tmp_path, stage_name) -> None:
    # the dam-break case exercises the widest content (free surface vec3s,
    # snappy refinement table, many patches)
    session = projects.create_project("fit", tmp_path, "Dam break (3D breach)")
    stage = _stage(stage_name, session)
    qtbot.addWidget(stage)
    for scroll in stage.findChildren(QScrollArea):
        inner = scroll.widget()
        if inner is None:
            continue
        min_w = inner.minimumSizeHint().width()
        assert min_w <= RIGHT_PANEL_WIDTH, (
            f"{stage_name} panel needs {min_w}px > {RIGHT_PANEL_WIDTH}px "
            "(would show a horizontal scrollbar)")


def test_flow_layout_wraps(qtbot) -> None:
    from PyQt6.QtWidgets import QLabel, QWidget

    from flowdesk.ui.components import FlowLayout

    host = QWidget()
    qtbot.addWidget(host)
    layout = FlowLayout(host, spacing=6)
    for i in range(8):
        layout.addWidget(QLabel(f"chip {i}"))
    # at a narrow width the laid-out height exceeds a single row -> it wrapped
    one_row = max(layout.itemAt(i).sizeHint().height() for i in range(layout.count()))
    assert layout.heightForWidth(120) > one_row
