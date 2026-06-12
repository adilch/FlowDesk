"""Model-select wizard (the SimScale-style stepped scenario chooser).

Lighter stepped selector: a breadcrumb + a grid of scenario cards that narrows
step by step to a supported solver; unsupported branches are shown disabled with
a 'Phase 2' note. After resolving, a summary shows the solver and its feature
badges (interactive Transient/Turbulence toggles under 'Modify'). Drives the
model via flowdesk.app.scenario; the Physics stage hosts it and keeps the
detailed tuning forms below.
"""

from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from flowdesk.app import scenario
from flowdesk.app.projects import ProjectSession
from flowdesk.ui.components import CollapsibleGroup, make_button
from flowdesk.ui.theme import repolish


class ModelSelector(QWidget):
    """Reads/writes session.model.physics via the scenario tree. Emits `applied`
    after any change so the host can sync forms + persist + mark staleness."""

    applied = pyqtSignal()

    def __init__(self, session: ProjectSession, parent: QWidget | None = None):
        super().__init__(parent)
        self.session = session
        self._path: list[str] = []  # current depth in the chooser
        self._mode = "summary"  # "summary" | "choose" | "manual"

        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(0, 0, 0, 0)
        self._body = QFrame()
        self._body.setProperty("card", "true")
        self._body_layout = QVBoxLayout(self._body)
        self._root.addWidget(self._body)
        self.refresh()

    # ------------------------------------------------------------------ render

    def refresh(self) -> None:
        while self._body_layout.count():
            item = self._body_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                self._clear_layout(item.layout())
        header = QLabel("SIMULATION TYPE")
        header.setProperty("role", "section")
        self._body_layout.addWidget(header)
        if self._mode == "summary":
            self._render_summary()
        elif self._mode == "manual":
            self._render_manual()
        else:
            self._render_chooser()

    def _render_summary(self) -> None:
        model = self.session.model
        path = scenario.current_path(model)
        crumb = " › ".join(scenario.breadcrumb_labels(path))
        crumb_label = QLabel(crumb)
        crumb_label.setWordWrap(True)
        self._body_layout.addWidget(crumb_label)

        solver = QLabel(f"Solver:  {scenario.solver_for(model)}")
        solver.setProperty("role", "title")
        self._body_layout.addWidget(solver)

        # feature badges
        badges = QHBoxLayout()
        badges.setSpacing(6)
        interactive: list[scenario.Feature] = []
        for feat in scenario.feature_badges(model):
            if feat.interactive:
                interactive.append(feat)
            chip = QLabel(("✓ " if feat.on else "○ ") + feat.label)
            chip.setProperty("chip", "true")
            chip.setProperty("status", "complete" if feat.on else "empty")
            badges.addWidget(chip)
        badges.addStretch()
        wrap = QWidget()
        wrap.setLayout(badges)
        self._body_layout.addWidget(wrap)

        # Modify: the genuinely-toggleable features
        if interactive:
            modify = CollapsibleGroup("Modify features")
            for feat in interactive:
                btn = QPushButton(feat.label)
                btn.setCheckable(True)
                btn.setChecked(feat.on)
                btn.setProperty("segment", "true")
                btn.clicked.connect(
                    lambda checked, k=feat.key: self._toggle_feature(k, checked))
                modify.body_layout.addWidget(btn)
            self._body_layout.addWidget(modify)

        change = make_button("Change model…")
        change.clicked.connect(self._enter_chooser)
        self._body_layout.addWidget(change)

    def _render_chooser(self) -> None:
        if self._path:
            crumb = QLabel("Simulation › " + " › ".join(
                scenario.breadcrumb_labels(self._path)))
            crumb.setProperty("role", "caption")
            crumb.setWordWrap(True)
            self._body_layout.addWidget(crumb)

        node = scenario.node_at(self._path)
        grid = QGridLayout()
        for i, child in enumerate(node.children):
            card = self._make_card(child)
            grid.addWidget(card, i // 2, i % 2)
        holder = QWidget()
        holder.setLayout(grid)
        self._body_layout.addWidget(holder)

        nav = QHBoxLayout()
        if self._path:
            back = make_button("← Back", "ghost")
            back.clicked.connect(self._back)
            nav.addWidget(back)
        else:
            manual = make_button("🔍 Choose Solver Manually", "ghost")
            manual.clicked.connect(self._enter_manual)
            nav.addWidget(manual)
        nav.addStretch()
        cancel = make_button("Cancel", "ghost")
        cancel.clicked.connect(self._to_summary)
        nav.addWidget(cancel)
        self._body_layout.addLayout(nav)

    def _make_card(self, child: scenario.ScenarioNode) -> QPushButton:
        text = f"{child.icon}\n{child.label}"
        if not child.supported:
            text += "\n· Phase 2"
        card = QPushButton(text)
        card.setMinimumHeight(64)
        card.setEnabled(child.supported)
        if not child.supported:
            card.setToolTip(child.note)
        else:
            card.clicked.connect(lambda _=False, c=child: self._choose(c))
        return card

    def _render_manual(self) -> None:
        label = QLabel("Pick the OpenFOAM solver directly:")
        self._body_layout.addWidget(label)
        self._manual_combo = QComboBox()
        self._manual_combo.addItems(scenario.MANUAL_SOLVERS)
        self._manual_combo.setCurrentText(scenario.solver_for(self.session.model))
        self._body_layout.addWidget(self._manual_combo)
        nav = QHBoxLayout()
        back = make_button("← Back", "ghost")
        back.clicked.connect(self._enter_chooser)
        apply_btn = make_button("Apply", "primary")
        apply_btn.clicked.connect(self._apply_manual)
        nav.addWidget(back)
        nav.addStretch()
        nav.addWidget(apply_btn)
        self._body_layout.addLayout(nav)

    # ------------------------------------------------------------------ actions

    def _enter_chooser(self) -> None:
        self._path = []
        self._mode = "choose"
        self.refresh()

    def _enter_manual(self) -> None:
        self._mode = "manual"
        self.refresh()

    def _to_summary(self) -> None:
        self._mode = "summary"
        self.refresh()

    def _back(self) -> None:
        if self._path:
            self._path.pop()
        self.refresh()

    def _choose(self, child: scenario.ScenarioNode) -> None:
        if child.is_leaf:
            scenario.apply_resolution(self.session.model, child.resolution)
            self._mode = "summary"
            self.refresh()
            self.applied.emit()
            return
        self._path.append(child.key)
        self.refresh()

    def _apply_manual(self) -> None:
        scenario.apply_manual_solver(self.session.model, self._manual_combo.currentText())
        self._mode = "summary"
        self.refresh()
        self.applied.emit()

    def _toggle_feature(self, key: str, on: bool) -> None:
        scenario.set_feature(self.session.model, key, on)
        self.refresh()
        self.applied.emit()

    # ------------------------------------------------------------------ util

    def _clear_layout(self, layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                self._clear_layout(item.layout())
        repolish(self)
