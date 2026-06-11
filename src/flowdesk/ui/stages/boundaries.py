"""Boundary Conditions stage (PRD §4.5): patch list mirroring the viewer,
physical-BC forms, bulk assignment, staleness re-apply."""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from flowdesk.app.projects import ProjectSession
from flowdesk.model.boundaries import (
    Empty,
    Outflow,
    PhysicalBC,
    PressureOutlet,
    SlipWall,
    Symmetry,
    VelocityInlet,
    Wall,
)
from flowdesk.model.case import InvalidCaseError
from flowdesk.model.findings import Stage
from flowdesk.ui.components import (
    Banner,
    SegmentedControl,
    UnitLineEdit,
    Vec3Input,
    make_button,
)
from flowdesk.ui.theme import PANEL_PADDING, PATCH_COLORS, RIGHT_PANEL_WIDTH

BC_TYPES = ["Velocity inlet", "Pressure outlet", "Wall (no-slip)", "Slip wall",
            "Symmetry", "Outflow (zero-gradient)", "Empty (2D)"]

_KIND_TO_LABEL = {
    "velocityInlet": "Velocity inlet",
    "pressureOutlet": "Pressure outlet",
    "wall": "Wall (no-slip)",
    "slip": "Slip wall",
    "symmetry": "Symmetry",
    "outflow": "Outflow (zero-gradient)",
    "empty": "Empty (2D)",
}

_KIND_TO_COLOR_KEY = {
    "velocityInlet": "inlet",
    "pressureOutlet": "outlet",
    "wall": "wall",
    "slip": "slip",
    "symmetry": "symmetry",
    "outflow": "outlet",
    "empty": "symmetry",
}


def patch_color(bc: PhysicalBC | None) -> str | None:
    """Okabe-Ito categorical color for a patch's assignment (§6.1); None = unassigned."""
    if bc is None:
        return None
    return PATCH_COLORS[_KIND_TO_COLOR_KEY[bc.kind]]


