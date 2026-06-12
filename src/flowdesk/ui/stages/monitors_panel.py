"""Runtime-monitor configuration (forces, flow rate, field value, probes).

A compact list + Add menu on the Run stage; each type gets a small config
dialog. Writes model.monitors; the Run stage plots their output live.
"""

from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMenu,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from flowdesk.app.projects import ProjectSession
from flowdesk.model.monitors import (
    FieldValueMonitor,
    FlowRateMonitor,
    ForcesMonitor,
    ProbesMonitor,
)
from flowdesk.ui.components import UnitLineEdit, make_button

_FIELDS = ["U", "p", "k", "omega", "epsilon", "nut", "alpha.water"]


class MonitorsPanel(QWidget):
    changed = pyqtSignal()

    def __init__(self, session: ProjectSession, parent: QWidget | None = None):
        super().__init__(parent)
        self.session = session
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        header = QLabel("MONITORS")
        header.setProperty("role", "section")
        layout.addWidget(header)

        self.list = QListWidget()
        self.list.setMaximumHeight(110)
        layout.addWidget(self.list)

        row = QVBoxLayout()
        add_btn = QToolButton()
        add_btn.setText("Add monitor ▾")
        add_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(add_btn)
        menu.addAction("Forces / coefficients (drag, lift)…", self._add_forces)
        menu.addAction("Flow rate through a patch…", self._add_flow_rate)
        menu.addAction("Field min / max / average…", self._add_field_value)
        menu.addAction("Probes at points…", self._add_probes)
        add_btn.setMenu(menu)
        remove_btn = make_button("Remove", "ghost")
        remove_btn.clicked.connect(self._remove)
        row.addWidget(add_btn)
        row.addWidget(remove_btn)
        layout.addLayout(row)
        self.refresh()

    # ------------------------------------------------------------------ helpers

    def _patches(self) -> list[str]:
        return list(self.session.model.boundaries.keys())

    def refresh(self) -> None:
        self.list.clear()
        for mon in self.session.model.monitors:
            self.list.addItem(f"{mon.name}   ({mon.kind})")

    def _commit(self, monitor) -> None:
        # unique name
        existing = {m.name for m in self.session.model.monitors}
        base, n = monitor.name, 2
        while monitor.name in existing:
            monitor.name = f"{base}{n}"
            n += 1
        self.session.model.monitors.append(monitor)
        self.session.save_model()
        self.refresh()
        self.changed.emit()

    def _remove(self) -> None:
        i = self.list.currentRow()
        if 0 <= i < len(self.session.model.monitors):
            del self.session.model.monitors[i]
            self.session.save_model()
            self.refresh()
            self.changed.emit()

    # ------------------------------------------------------------------ dialogs

    def _add_flow_rate(self) -> None:
        d = QDialog(self)
        d.setWindowTitle("Flow rate monitor")
        form = QFormLayout(d)
        name = QLineEdit("flowRate")
        patch = QComboBox()
        patch.addItems(self._patches())
        form.addRow("Name", name)
        form.addRow("Patch", patch)
        if self._exec(d, form) and patch.currentText():
            self._commit(FlowRateMonitor(name=name.text().strip() or "flowRate",
                                         patch=patch.currentText()))

    def _add_field_value(self) -> None:
        d = QDialog(self)
        d.setWindowTitle("Field value monitor")
        form = QFormLayout(d)
        name = QLineEdit("fieldValue")
        field = QComboBox()
        field.addItems(_FIELDS)
        op = QComboBox()
        op.addItems(["volAverage", "max", "min"])
        form.addRow("Name", name)
        form.addRow("Field", field)
        form.addRow("Operation", op)
        if self._exec(d, form):
            self._commit(FieldValueMonitor(
                name=name.text().strip() or "fieldValue",
                field=field.currentText(), operation=op.currentText()))

    def _add_forces(self) -> None:
        d = QDialog(self)
        d.setWindowTitle("Forces / coefficients monitor")
        form = QFormLayout(d)
        name = QLineEdit("forces")
        patches = QListWidget()
        patches.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        patches.addItems(self._patches())
        patches.setMaximumHeight(90)
        u_inf = UnitLineEdit(unit="m/s", value=1.0, minimum=1e-6)
        a_ref = UnitLineEdit(unit="m2", value=1.0, minimum=1e-9)
        l_ref = UnitLineEdit(unit="m", value=1.0, minimum=1e-9)
        rho = UnitLineEdit(value=1.225, minimum=1e-6)
        form.addRow("Name", name)
        form.addRow("Patches", patches)
        form.addRow("Freestream U", u_inf)
        form.addRow("Reference area", a_ref)
        form.addRow("Reference length", l_ref)
        form.addRow("Reference ρ", rho)
        if self._exec(d, form):
            sel = [i.text() for i in patches.selectedItems()]
            self._commit(ForcesMonitor(
                name=name.text().strip() or "forces", patches=sel,
                u_inf=u_inf.value(), a_ref=a_ref.value(), l_ref=l_ref.value(),
                rho_inf=rho.value()))

    def _add_probes(self) -> None:
        d = QDialog(self)
        d.setWindowTitle("Probes monitor")
        form = QFormLayout(d)
        name = QLineEdit("probes")
        fields = QLineEdit("U p")
        points = QLineEdit("0 0 0")
        points.setToolTip("Points as 'x y z; x y z; ...'")
        form.addRow("Name", name)
        form.addRow("Fields", fields)
        form.addRow("Points (x y z; …)", points)
        if self._exec(d, form):
            locs = []
            for chunk in points.text().split(";"):
                nums = chunk.split()
                if len(nums) == 3:
                    locs.append(tuple(float(x) for x in nums))
            self._commit(ProbesMonitor(
                name=name.text().strip() or "probes",
                fields=fields.text().split() or ["U", "p"], locations=locs))

    @staticmethod
    def _exec(dialog: QDialog, form: QFormLayout) -> bool:
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        return dialog.exec() == QDialog.DialogCode.Accepted
