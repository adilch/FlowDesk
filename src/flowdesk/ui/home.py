"""Home screen (PRD §4.1): recent projects, New/Open, environment status strip."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QVBoxLayout,
    QWidget,
)

from flowdesk.app.projects import openfoam_path_problem, validate_project_name
from flowdesk.app.settings import AppSettings
from flowdesk.app.templates import TEMPLATES
from flowdesk.platform.commands import Environment, default_projects_dir, is_slow_location
from flowdesk.ui.components import Banner, make_button
from flowdesk.ui.icons import icon
from flowdesk.ui.theme import COLORS, GROUP_GAP, PANEL_PADDING


def _relative_time(iso: str) -> str:
    """'2h ago' / 'yesterday' / '3d ago' from an ISO timestamp."""
    from datetime import UTC, datetime

    if not iso:
        return ""
    try:
        when = datetime.fromisoformat(iso)
    except ValueError:
        return ""
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    delta = datetime.now(UTC) - when
    secs = int(delta.total_seconds())
    if secs < 90:
        return "just now"
    if secs < 3600:
        return f"{secs // 60}m ago"
    if secs < 86400:
        return f"{secs // 3600}h ago"
    if secs < 172800:
        return "yesterday"
    return f"{secs // 86400}d ago"


_SOLVER_ICON = {"interFoam": "physics", "pimpleFoam": "physics",
                "simpleFoam": "geometry"}


def _reveal(path: str) -> None:
    """Open the project folder in the OS file manager."""
    import subprocess
    import sys

    p = Path(path)
    try:
        if sys.platform == "win32":
            subprocess.Popen(["explorer", str(p)])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(p)])
        else:
            subprocess.Popen(["xdg-open", str(p)])
    except OSError:
        pass


class _RecentRow(QWidget):
    """A compact two-line recent-project row: name + solver/cells/age meta."""

    def __init__(self, entry, exists: bool, parent: QWidget | None = None):
        super().__init__(parent)
        self.setProperty("recentRow", "true")
        row = QHBoxLayout(self)
        row.setContentsMargins(8, 4, 8, 4)
        row.setSpacing(8)

        ic = QLabel()
        ic.setPixmap(icon(_SOLVER_ICON.get(entry.solver, "geometry"),
                          COLORS["text-2"], 18).pixmap(18, 18))
        row.addWidget(ic)

        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)
        name = QLabel(entry.name)
        meta_bits = [b for b in (
            entry.solver,
            f"{entry.cell_count // 1000}k cells" if entry.cell_count >= 1000
            else (f"{entry.cell_count} cells" if entry.cell_count else ""),
            _relative_time(entry.last_opened)) if b]
        meta = QLabel("  ·  ".join(meta_bits) if exists else "missing — locate")
        meta.setProperty("role", "caption")
        col.addWidget(name)
        col.addWidget(meta)
        row.addLayout(col, stretch=1)
        self.setToolTip(entry.path)
        if not exists:
            self.setEnabled(False)


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
        self._populate_templates()
        self.template_combo.setCurrentText("Lid-driven cavity")
        self.template_combo.currentTextChanged.connect(self._on_template_changed)
        form.addRow("Template", self.template_combo)
        layout.addLayout(form)

        template_row = QHBoxLayout()
        self.template_desc = QLabel("")
        self.template_desc.setProperty("role", "caption")
        self.template_desc.setWordWrap(True)
        self.delete_template_btn = make_button("Delete", "ghost")
        self.delete_template_btn.clicked.connect(self._delete_template)
        template_row.addWidget(self.template_desc, stretch=1)
        template_row.addWidget(self.delete_template_btn)
        layout.addLayout(template_row)
        self._on_template_changed(self.template_combo.currentText())

        self._banner_slot = QVBoxLayout()
        layout.addLayout(self._banner_slot)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _populate_templates(self) -> None:
        from flowdesk.app import user_templates

        current = self.template_combo.currentText()
        self.template_combo.blockSignals(True)
        self.template_combo.clear()
        self.template_combo.addItems(list(TEMPLATES))
        self._user_template_names = [t.name for t in user_templates.list_user_templates()]
        if self._user_template_names:
            self.template_combo.insertSeparator(self.template_combo.count())
            self.template_combo.addItems(self._user_template_names)
        if current:
            self.template_combo.setCurrentText(current)
        self.template_combo.blockSignals(False)

    def _on_template_changed(self, name: str) -> None:
        from flowdesk.app import user_templates
        from flowdesk.app.templates import TEMPLATE_DESCRIPTIONS

        is_user = name in getattr(self, "_user_template_names", [])
        self.delete_template_btn.setVisible(is_user)
        if is_user:
            t = user_templates.get_user_template(name)
            desc = (t.description or "Your saved template.") if t else ""
            self.template_desc.setText(f"{desc}   ({t.solver})" if t else desc)
        else:
            self.template_desc.setText(TEMPLATE_DESCRIPTIONS.get(name, ""))

    def _delete_template(self) -> None:
        from flowdesk.app import user_templates

        name = self.template_combo.currentText()
        if user_templates.delete_template(name):
            self._populate_templates()
            self.template_combo.setCurrentText("Lid-driven cavity")
            self._on_template_changed(self.template_combo.currentText())

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
        # Block OpenFOAM-hostile paths up front (spaces/parens in name OR any
        # parent folder) - they fail fatally deep in the mesh pipeline otherwise
        path_problem = openfoam_path_problem(location / self.name_edit.text())
        if path_problem:
            self._banner_slot.addWidget(Banner(path_problem, "error"))
            return
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

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._build_recent_panel())
        outer.addWidget(self._build_welcome(), stretch=1)
        self.refresh_recent()

    # ------------------------------------------------------------------ left

    def _build_recent_panel(self) -> QWidget:
        panel = QFrame()
        panel.setProperty("panel", "true")
        panel.setFixedWidth(280)
        col = QVBoxLayout(panel)
        col.setContentsMargins(12, 16, 12, 16)
        col.setSpacing(8)

        header = QLabel("RECENT PROJECTS")
        header.setProperty("role", "section")
        col.addWidget(header)

        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("Filter…")
        self.filter_edit.textChanged.connect(self._apply_filter)
        col.addWidget(self.filter_edit)

        self.recent_list = QListWidget()
        self.recent_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.recent_list.customContextMenuRequested.connect(self._recent_menu)
        self.recent_list.itemActivated.connect(self._open_item)
        self.recent_list.itemClicked.connect(self._open_item)
        col.addWidget(self.recent_list, stretch=1)
        self._empty_note = QLabel("No recent projects yet.")
        self._empty_note.setProperty("role", "caption")
        self._empty_note.setWordWrap(True)
        col.addWidget(self._empty_note)
        return panel

    def refresh_recent(self) -> None:
        self.recent_list.clear()
        self._empty_note.setVisible(not self.settings.recent)
        for entry in self.settings.recent:
            exists = Path(entry.path).exists()
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, entry.path)
            item.setSizeHint(QSize(0, 46))
            self.recent_list.addItem(item)
            self.recent_list.setItemWidget(item, _RecentRow(entry, exists))
        self._apply_filter(self.filter_edit.text())

    def _apply_filter(self, text: str) -> None:
        needle = text.strip().lower()
        for i in range(self.recent_list.count()):
            item = self.recent_list.item(i)
            path = item.data(Qt.ItemDataRole.UserRole)
            entry = next((r for r in self.settings.recent if r.path == path), None)
            visible = (not needle) or (entry is not None
                                       and needle in entry.name.lower())
            item.setHidden(not visible)

    def _open_item(self, item: QListWidgetItem) -> None:
        path = item.data(Qt.ItemDataRole.UserRole)
        if path and Path(path).exists():
            self.open_requested.emit(Path(path))

    def _recent_menu(self, pos) -> None:
        item = self.recent_list.itemAt(pos)
        if item is None:
            return
        path = item.data(Qt.ItemDataRole.UserRole)
        menu = QMenu(self)
        if Path(path).exists():
            menu.addAction("Open", lambda: self.open_requested.emit(Path(path)))
            menu.addAction("Reveal in file manager", lambda: _reveal(path))
        menu.addAction("Remove from recent", lambda: self._remove_recent(path))
        menu.exec(self.recent_list.mapToGlobal(pos))

    def _remove_recent(self, path: str) -> None:
        self.settings.remove_recent(path)
        self.settings.save()
        self.refresh_recent()

    # ------------------------------------------------------------------ right

    def _build_welcome(self) -> QWidget:
        wrap = QWidget()
        v = QVBoxLayout(wrap)
        margin = PANEL_PADDING * 2
        v.setContentsMargins(margin, margin, margin, margin)
        v.setSpacing(GROUP_GAP // 2)
        v.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        v.addStretch()

        title = QLabel("FlowDesk")
        title.setProperty("role", "title")
        title.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        tagline = QLabel("Set up, run and post-process OpenFOAM — no limits.")
        tagline.setProperty("role", "caption")
        tagline.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        v.addWidget(title)
        v.addWidget(tagline)

        if not self.env.available:
            v.addWidget(Banner(
                f"FlowDesk needs OpenFOAM. {self.env.detail} — fix this once.",
                "warn"))
        else:
            status = QLabel(f"✔ {self.env.detail}")
            status.setProperty("role", "status-ok")
            status.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            v.addWidget(status)

        actions = QHBoxLayout()
        actions.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        new_btn = make_button("New project…", "primary")
        new_btn.setIcon(icon("plus", "#FFFFFF", 18))
        new_btn.clicked.connect(self._new_dialog)
        open_btn = make_button("Open…")
        open_btn.setIcon(icon("folder", COLORS["text-1"], 18))
        open_btn.clicked.connect(self._open_dialog)
        env_btn = make_button("Environment…", "ghost")
        env_btn.clicked.connect(self._environment_dialog)
        actions.addWidget(new_btn)
        actions.addWidget(open_btn)
        actions.addWidget(env_btn)
        v.addLayout(actions)

        if not self.settings.coach_done:
            tutorial = make_button("▶ Try the cavity tutorial (2 min)", "ghost")
            tutorial.clicked.connect(self._start_tutorial)
            v.addWidget(tutorial, alignment=Qt.AlignmentFlag.AlignHCenter)

        quick_title = QLabel("START FROM A TEMPLATE")
        quick_title.setProperty("role", "section")
        quick_title.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        v.addWidget(quick_title)
        grid = QHBoxLayout()
        grid.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        for tmpl in ("Lid-driven cavity", "Flow over Weir (multi-phase)",
                     "Dam break (3D breach)", "Vortex shedding (transient)"):
            if tmpl in TEMPLATES:
                b = make_button(tmpl.split(" (")[0])
                b.clicked.connect(lambda _=False, t=tmpl: self._quick_create(t))
                grid.addWidget(b)
        v.addLayout(grid)
        v.addStretch()
        return wrap

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

    def _start_tutorial(self) -> None:
        self._quick_create("Lid-driven cavity", prefix="cavity-tutorial")

    def _quick_create(self, template: str, prefix: str = "") -> None:
        from datetime import datetime

        slug = prefix or template.split(" (")[0].lower().replace(" ", "-")
        name = f"{slug}-{datetime.now().strftime('%H%M%S')}"
        location = Path(self.settings.last_location or
                        str(default_projects_dir(self.env)))
        self.create_requested.emit(name, location, template)
