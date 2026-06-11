"""Left workflow rail (PRD §5.1/§5.2): navigation, not a wizard - any stage
clickable anytime; chips communicate readiness."""

from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QFrame, QLabel, QPushButton, QVBoxLayout, QWidget

from flowdesk.model.findings import Stage
from flowdesk.ui.theme import RAIL_WIDTH, STAGE_STATUSES, repolish

STAGE_LABELS = {
    Stage.GEOMETRY: "1  Geometry",
    Stage.MESH: "2  Mesh",
    Stage.PHYSICS: "3  Physics",
    Stage.BOUNDARIES: "4  Boundary Conditions",
    Stage.NUMERICS: "5  Numerics",
    Stage.RUN: "6  Run",
    Stage.RESULTS: "7  Results",
}


class RailItem(QPushButton):
    def __init__(self, stage: Stage, parent: QWidget | None = None):
        super().__init__(parent)
        self.stage = stage
        self.setCheckable(True)
        self.setProperty("variant", "ghost")
        self._status = "empty"
        self._refresh()

    def set_status(self, status: str) -> None:
        self._status = status
        self._refresh()

    def _refresh(self) -> None:
        info = STAGE_STATUSES[self._status]
        self.setText(f"{info.glyph}  {STAGE_LABELS[self.stage]}")
        self.setToolTip(info.label)
        self.setProperty("status", self._status)
        repolish(self)


class WorkflowRail(QFrame):
    stage_selected = pyqtSignal(Stage)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setProperty("panel", "true")
        self.setFixedWidth(RAIL_WIDTH)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 16, 8, 16)
        layout.setSpacing(2)

        title = QLabel("WORKFLOW")
        title.setProperty("role", "section")
        layout.addWidget(title)

        self._items: dict[Stage, RailItem] = {}
        for stage in Stage:
            item = RailItem(stage)
            item.clicked.connect(lambda _=False, s=stage: self._select(s))
            self._items[stage] = item
            layout.addWidget(item)
        layout.addStretch()

    def _select(self, stage: Stage) -> None:
        for s, item in self._items.items():
            item.setChecked(s is stage)
        self.stage_selected.emit(stage)

    def select(self, stage: Stage) -> None:
        self._select(stage)

    def update_statuses(self, statuses: dict[Stage, str],
                        enabled: dict[Stage, bool] | None = None) -> None:
        for stage, status in statuses.items():
            self._items[stage].set_status(status)
        if enabled:
            for stage, on in enabled.items():
                self._items[stage].setEnabled(on)
