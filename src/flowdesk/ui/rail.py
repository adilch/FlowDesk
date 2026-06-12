"""Left workflow rail (PRD §5.1/§5.2): navigation, not a wizard - any stage
clickable anytime; chips communicate readiness. Collapsible to an icon strip."""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from flowdesk.model.findings import Stage
from flowdesk.ui.theme import (
    RAIL_COLLAPSED_WIDTH,
    RAIL_WIDTH,
    STAGE_STATUSES,
    repolish,
)

# (number, full label) per stage. Collapsed mode shows the number + status glyph.
STAGE_INFO = {
    Stage.GEOMETRY: ("1", "Geometry"),
    Stage.MESH: ("2", "Mesh"),
    Stage.PHYSICS: ("3", "Physics"),
    Stage.BOUNDARIES: ("4", "Boundary Conditions"),
    Stage.NUMERICS: ("5", "Numerics"),
    Stage.RUN: ("6", "Run"),
    Stage.RESULTS: ("7", "Results"),
}


class RailItem(QPushButton):
    def __init__(self, stage: Stage, parent: QWidget | None = None):
        super().__init__(parent)
        self.stage = stage
        self.setCheckable(True)
        self.setProperty("rail", "true")
        self._status = "empty"
        self._collapsed = False
        self._refresh()

    def set_status(self, status: str) -> None:
        self._status = status
        self._refresh()

    def set_collapsed(self, collapsed: bool) -> None:
        self._collapsed = collapsed
        self._refresh()

    def _refresh(self) -> None:
        info = STAGE_STATUSES[self._status]
        number, label = STAGE_INFO[self.stage]
        if self._collapsed:
            self.setText(f"{number} {info.glyph}")
            self.setToolTip(f"{label} — {info.label}")
        else:
            self.setText(f"{info.glyph}  {number}  {label}")
            self.setToolTip(info.label)
        self.setProperty("status", self._status)
        repolish(self)


class WorkflowRail(QFrame):
    stage_selected = pyqtSignal(Stage)
    collapse_toggled = pyqtSignal(bool)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setProperty("panel", "true")
        self._collapsed = False
        self.setFixedWidth(RAIL_WIDTH)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 12, 8, 12)
        layout.setSpacing(2)

        header = QHBoxLayout()
        self._title = QLabel("WORKFLOW")
        self._title.setProperty("role", "section")
        self._toggle = QToolButton()
        self._toggle.setProperty("railToggle", "true")
        self._toggle.setText("«")
        self._toggle.setToolTip("Collapse the workflow rail")
        self._toggle.clicked.connect(self.toggle_collapsed)
        header.addWidget(self._title, stretch=1)
        header.addWidget(self._toggle)
        layout.addLayout(header)

        self._items: dict[Stage, RailItem] = {}
        for stage in Stage:
            item = RailItem(stage)
            item.clicked.connect(lambda _=False, s=stage: self._select(s))
            self._items[stage] = item
            layout.addWidget(item)
        layout.addStretch()

    # ------------------------------------------------------------------ collapse

    def toggle_collapsed(self) -> None:
        self.set_collapsed(not self._collapsed)

    def set_collapsed(self, collapsed: bool) -> None:
        self._collapsed = collapsed
        self.setFixedWidth(RAIL_COLLAPSED_WIDTH if collapsed else RAIL_WIDTH)
        self._title.setVisible(not collapsed)
        self._toggle.setText("»" if collapsed else "«")
        self._toggle.setToolTip(
            "Expand the workflow rail" if collapsed else "Collapse the workflow rail")
        # keep the toggle reachable when collapsed
        self.layout().itemAt(0).layout().setAlignment(
            self._toggle, Qt.AlignmentFlag.AlignHCenter if collapsed
            else Qt.AlignmentFlag.AlignRight)
        for item in self._items.values():
            item.set_collapsed(collapsed)
        self.collapse_toggled.emit(collapsed)

    @property
    def is_collapsed(self) -> bool:
        return self._collapsed

    # ------------------------------------------------------------------ selection

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
