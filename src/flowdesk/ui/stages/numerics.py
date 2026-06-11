"""Numerics stage (PRD §4.6): preset segmented control, advanced disclosure
showing resolved values, first-order start assist."""

from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from flowdesk.app.projects import ProjectSession
from flowdesk.model.findings import Stage
from flowdesk.model.numerics import Preset, make_preset
from flowdesk.ui.components import (
    CollapsibleGroup,
    SegmentedControl,
    UnitLineEdit,
    make_button,
)
from flowdesk.ui.theme import GROUP_GAP, PANEL_PADDING

PRESET_ORDER = [Preset.ROBUST, Preset.BALANCED, Preset.ACCURATE, Preset.CUSTOM]


class NumericsStage(QWidget):
    model_changed = pyqtSignal(Stage)

    def __init__(self, session: ProjectSession, parent: QWidget | None = None):
        super().__init__(parent)
        self.session = session
        n = session.model.numerics

        outer = QHBoxLayout(self)
        panel = QWidget()
        panel.setMaximumWidth(620)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(PANEL_PADDING * 2, PANEL_PADDING, PANEL_PADDING,
                                  PANEL_PADDING)
        layout.setSpacing(GROUP_GAP // 2)
        outer.addWidget(panel)
        outer.addStretch()

        title = QLabel("Numerics")
        title.setProperty("role", "title")
        layout.addWidget(title)

        self.preset_seg = SegmentedControl(
            ["Robust", "Balanced", "Accurate", "Custom"],
            current=PRESET_ORDER.index(n.preset))
        self.preset_seg.selectionChanged.connect(self._on_preset)
        layout.addWidget(self.preset_seg)

        self.preset_caption = QLabel("")
        self.preset_caption.setProperty("role", "caption")
        layout.addWidget(self.preset_caption)

        # First-order start assist (§4.6)
        first_order_row = QHBoxLayout()
        self.first_order_chk = QCheckBox("First-order start")
        self.first_order_chk.setToolTip(
            "Run leg 1 with upwind divergence schemes, then switch to the "
            "preset's target schemes and continue (visible in the run log)")
        self.first_order_chk.setChecked(n.first_order_start.enabled)
        self.switch_iter = QSpinBox()
        self.switch_iter.setRange(10, 100_000)
        self.switch_iter.setValue(n.first_order_start.switch_iteration)
        first_order_row.addWidget(self.first_order_chk)
        first_order_row.addWidget(QLabel("switch at iteration"))
        first_order_row.addWidget(self.switch_iter)
        first_order_row.addStretch()
        layout.addLayout(first_order_row)

        # Advanced: the resolved values (touching any flips to Custom)
        self.advanced = CollapsibleGroup("Advanced — resolved scheme/solver values")
        grid = QGridLayout()
        self._fields: dict[str, UnitLineEdit] = {}

        def add_row(row: int, label: str, key: str, value: float,
                    minimum: float | None = None) -> None:
            grid.addWidget(QLabel(label), row, 0)
            edit = UnitLineEdit(value=value, minimum=minimum)
            edit.valueChanged.connect(lambda _v: self._flip_to_custom())
            self._fields[key] = edit
            grid.addWidget(edit, row, 1)

        add_row(0, "p solver tolerance", "p_tol", n.p_solver.tolerance, 0)
        add_row(1, "p solver relTol", "p_rel", n.p_solver.rel_tol, 0)
        add_row(2, "U/turb tolerance", "u_tol", n.u_solver.tolerance, 0)
        add_row(3, "U/turb relTol", "u_rel", n.u_solver.rel_tol, 0)
        add_row(4, "Relaxation p", "relax_p", n.relaxation.p, 0.01)
        add_row(5, "Relaxation U", "relax_u", n.relaxation.u, 0.01)
        add_row(6, "Relaxation turbulence", "relax_turb", n.relaxation.turb, 0.01)
        add_row(7, "Residual target p", "res_p", n.residual_targets.p, 0)
        add_row(8, "Residual target U", "res_u", n.residual_targets.u, 0)
        add_row(9, "Residual target turb", "res_turb", n.residual_targets.turb, 0)
        self.scheme_label = QLabel("")
        self.scheme_label.setProperty("role", "caption")
        self.scheme_label.setWordWrap(True)
        holder = QWidget()
        holder.setLayout(grid)
        self.advanced.body_layout.addWidget(self.scheme_label)
        self.advanced.body_layout.addWidget(holder)
        layout.addWidget(self.advanced)

        self.apply_btn = make_button("Apply", "primary")
        self.apply_btn.clicked.connect(self.apply)
        layout.addWidget(self.apply_btn)
        layout.addStretch()
        self._refresh_captions()

    # ------------------------------------------------------------------ handlers

    def _on_preset(self, index: int) -> None:
        preset = PRESET_ORDER[index]
        if preset is not Preset.CUSTOM:
            resolved = make_preset(preset)
            self.session.model.numerics = resolved
            self._load_fields(resolved)
        else:
            self.session.model.numerics.preset = Preset.CUSTOM
        self._refresh_captions()

    def _load_fields(self, n) -> None:
        values = {
            "p_tol": n.p_solver.tolerance, "p_rel": n.p_solver.rel_tol,
            "u_tol": n.u_solver.tolerance, "u_rel": n.u_solver.rel_tol,
            "relax_p": n.relaxation.p, "relax_u": n.relaxation.u,
            "relax_turb": n.relaxation.turb,
            "res_p": n.residual_targets.p, "res_u": n.residual_targets.u,
            "res_turb": n.residual_targets.turb,
        }
        for key, value in values.items():
            self._fields[key].set_value(value)

    def _flip_to_custom(self) -> None:
        if self.session.model.numerics.preset is not Preset.CUSTOM:
            base = self.session.model.numerics.preset.value
            self.session.model.numerics.preset = Preset.CUSTOM
            self.preset_seg._group.button(3).setChecked(True)
            self.preset_caption.setText(f"Custom (based on {base})")

    def _refresh_captions(self) -> None:
        n = self.session.model.numerics
        self.preset_caption.setText({
            Preset.ROBUST: "Conservative: upwind, strong limiting, safe relaxation.",
            Preset.BALANCED: "linearUpwind momentum, SIMPLEC, lighter limiting.",
            Preset.ACCURATE: "Second-order turbulence, tighter targets.",
            Preset.CUSTOM: "Custom values.",
        }[n.preset])
        self.scheme_label.setText(
            f"div(phi,U): {n.div_u}   •   div(phi,k/ω): {n.div_turb}   •   "
            f"grad: {n.grad_scheme}   •   laplacian: {n.laplacian_scheme}")

    # ------------------------------------------------------------------ apply

    def apply(self) -> None:
        n = self.session.model.numerics
        n.p_solver.tolerance = self._fields["p_tol"].value()
        n.p_solver.rel_tol = self._fields["p_rel"].value()
        n.u_solver.tolerance = self._fields["u_tol"].value()
        n.u_solver.rel_tol = self._fields["u_rel"].value()
        n.relaxation.p = self._fields["relax_p"].value()
        n.relaxation.u = self._fields["relax_u"].value()
        n.relaxation.turb = self._fields["relax_turb"].value()
        n.residual_targets.p = self._fields["res_p"].value()
        n.residual_targets.u = self._fields["res_u"].value()
        n.residual_targets.turb = self._fields["res_turb"].value()
        n.first_order_start.enabled = self.first_order_chk.isChecked()
        n.first_order_start.switch_iteration = self.switch_iter.value()
        self.session.save_model()
        self.session.staleness.clear(Stage.NUMERICS)
        self.model_changed.emit(Stage.NUMERICS)
