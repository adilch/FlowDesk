"""Home screen (PRD §4.1): recent projects, New/Open, environment status strip."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from flowdesk.app.projects import validate_project_name
from flowdesk.app.settings import AppSettings
from flowdesk.app.templates import TEMPLATES
from flowdesk.platform.commands import Environment, default_projects_dir, is_slow_location
from flowdesk.ui.components import Banner, make_button
from flowdesk.ui.theme import GROUP_GAP, PANEL_PADDING


class NewProjectDialog(QDialog):
    """Name / location / template / solver intent (§4.1). One of the few modals."""

    def __init__(self, env: Environment, settings: AppSettings,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("New Project")
        self.env = env

        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.name_edit = QLineEdit("Untitled-1")
        form.addRow("Name", self.name_edit)

        location_row = QHBoxLayout()
        default_loc = settings.last_location or str(default_projects_dir(env))
        self.location_edit = QLineEdit(default_loc)
        browse = make_button("Browse…")
        browse.clicked.connect(self._browse)
        location_row.addWidget(self.location_edit)
        location_row.addWidget(browse)
        form.addRow("Location", location_row)

        self.template_combo = QComboBox()
        self.template_combo.addItems(list(TEMPLATES))
        self.template_combo.setCurrentText("Lid-driven cavity")
        form.addRow("Template", self.template_combo)
        layout.addLayout(form)

        self._banner_slot = QVBoxLayout()
        layout.addLayout(self._banner_slot)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _browse(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "Project location",
                                                  self.location_edit.text())
        if chosen:
            self.location_edit.setText(chosen)

    def _validate_and_accept(self) -> None:
        while self._banner_slot.count():
            item = self._banner_slot.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        error = validate_project_name(self.name_edit.text())
        if error:
            self._banner_slot.addWidget(Banner(error, "error"))
            return
        location = Path(self.location_edit.text())
        if " " in self.name_edit.text():
            self._banner_slot.addWidget(Banner(
                "Spaces in the name will cause WSL path friction.", "warn"))
        if is_slow_location(location, self.env):
            self._banner_slot.addWidget(Banner(
                "This location is on a Windows drive: OpenFOAM I/O will be 5–20× "
                "slower than the recommended WSL home (§8.4). Continuing anyway.",
                "warn"))
        self.accept()

    @property
    def values(self) -> tuple[str, Path, str]:
        return (self.name_edit.text().strip(), Path(self.location_edit.text()),
                self.template_combo.currentText())


class HomeScreen(QWidget):
    create_requested = pyqtSignal(str, Path, str)  # name, location, template
    open_requested = pyqtSignal(Path)

    def __init__(self, env: Environment, settings: AppSettings,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.env = env
        self.settings = settings

        layout = QVBoxLayout(self)
        margin = PANEL_PADDING * 3
        layout.setContentsMargins(margin, margin, margin, margin)
        layout.setSpacing(GROUP_GAP)

        title = QLabel("FlowDesk")
        title.setProperty("role", "title")
        layout.addWidget(title)

        # Environment status strip (§4.1): say nothing when green
        if not env.available:
            layout.addWidget(Banner(
                f"FlowDesk needs OpenFOAM. {env.detail} — fix this once and "
                "everything else works.", "warn"))
        else:
            status = QLabel(f"✔ {env.detail}")
            status.setProperty("role", "caption")
            layout.addWidget(status)

        actions = QHBoxLayout()
        new_btn = make_button("New Project…", "primary")
        new_btn.clicked.connect(self._new_dialog)
        open_btn = make_button("Open Project…")
        open_btn.clicked.connect(self._open_dialog)
        settings_btn = make_button("Environment…", "ghost")
        settings_btn.clicked.connect(self._environment_dialog)
        actions.addWidget(new_btn)
        actions.addWidget(open_btn)
        actions.addWidget(settings_btn)
        actions.addStretch()
        layout.addLayout(actions)

        recent_title = QLabel("RECENT")
        recent_title.setProperty("role", "section")
        layout.addWidget(recent_title)
        self._recent_box = QVBoxLayout()
        layout.addLayout(self._recent_box)
        layout.addStretch()
        self.refresh_recent()

    def refresh_recent(self) -> None:
        while self._recent_box.count():
            item = self._recent_box.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        if not self.settings.recent:
            note = QLabel("No recent projects. Start with the lid-driven cavity "
                          "template — it doubles as an environment check.")
            note.setProperty("role", "caption")
            self._recent_box.addWidget(note)
            return
        for entry in self.settings.recent:
            exists = Path(entry.path).exists()
            label = entry.name + (f" — {entry.solver}" if entry.solver else "")
            if entry.cell_count:
                label += f" — {entry.cell_count:,} cells"
            btn = make_button(label, "ghost")
            btn.setToolTip(entry.path)
            if exists:
                btn.clicked.connect(
                    lambda _=False, p=entry.path: self.open_requested.emit(Path(p)))
            else:
                btn.setEnabled(False)
                btn.setText(label + "  (missing — locate via Open Project)")
            self._recent_box.addWidget(btn)

    def _new_dialog(self) -> None:
        dialog = NewProjectDialog(self.env, self.settings, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            name, location, template = dialog.values
            self.settings.last_location = str(location)
            self.settings.save()
            self.create_requested.emit(name, location, template)

    def _open_dialog(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "Open project")
        if chosen:
            self.open_requested.emit(Path(chosen))

    def _environment_dialog(self) -> None:
        from flowdesk.ui.environment_panel import EnvironmentDialog

        EnvironmentDialog(self.env, self).exec()
