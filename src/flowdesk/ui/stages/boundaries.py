"""Boundary Conditions stage (PRD §4.5): patch list mirroring the viewer,
solver-aware physical-BC characters, inlet/outlet sub-types, bulk assignment,
and a SimFlow-style per-field override editor grouped into Flow/Turbulence/Phase.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from flowdesk.app import bc_catalog
from flowdesk.app.projects import ProjectSession
from flowdesk.model.boundaries import (
    Atmosphere,
    Empty,
    FieldOverride,
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
    CollapsibleGroup,
    UnitLineEdit,
    Vec3Input,
    make_button,
    split_viewer_panel,
)
from flowdesk.ui.theme import PANEL_PADDING, PATCH_COLORS

_KIND_TO_LABEL = {
    "velocityInlet": "Velocity inlet",
    "pressureOutlet": "Pressure outlet",
    "wall": "Wall (no-slip)",
    "slip": "Slip wall",
    "symmetry": "Symmetry",
    "outflow": "Outflow (zero-gradient)",
    "empty": "Empty (2D)",
    "atmosphere": "Atmosphere (open)",
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
    selection_changed = pyqtSignal(set)  # patch names selected in the list

    def __init__(self, session: ProjectSession, parent: QWidget | None = None):
        super().__init__(parent)
        self.session = session

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.viewer_slot = QVBoxLayout()

        from PyQt6.QtWidgets import QScrollArea

        panel = QWidget()
        form = QVBoxLayout(panel)
        form.setContentsMargins(PANEL_PADDING, PANEL_PADDING, PANEL_PADDING, PANEL_PADDING)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(panel)
        split_viewer_panel(layout, self.viewer_slot, scroll)

        title = QLabel("Boundary Conditions")
        title.setProperty("role", "title")
        form.addWidget(title)

        self._stale_slot = QVBoxLayout()
        form.addLayout(self._stale_slot)

        form.addWidget(QLabel("Patches (Ctrl-click for multi-select)"))
        self.patch_list = QListWidget()
        self.patch_list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.patch_list.itemSelectionChanged.connect(self._on_selection)
        self.patch_list.setMaximumHeight(150)
        form.addWidget(self.patch_list)

        # Character (solver-aware) — repopulated in refresh()
        form.addWidget(QLabel("Boundary condition"))
        self.type_combo = QComboBox()
        self.type_combo.currentIndexChanged.connect(self._on_type_changed)
        form.addWidget(self.type_combo)

        self._params_stack = QStackedWidget()
        self._param_index: dict[str, int] = {}
        self._build_param_forms()
        form.addWidget(self._params_stack)

        self.assign_btn = make_button("Assign to selected patches", "primary")
        self.assign_btn.clicked.connect(self.assign)
        form.addWidget(self.assign_btn)

        # Per-field override editor (SimFlow per-field layer)
        self._override_group = CollapsibleGroup("Per-field overrides")
        self._override_box = self._override_group.body_layout
        form.addWidget(self._override_group)

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
        # Velocity inlet: spec sub-type combo + per-spec inputs
        inlet = QWidget()
        grid = QGridLayout(inlet)
        grid.setContentsMargins(0, 4, 0, 4)
        grid.addWidget(QLabel("Inlet type"), 0, 0)
        self.inlet_spec = QComboBox()
        for key, label in bc_catalog.INLET_SPECS:
            self.inlet_spec.addItem(label, key)
        self.inlet_spec.currentIndexChanged.connect(self._on_inlet_spec)
        grid.addWidget(self.inlet_spec, 0, 1)

        self.inlet_speed = UnitLineEdit(unit="m/s", value=1.0)
        self.inlet_vector = Vec3Input(unit="m/s", value=(1.0, 0.0, 0.0))
        self.inlet_volumetric = UnitLineEdit(unit="m3/s", value=0.1, minimum=0.0)
        self.inlet_mass = UnitLineEdit(value=1.0, minimum=0.0)
        self.inlet_mass.setToolTip("kg/s (OpenFOAM keyword: massFlowRate)")
        self.inlet_pressure_edit = UnitLineEdit(unit="m2/s", value=0.0)
        self.inlet_pressure_edit.setToolTip(
            "Inlet pressure (kinematic m²/s²; Pa for interFoam)")
        self._inlet_rows = {
            "normal": (QLabel("Speed"), self.inlet_speed),
            "vector": (QLabel("Velocity vector"), self.inlet_vector),
            "volumetricFlowRate": (QLabel("Volumetric flow rate"), self.inlet_volumetric),
            "massFlowRate": (QLabel("Mass flow rate"), self.inlet_mass),
            "pressure": (QLabel("Inlet pressure"), self.inlet_pressure_edit),
        }
        for r, (lab, widget) in enumerate(self._inlet_rows.values(), start=1):
            grid.addWidget(lab, r, 0)
            grid.addWidget(widget, r, 1)
        caption = QLabel("Turbulence at inlet: intensity & length from Physics")
        caption.setProperty("role", "caption")
        grid.addWidget(caption, 6, 0, 1, 2)
        self._register_param("velocityInlet", inlet)
        self._on_inlet_spec()

        # Pressure outlet: outlet-type combo + per-type input
        outlet = QWidget()
        grid = QGridLayout(outlet)
        grid.setContentsMargins(0, 4, 0, 4)
        grid.addWidget(QLabel("Outlet type"), 0, 0)
        self.outlet_type_combo = QComboBox()
        for key, label in bc_catalog.OUTLET_TYPES:
            self.outlet_type_combo.addItem(label, key)
        self.outlet_type_combo.currentIndexChanged.connect(self._on_outlet_type)
        grid.addWidget(self.outlet_type_combo, 0, 1)
        self.outlet_pressure = UnitLineEdit(unit="m2/s", value=0.0)
        self.outlet_pressure.setToolTip(
            "Kinematic gauge pressure p/ρ in m²/s² (OpenFOAM: fixedValue on p)")
        self.outlet_total = UnitLineEdit(unit="m2/s", value=0.0)
        self.outlet_total.setToolTip("Total (stagnation) pressure p0")
        self._outlet_rows = {
            "fixedValue": (QLabel("Gauge pressure"), self.outlet_pressure),
            "totalPressure": (QLabel("Total pressure"), self.outlet_total),
        }
        for r, (lab, widget) in enumerate(self._outlet_rows.values(), start=1):
            grid.addWidget(lab, r, 0)
            grid.addWidget(widget, r, 1)
        self._register_param("pressureOutlet", outlet)
        self._on_outlet_type()

        wall = QWidget()
        grid = QGridLayout(wall)
        grid.setContentsMargins(0, 4, 0, 4)
        self.wall_moving = QCheckBox("Moving wall")
        grid.addWidget(self.wall_moving, 0, 0)
        self.wall_velocity = Vec3Input(unit="m/s", value=(0.0, 0.0, 0.0))
        grid.addWidget(self.wall_velocity, 1, 0)
        self._register_param("wall", wall)

        self._register_param("slip", QWidget())
        self._register_param("symmetry", QWidget())

        outflow = QWidget()
        v = QVBoxLayout(outflow)
        v.setContentsMargins(0, 4, 0, 4)
        v.addWidget(Banner("Prefer 'Pressure outlet' — Outflow (zeroGradient "
                           "everywhere) is not backflow-safe.", "warn"))
        self._register_param("outflow", outflow)

        self._register_param("empty", QWidget())

        atmosphere = QWidget()
        v = QVBoxLayout(atmosphere)
        v.setContentsMargins(0, 4, 0, 4)
        v.addWidget(Banner(
            "Open boundary to still air (free-surface cases): total-pressure "
            "reference, air re-enters on backflow.", "info"))
        self._register_param("atmosphere", atmosphere)

    def _register_param(self, kind: str, widget: QWidget) -> None:
        self._param_index[kind] = self._params_stack.addWidget(widget)

    def _on_inlet_spec(self) -> None:
        spec = self.inlet_spec.currentData()
        for key, (lab, widget) in self._inlet_rows.items():
            lab.setVisible(key == spec)
            widget.setVisible(key == spec)

    def _on_outlet_type(self) -> None:
        otype = self.outlet_type_combo.currentData()
        for key, (lab, widget) in self._outlet_rows.items():
            lab.setVisible(key == otype)
            widget.setVisible(key == otype)

    def _on_type_changed(self) -> None:
        kind = self.type_combo.currentData()
        if kind in self._param_index:
            self._params_stack.setCurrentIndex(self._param_index[kind])

    # ------------------------------------------------------------------ data

    def _selected_patches(self) -> list[str]:
        return [item.data(Qt.ItemDataRole.UserRole)
                for item in self.patch_list.selectedItems()]

    def _bc_from_form(self) -> PhysicalBC:
        kind = self.type_combo.currentData()
        if kind == "velocityInlet":
            spec = self.inlet_spec.currentData()
            return VelocityInlet(
                mode=spec,
                speed=self.inlet_speed.value(),
                vector=self.inlet_vector.value(),
                volumetric_flow_rate=self.inlet_volumetric.value(),
                mass_flow_rate=self.inlet_mass.value(),
                inlet_pressure=self.inlet_pressure_edit.value())
        if kind == "pressureOutlet":
            return PressureOutlet(
                outlet_type=self.outlet_type_combo.currentData(),
                gauge_pressure=self.outlet_pressure.value(),
                total_pressure=self.outlet_total.value())
        if kind == "wall":
            if self.wall_moving.isChecked():
                return Wall(moving_velocity=self.wall_velocity.value())
            return Wall()
        if kind == "slip":
            return SlipWall()
        if kind == "symmetry":
            return Symmetry()
        if kind == "outflow":
            return Outflow()
        if kind == "atmosphere":
            return Atmosphere()
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
        from flowdesk.foam import polymesh, writer

        report = writer.write_case(validated, self.session.case_dir)
        for rel in report.skipped_detached:
            self._add_banner(f"{rel} is detached — not rewritten.", "warn")
        changes = polymesh.sync_boundary_types(self.session.model,
                                               self.session.case_dir)
        for patch, old, new in changes:
            self._add_banner(
                f"ℹ patch '{patch}' type updated in polyMesh/boundary: "
                f"{old} → {new} (required by the assigned BC).", "info")
        self.session.staleness.clear(Stage.BOUNDARIES)
        self.refresh()
        self.model_changed.emit(Stage.BOUNDARIES)
        return True

    # ------------------------------------------------------------------ display

    def refresh(self) -> None:
        self._refresh_stale()
        self._refresh_type_combo()

        selected = set(self._selected_patches())
        self.patch_list.clear()
        for patch in self.session.model.expected_patches():
            bc = self.session.model.boundaries.get(patch)
            label = _KIND_TO_LABEL.get(bc.kind, "?") if bc else "⚠ unassigned"
            n_over = len(bc.overrides) if bc else 0
            if n_over:
                label += f"  (+{n_over} override{'s' if n_over > 1 else ''})"
            item = QListWidgetItem(f"{patch}   —   {label}")
            item.setData(Qt.ItemDataRole.UserRole, patch)
            if bc is None:
                item.setForeground(Qt.GlobalColor.yellow)
            self.patch_list.addItem(item)
            if patch in selected:
                item.setSelected(True)
        self._refresh_overrides()

    def _refresh_type_combo(self) -> None:
        """Solver-aware character list (SimFlow: depends on the solver)."""
        current = self.type_combo.currentData()
        self.type_combo.blockSignals(True)
        self.type_combo.clear()
        for kind, label in bc_catalog.available_kinds(self.session.model):
            self.type_combo.addItem(label, kind)
        idx = self.type_combo.findData(current)
        if idx >= 0:
            self.type_combo.setCurrentIndex(idx)
        self.type_combo.blockSignals(False)
        self._on_type_changed()

    def _refresh_stale(self) -> None:
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

    def _on_selection(self) -> None:
        patches = self._selected_patches()
        self.selection_changed.emit(set(patches))  # viewer highlight (§4.5)
        self._refresh_overrides()
        if len(patches) != 1:
            return
        bc = self.session.model.boundaries.get(patches[0])
        if bc is None:
            return
        self.type_combo.setCurrentIndex(self.type_combo.findData(bc.kind))
        if isinstance(bc, VelocityInlet):
            self.inlet_spec.setCurrentIndex(self.inlet_spec.findData(bc.mode))
            self.inlet_speed.set_value(bc.speed)
            self.inlet_vector.set_values(bc.vector)
            self.inlet_volumetric.set_value(bc.volumetric_flow_rate)
            self.inlet_mass.set_value(bc.mass_flow_rate)
            self.inlet_pressure_edit.set_value(bc.inlet_pressure)
        elif isinstance(bc, PressureOutlet):
            self.outlet_type_combo.setCurrentIndex(
                self.outlet_type_combo.findData(bc.outlet_type))
            self.outlet_pressure.set_value(bc.gauge_pressure)
            self.outlet_total.set_value(bc.total_pressure)
        elif isinstance(bc, Wall):
            self.wall_moving.setChecked(bc.moving_velocity is not None)
            if bc.moving_velocity is not None:
                self.wall_velocity.set_values(bc.moving_velocity)

    # ------------------------------------------------------------------ overrides

    def _refresh_overrides(self) -> None:
        """Show the per-field override editor for a single selected patch."""
        while self._override_box.count():
            item = self._override_box.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                self._clear_layout(item.layout())

        patches = self._selected_patches()
        if len(patches) != 1 or patches[0] not in self.session.model.boundaries:
            note = QLabel("Select one assigned patch to override individual fields.")
            note.setProperty("role", "caption")
            note.setWordWrap(True)
            self._override_box.addWidget(note)
            return
        patch = patches[0]
        bc = self.session.model.boundaries[patch]
        for group_name, fields in bc_catalog.field_groups(self.session.model):
            header = QLabel(group_name.upper())
            header.setProperty("role", "section")
            self._override_box.addWidget(header)
            for field in fields:
                self._override_box.addWidget(self._override_row(patch, bc, field))

    def _override_row(self, patch: str, bc: PhysicalBC, field: str) -> QWidget:
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(QLabel(field), stretch=1)

        type_combo = QComboBox()
        type_combo.addItem("Managed", None)
        for key, label in bc_catalog.override_types_for_field(field):
            type_combo.addItem(label, key)
        existing = bc.overrides.get(field)
        if existing is not None:
            idx = type_combo.findData(existing.patch_type)
            type_combo.setCurrentIndex(idx if idx >= 0 else 0)
        h.addWidget(type_combo, stretch=1)

        value_edit = QLineEdit(existing.value if existing else "")
        value_edit.setPlaceholderText("uniform …")
        value_edit.setEnabled(existing is not None)
        h.addWidget(value_edit, stretch=1)

        def commit() -> None:
            ptype = type_combo.currentData()
            if ptype is None:
                bc.overrides.pop(field, None)
                value_edit.setEnabled(False)
                value_edit.clear()
            else:
                value_edit.setEnabled(True)
                bc.overrides[field] = FieldOverride(
                    patch_type=ptype, value=value_edit.text().strip())
            self.session.save_model()
            self.model_changed.emit(Stage.BOUNDARIES)
            self._refresh_patch_labels()

        type_combo.currentIndexChanged.connect(lambda _i: commit())
        value_edit.editingFinished.connect(commit)
        return row

    def _refresh_patch_labels(self) -> None:
        """Update the '(+N overrides)' suffix without rebuilding selection."""
        for i in range(self.patch_list.count()):
            item = self.patch_list.item(i)
            patch = item.data(Qt.ItemDataRole.UserRole)
            bc = self.session.model.boundaries.get(patch)
            label = _KIND_TO_LABEL.get(bc.kind, "?") if bc else "⚠ unassigned"
            n_over = len(bc.overrides) if bc else 0
            if n_over:
                label += f"  (+{n_over} override{'s' if n_over > 1 else ''})"
            item.setText(f"{patch}   —   {label}")

    def _clear_layout(self, layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                self._clear_layout(item.layout())

    # ------------------------------------------------------------------ banners

    def _add_banner(self, message: str, severity: str) -> None:
        self._banner_slot.addWidget(Banner(message, severity))

    def _clear_banners(self) -> None:
        while self._banner_slot.count():
            item = self._banner_slot.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
