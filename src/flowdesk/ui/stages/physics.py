"""Physics stage (PRD §4.4): time treatment, turbulence, fluid, reference values
with live derived k/omega/epsilon."""

from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from flowdesk.app.projects import ProjectSession
from flowdesk.model.findings import Stage
from flowdesk.model.physics import (
    FLUID_PRESETS,
    Fluid,
    SteadyTime,
    TransientTime,
    Turbulence,
)
from flowdesk.ui.components import (
    Banner,
    SegmentedControl,
    UnitLineEdit,
    Vec3Input,
    make_button,
    split_viewer_panel,
)
from flowdesk.ui.stages.model_selector import ModelSelector
from flowdesk.ui.theme import GROUP_GAP, PANEL_PADDING

TURBULENCE_LABELS = {
    "Laminar": Turbulence.LAMINAR,
    "k-ε": Turbulence.K_EPSILON,
    "k-ω SST": Turbulence.K_OMEGA_SST,
}
FLUID_LABELS = {"Water (20 °C)": "water", "Air": "air", "Custom…": "custom"}


class PhysicsStage(QWidget):
    model_changed = pyqtSignal(Stage)

    def __init__(self, session: ProjectSession, parent: QWidget | None = None):
        super().__init__(parent)
        self.session = session
        physics = session.model.physics

        # Viewer-dominant layout: the 3D canvas stays visible while editing
        # spatial inputs (the free-surface water column is a spatial object)
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.viewer_slot = QVBoxLayout()

        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(PANEL_PADDING, PANEL_PADDING, PANEL_PADDING,
                                  PANEL_PADDING)
        layout.setSpacing(GROUP_GAP // 2)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(panel)
        split_viewer_panel(outer, self.viewer_slot, scroll)

        title = QLabel("Physics")
        title.setProperty("role", "title")
        layout.addWidget(title)

        # Step-by-step model-select wizard drives solver / free surface / time
        self.model_selector = ModelSelector(session)
        self.model_selector.applied.connect(self._on_model_selected)
        layout.addWidget(self.model_selector)

        # Backing controls for time treatment + free surface. The wizard (and
        # its feature toggles) drive these; kept functional but hidden so the
        # wizard is the single visible control for model selection.
        self._manual_box = QWidget()
        self._manual_box.setVisible(False)
        manual = QGridLayout(self._manual_box)
        manual.setContentsMargins(0, 0, 0, 0)
        manual.addWidget(QLabel("Time treatment"), 0, 0)
        self.time_seg = SegmentedControl(
            ["Steady", "Transient"], current=0 if physics.is_steady else 1)
        self.time_seg.selectionChanged.connect(self._on_time_changed)
        manual.addWidget(self.time_seg, 0, 1)
        self.solver_label = QLabel(f"solver: {physics.solver}")
        self.solver_label.setProperty("role", "caption")
        manual.addWidget(self.solver_label, 0, 2)
        layout.addWidget(self._manual_box)

        # Tuning forms (visible): turbulence model, fluid, viscosity
        grid = QGridLayout()
        grid.addWidget(QLabel("Turbulence model"), 0, 0)
        self.turbulence_combo = QComboBox()
        self.turbulence_combo.addItems(list(TURBULENCE_LABELS))
        current = {v: k for k, v in TURBULENCE_LABELS.items()}[physics.turbulence]
        self.turbulence_combo.setCurrentText(current)
        grid.addWidget(self.turbulence_combo, 0, 1)

        grid.addWidget(QLabel("Fluid"), 1, 0)
        self.fluid_combo = QComboBox()
        self.fluid_combo.addItems(list(FLUID_LABELS))
        preset_name = {"water": "Water (20 °C)", "air": "Air"}.get(
            physics.fluid.name, "Custom…")
        self.fluid_combo.setCurrentText(preset_name)
        self.fluid_combo.currentTextChanged.connect(self._on_fluid_changed)
        grid.addWidget(self.fluid_combo, 1, 1)

        grid.addWidget(QLabel("Kinematic viscosity ν"), 2, 0)
        self.nu_edit = UnitLineEdit(unit="m2/s", value=physics.fluid.nu, minimum=1e-12)
        self.nu_edit.setEnabled(preset_name == "Custom…")
        grid.addWidget(self.nu_edit, 2, 1)
        layout.addLayout(grid)

        # Reference values (§4.4)
        ref_title = QLabel("REFERENCE VALUES (TURBULENCE INIT)")
        ref_title.setProperty("role", "section")
        layout.addWidget(ref_title)
        ref = QGridLayout()
        ref.addWidget(QLabel("Freestream velocity scale"), 0, 0)
        self.u_ref = UnitLineEdit(unit="m/s", value=physics.turb_ref.velocity_scale,
                                  minimum=1e-9)
        ref.addWidget(self.u_ref, 0, 1)
        ref.addWidget(QLabel("Turbulence intensity"), 1, 0)
        self.intensity = UnitLineEdit(unit="%", value=physics.turb_ref.intensity,
                                      minimum=0.01, maximum=100)
        ref.addWidget(self.intensity, 1, 1)
        ref.addWidget(QLabel("Length scale"), 2, 0)
        self.length = UnitLineEdit(unit="m", value=physics.turb_ref.length_scale,
                                   minimum=1e-9)
        ref.addWidget(self.length, 2, 1)
        layout.addLayout(ref)

        self.derived_label = QLabel("")
        self.derived_label.setProperty("role", "caption")
        self.derived_label.setToolTip(
            "k = 1.5 (I·U)²   ω = √k / (Cμ^0.25 · L)   ε = Cμ^0.75 · k^1.5 / L")
        layout.addWidget(self.derived_label)
        for widget in (self.u_ref, self.intensity, self.length):
            widget.valueChanged.connect(lambda _v: self._update_derived())

        # Transient extras (§4.4), visible only when Transient
        self.transient_box = QWidget()
        tr = QGridLayout(self.transient_box)
        tr.setContentsMargins(0, 0, 0, 0)
        t = physics.time if not physics.is_steady else TransientTime()
        tr.addWidget(QLabel("End time"), 0, 0)
        self.end_time = UnitLineEdit(unit="s", value=t.end_time, minimum=1e-9)
        tr.addWidget(self.end_time, 0, 1)
        tr.addWidget(QLabel("Output interval"), 1, 0)
        self.output_interval = UnitLineEdit(unit="s", value=t.output_interval,
                                            minimum=1e-9)
        tr.addWidget(self.output_interval, 1, 1)
        tr.addWidget(QLabel("Max Courant number"), 2, 0)
        self.max_courant = UnitLineEdit(value=t.max_courant, minimum=0.01)
        tr.addWidget(self.max_courant, 2, 1)
        tr.addWidget(QLabel("Initial Δt"), 3, 0)
        self.initial_dt = UnitLineEdit(unit="s", value=t.initial_dt, minimum=1e-12)
        tr.addWidget(self.initial_dt, 3, 1)
        self.transient_box.setVisible(not physics.is_steady)
        layout.addWidget(self.transient_box)

        # Free surface (interFoam): the checkbox is backing state driven by the
        # wizard (hidden); the parameter box below stays visible when active
        fs = physics.free_surface
        self.free_surface_chk = QCheckBox("Free surface (interFoam)")
        self.free_surface_chk.setChecked(fs is not None)
        self.free_surface_chk.toggled.connect(self._on_free_surface_toggled)
        manual.addWidget(self.free_surface_chk, 1, 0, 1, 3)

        fs_title = QLabel("FREE SURFACE (interFoam)")
        fs_title.setProperty("role", "section")
        self._fs_title = fs_title
        fs_title.setVisible(fs is not None)
        layout.addWidget(fs_title)

        self.fs_box = QWidget()
        fsg = QGridLayout(self.fs_box)
        fsg.setContentsMargins(0, 0, 0, 0)
        from flowdesk.model.physics import FreeSurfaceModel

        fs_values = fs if fs is not None else FreeSurfaceModel()
        fsg.addWidget(QLabel("Water column min"), 0, 0)
        self.column_min = Vec3Input(unit="m", value=fs_values.water_column_min)
        fsg.addWidget(self.column_min, 0, 1)
        fsg.addWidget(QLabel("Water column max"), 1, 0)
        self.column_max = Vec3Input(unit="m", value=fs_values.water_column_max)
        fsg.addWidget(self.column_max, 1, 1)
        fsg.addWidget(QLabel("Gravity"), 2, 0)
        self.gravity = Vec3Input(unit="m/s²", value=fs_values.gravity)
        fsg.addWidget(self.gravity, 2, 1)
        fsg.addWidget(QLabel("Surface tension σ"), 3, 0)
        self.sigma = UnitLineEdit(value=fs_values.sigma, minimum=0.0)
        self.sigma.setToolTip("N/m; 0.07 for water-air (OpenFOAM keyword: sigma)")
        fsg.addWidget(self.sigma, 3, 1)
        fsg.addWidget(QLabel("Air: ν / ρ"), 4, 0)
        air_row = QHBoxLayout()
        self.air_nu = UnitLineEdit(unit="m2/s", value=fs_values.light_phase.nu,
                                   minimum=1e-12)
        self.air_rho = UnitLineEdit(value=fs_values.light_phase.rho, minimum=1e-9)
        self.air_rho.setToolTip("kg/m³")
        air_row.addWidget(self.air_nu)
        air_row.addWidget(self.air_rho)
        air_holder = QWidget()
        air_holder.setLayout(air_row)
        fsg.addWidget(air_holder, 4, 1)
        note = QLabel("The Physics fluid above is the heavy phase (water). "
                      "setFields fills the column at run start.")
        note.setProperty("role", "caption")
        note.setWordWrap(True)
        fsg.addWidget(note, 5, 0, 1, 2)
        self.fs_box.setVisible(fs is not None)
        layout.addWidget(self.fs_box)

        # Passive scalar transport (mixing / tracers) - single-phase only
        st = physics.scalar_transport
        self.scalar_chk = QCheckBox("Passive scalar transport (tracer / mixing)")
        self.scalar_chk.setChecked(st is not None)
        self.scalar_chk.toggled.connect(self._on_scalar_toggled)
        layout.addWidget(self.scalar_chk)

        self.scalar_box = QWidget()
        sg = QGridLayout(self.scalar_box)
        sg.setContentsMargins(0, 0, 0, 0)
        from flowdesk.model.physics import ScalarTransportModel

        st_values = st if st is not None else ScalarTransportModel()
        sg.addWidget(QLabel("Field name"), 0, 0)
        self.scalar_field = QLineEdit(st_values.field)
        sg.addWidget(self.scalar_field, 0, 1)
        sg.addWidget(QLabel("Diffusivity D"), 1, 0)
        self.scalar_d = UnitLineEdit(unit="m2/s", value=st_values.diffusivity,
                                     minimum=0.0)
        sg.addWidget(self.scalar_d, 1, 1)
        sg.addWidget(QLabel("Inlet concentration"), 2, 0)
        self.scalar_inlet = UnitLineEdit(value=st_values.inlet_value)
        sg.addWidget(self.scalar_inlet, 2, 1)
        snote = QLabel("A dimensionless tracer injected at velocity inlets and "
                       "carried by the flow; view it in Results.")
        snote.setProperty("role", "caption")
        snote.setWordWrap(True)
        sg.addWidget(snote, 3, 0, 1, 2)
        self.scalar_box.setVisible(st is not None)
        layout.addWidget(self.scalar_box)

        self.apply_btn = make_button("Apply", "primary")
        self.apply_btn.clicked.connect(self.apply)
        layout.addWidget(self.apply_btn)
        self._banner_slot = QVBoxLayout()
        layout.addLayout(self._banner_slot)
        layout.addStretch()
        self._update_derived()

    # ------------------------------------------------------------------ handlers

    def _on_time_changed(self, index: int) -> None:
        self.transient_box.setVisible(index == 1)
        self._update_solver_label(transient=index == 1)

    def _on_model_selected(self) -> None:
        """The wizard wrote the model selection; reflect it in the forms + persist."""
        self._sync_controls_from_model()
        self.session.save_model()
        self.session.staleness.mark_applied(Stage.PHYSICS, "simulation type changed")
        self.model_changed.emit(Stage.PHYSICS)

    def _sync_controls_from_model(self) -> None:
        p = self.session.model.physics
        fs = p.free_surface is not None
        transient = not p.is_steady
        self.time_seg._group.blockSignals(True)
        self.free_surface_chk.blockSignals(True)
        self.time_seg._group.button(1 if transient else 0).setChecked(True)
        self.free_surface_chk.setChecked(fs)
        self.time_seg._group.blockSignals(False)
        self.free_surface_chk.blockSignals(False)
        self.transient_box.setVisible(transient)
        self.fs_box.setVisible(fs)
        self._fs_title.setVisible(fs)
        self._update_solver_label(transient=transient)
        label = {v: k for k, v in TURBULENCE_LABELS.items()}[p.turbulence]
        self.turbulence_combo.setCurrentText(label)

    def _on_scalar_toggled(self, checked: bool) -> None:
        self.scalar_box.setVisible(checked)

    def _on_free_surface_toggled(self, checked: bool) -> None:
        self.fs_box.setVisible(checked)
        self._fs_title.setVisible(checked)
        if checked and self.time_seg.current() == 0:
            # interFoam is transient-only: switch and say so
            self.time_seg._group.button(1).setChecked(True)
            self._on_time_changed(1)
            self._add_banner("Free-surface cases are transient — switched the "
                             "time treatment for you.", "info")
        else:
            self._update_solver_label()

    def _update_solver_label(self, transient: bool | None = None) -> None:
        if transient is None:
            transient = self.time_seg.current() == 1
        if self.free_surface_chk.isChecked():
            solver = "interFoam"
        else:
            solver = "pimpleFoam" if transient else "simpleFoam"
        self.solver_label.setText(f"solver: {solver}")

    def _on_fluid_changed(self, label: str) -> None:
        key = FLUID_LABELS.get(label, "custom")
        if key in FLUID_PRESETS:
            self.nu_edit.set_value(FLUID_PRESETS[key].nu)
            self.nu_edit.setEnabled(False)
        else:
            self.nu_edit.setEnabled(True)

    def _update_derived(self) -> None:
        physics = self.session.model.physics.model_copy(deep=True)
        physics.turb_ref.velocity_scale = self.u_ref.value()
        physics.turb_ref.intensity = self.intensity.value()
        physics.turb_ref.length_scale = self.length.value()
        try:
            self.derived_label.setText(
                f"derived:  k = {physics.k_from():.4g} m²/s²   "
                f"ω = {physics.omega_from():.4g} 1/s   "
                f"ε = {physics.epsilon_from():.4g} m²/s³")
        except ZeroDivisionError:
            self.derived_label.setText("derived: — (length scale must be > 0)")

    # ------------------------------------------------------------------ apply

    def apply(self) -> None:
        self._clear_banners()
        physics = self.session.model.physics
        old_turbulence = physics.turbulence

        if self.time_seg.current() == 0:
            physics.time = SteadyTime()
        else:
            physics.time = TransientTime(
                end_time=self.end_time.value(),
                output_interval=self.output_interval.value(),
                max_courant=self.max_courant.value(),
                initial_dt=self.initial_dt.value(),
            )
        physics.turbulence = TURBULENCE_LABELS[self.turbulence_combo.currentText()]
        fluid_key = FLUID_LABELS[self.fluid_combo.currentText()]
        if fluid_key in FLUID_PRESETS:
            physics.fluid = FLUID_PRESETS[fluid_key].model_copy()
        else:
            physics.fluid = Fluid(name="custom", nu=self.nu_edit.value())

        if self.free_surface_chk.isChecked():
            from flowdesk.model.physics import FreeSurfaceModel

            physics.free_surface = FreeSurfaceModel(
                light_phase=Fluid(name="air", nu=self.air_nu.value(),
                                  rho=self.air_rho.value()),
                sigma=self.sigma.value(),
                gravity=self.gravity.value(),
                water_column_min=self.column_min.value(),
                water_column_max=self.column_max.value(),
            )
        else:
            physics.free_surface = None

        if self.scalar_chk.isChecked():
            from flowdesk.model.physics import ScalarTransportModel

            physics.scalar_transport = ScalarTransportModel(
                field=self.scalar_field.text().strip() or "s",
                diffusivity=self.scalar_d.value(),
                inlet_value=self.scalar_inlet.value())
        else:
            physics.scalar_transport = None

        physics.turb_ref.velocity_scale = self.u_ref.value()
        physics.turb_ref.intensity = self.intensity.value()
        physics.turb_ref.length_scale = self.length.value()

        self.session.save_model()
        summary = "physics changed"
        if physics.turbulence is not old_turbulence:
            # §4.5 consistency rule: wall entries follow the turbulence model
            summary = (f"turbulence model changed: {old_turbulence.value} → "
                       f"{physics.turbulence.value} (wall functions regenerate)")
        self.session.staleness.mark_applied(Stage.PHYSICS, summary)
        self.model_selector.refresh()  # badges/solver reflect tuning changes
        self.model_changed.emit(Stage.PHYSICS)

    def _clear_banners(self) -> None:
        while self._banner_slot.count():
            item = self._banner_slot.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _add_banner(self, message: str, severity: str) -> None:
        self._banner_slot.addWidget(Banner(message, severity))