class BoundariesStage(QWidget):
    model_changed = pyqtSignal(Stage)

    def __init__(self, session: ProjectSession, parent: QWidget | None = None):
        super().__init__(parent)
        self.session = session

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.viewer_slot = QVBoxLayout()
        layout.addLayout(self.viewer_slot, stretch=1)

        panel = QWidget()
        panel.setFixedWidth(RIGHT_PANEL_WIDTH + 60)
        form = QVBoxLayout(panel)
        form.setContentsMargins(PANEL_PADDING, PANEL_PADDING, PANEL_PADDING, PANEL_PADDING)
        layout.addWidget(panel)

        title = QLabel("Boundary Conditions")
        title.setProperty("role", "title")
        form.addWidget(title)

        self._stale_slot = QVBoxLayout()
        form.addLayout(self._stale_slot)

        form.addWidget(QLabel("Patches (Ctrl-click for multi-select)"))
        self.patch_list = QListWidget()
        self.patch_list.setSelectionMode(
            QListWidget.SelectionMode.ExtendedSelection)
        self.patch_list.itemSelectionChanged.connect(self._on_selection)
        self.patch_list.setMaximumHeight(170)
        form.addWidget(self.patch_list)

        form.addWidget(QLabel("Boundary condition"))
        self.type_combo = QComboBox()
        self.type_combo.addItems(BC_TYPES)
        self.type_combo.currentIndexChanged.connect(
            lambda i: self._params_stack.setCurrentIndex(i))
        form.addWidget(self.type_combo)

        self._params_stack = QStackedWidget()
        self._build_param_forms()
        form.addWidget(self._params_stack)

        self.assign_btn = make_button("Assign to selected patches", "primary")
        self.assign_btn.clicked.connect(self.assign)
        form.addWidget(self.assign_btn)

        self.enclosed_chk = QCheckBox(
            "Fully enclosed domain (no inlet/outlet; sets pressure reference)")
        self.enclosed_chk.setChecked(session.model.enclosed_domain)
        self.enclosed_chk.toggled.connect(self._on_enclosed)
        form.addWidget(self.enclosed_chk)

        self.apply_btn = make_button("Apply (write field files)")
        self.apply_btn.clicked.connect(self.apply)
        form.addWidget(self.apply_btn)

        self._banner_slot = QVBoxLayout()
        form.addLayout(self._banner_slot)
        form.addStretch()
        self.refresh()

    # ------------------------------------------------------------------ param forms

    def _build_param_forms(self) -> None:
        # Velocity inlet (§4.5): normal speed | vector, turbulence spec
        inlet = QWidget()
        grid = QGridLayout(inlet)
        grid.setContentsMargins(0, 4, 0, 4)
        self.inlet_mode = SegmentedControl(["Normal speed", "Vector"])
        grid.addWidget(self.inlet_mode, 0, 0, 1, 2)
        grid.addWidget(QLabel("Speed"), 1, 0)
        self.inlet_speed = UnitLineEdit(unit="m/s", value=1.0)
        grid.addWidget(self.inlet_speed, 1, 1)
        grid.addWidget(QLabel("Vector"), 2, 0)
        self.inlet_vector = Vec3Input(unit="m/s", value=(1.0, 0.0, 0.0))
        grid.addWidget(self.inlet_vector, 2, 1)
        caption = QLabel("Turbulence at inlet: intensity & length from Physics")
        caption.setProperty("role", "caption")
        grid.addWidget(caption, 3, 0, 1, 2)
        self._params_stack.addWidget(inlet)

        outlet = QWidget()
        grid = QGridLayout(outlet)
        grid.setContentsMargins(0, 4, 0, 4)
        grid.addWidget(QLabel("Gauge pressure"), 0, 0)
        self.outlet_pressure = UnitLineEdit(unit="m2/s", value=0.0)
        self.outlet_pressure.setToolTip(
            "Kinematic pressure p/ρ in m²/s² — divide a Pa value by the fluid "
            "density (OpenFOAM keyword: fixedValue on p)")
        grid.addWidget(self.outlet_pressure, 0, 1)
        self._params_stack.addWidget(outlet)

        wall = QWidget()
        grid = QGridLayout(wall)
        grid.setContentsMargins(0, 4, 0, 4)
        self.wall_moving = QCheckBox("Moving wall")
        grid.addWidget(self.wall_moving, 0, 0)
        self.wall_velocity = Vec3Input(unit="m/s", value=(0.0, 0.0, 0.0))
        grid.addWidget(self.wall_velocity, 1, 0)
        self._params_stack.addWidget(wall)

        self._params_stack.addWidget(QWidget())  # Slip wall: no parameters
        self._params_stack.addWidget(QWidget())  # Symmetry: no parameters

        outflow = QWidget()  # Outflow gets the §4.5 warning
        v = QVBoxLayout(outflow)
        v.setContentsMargins(0, 4, 0, 4)
        v.addWidget(Banner("Prefer 'Pressure outlet' — Outflow (zeroGradient "
                           "everywhere) is not backflow-safe.", "warn"))
        self._params_stack.addWidget(outflow)

        self._params_stack.addWidget(QWidget())  # Empty (2D): no parameters

    # ------------------------------------------------------------------ data

    def _selected_patches(self) -> list[str]:
        return [item.data(Qt.ItemDataRole.UserRole)
                for item in self.patch_list.selectedItems()]

    def _bc_from_form(self) -> PhysicalBC:
        label = self.type_combo.currentText()
        if label == "Velocity inlet":
            if self.inlet_mode.current() == 0:
                return VelocityInlet(mode="normal", speed=self.inlet_speed.value())
            return VelocityInlet(mode="vector", vector=self.inlet_vector.value())
        if label == "Pressure outlet":
            return PressureOutlet(gauge_pressure=self.outlet_pressure.value())
        if label == "Wall (no-slip)":
            if self.wall_moving.isChecked():
                return Wall(moving_velocity=self.wall_velocity.value())
            return Wall()
        if label == "Slip wall":
            return SlipWall()
        if label == "Symmetry":
            return Symmetry()
        if label == "Outflow (zero-gradient)":
            return Outflow()
        return Empty()

    # ------------------------------------------------------------------ actions

    def assign(self) -> None:
        self._clear_banners()
        patches = self._selected_patches()
        if not patches:
            self._add_banner("Select one or more patches first.", "info")
            return
        for patch in patches:
            self.session.model.boundaries[patch] = self._bc_from_form()
        # prune assignments to patches that no longer exist
        valid = set(self.session.model.expected_patches())
        for name in list(self.session.model.boundaries):
            if name not in valid:
                del self.session.model.boundaries[name]
        self.session.save_model()
        self.refresh()
        self.model_changed.emit(Stage.BOUNDARIES)

    def _on_enclosed(self, checked: bool) -> None:
        self.session.model.enclosed_domain = checked
        self.session.save_model()
        self.model_changed.emit(Stage.BOUNDARIES)

    def apply(self) -> bool:
        """Write the case including field files - requires full validity."""
        self._clear_banners()
        try:
            validated = self.session.model.validated()
        except InvalidCaseError as exc:
            for finding in exc.findings[:5]:
                self._add_banner(finding.message, "error")
            return False
        from flowdesk.foam import writer

        report = writer.write_case(validated, self.session.case_dir)
        for rel in report.skipped_detached:
            self._add_banner(f"{rel} is detached — not rewritten.", "warn")
        self.session.staleness.clear(Stage.BOUNDARIES)
        self.refresh()
        self.model_changed.emit(Stage.BOUNDARIES)
        return True

    # ------------------------------------------------------------------ display

    def refresh(self) -> None:
        # staleness banner with one-click re-apply (§4.5)
        while self._stale_slot.count():
            item = self._stale_slot.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        if self.session.staleness.is_stale(Stage.BOUNDARIES):
            row = QWidget()
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 0, 0, 0)
            h.addWidget(Banner(
                f"⟳ {self.session.staleness.reason(Stage.BOUNDARIES)}", "warn"),
                stretch=1)
            reapply = make_button("Re-apply")
            reapply.clicked.connect(self.apply)
            h.addWidget(reapply)
            self._stale_slot.addWidget(row)

        selected = set(self._selected_patches())
        self.patch_list.clear()
        for patch in self.session.model.expected_patches():
            bc = self.session.model.boundaries.get(patch)
            label = _KIND_TO_LABEL.get(bc.kind, "?") if bc else "⚠ unassigned"
            item = QListWidgetItem(f"{patch}   —   {label}")
            item.setData(Qt.ItemDataRole.UserRole, patch)
            if bc is None:
                item.setForeground(Qt.GlobalColor.yellow)
            self.patch_list.addItem(item)
            if patch in selected:
                item.setSelected(True)

    def _on_selection(self) -> None:
        patches = self._selected_patches()
        if len(patches) != 1:
            return
        bc = self.session.model.boundaries.get(patches[0])
        if bc is None:
            return
        # reflect the existing assignment in the form
        self.type_combo.setCurrentText(_KIND_TO_LABEL[bc.kind])
        if isinstance(bc, VelocityInlet):
            self.inlet_speed.set_value(bc.speed)
            self.inlet_vector.set_values(bc.vector)
        elif isinstance(bc, PressureOutlet):
            self.outlet_pressure.set_value(bc.gauge_pressure)
        elif isinstance(bc, Wall):
            self.wall_moving.setChecked(bc.moving_velocity is not None)
            if bc.moving_velocity is not None:
                self.wall_velocity.set_values(bc.moving_velocity)

    # ------------------------------------------------------------------ banners

    def _add_banner(self, message: str, severity: str) -> None:
        self._banner_slot.addWidget(Banner(message, severity))

    def _clear_banners(self) -> None:
        while self._banner_slot.count():
            item = self._banner_slot.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
