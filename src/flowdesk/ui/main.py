"""FlowDesk application entry point: Home <-> Project window (PRD §5.1)."""

from __future__ import annotations

import sys
from pathlib import Path

from PyQt6.QtWidgets import QApplication, QMainWindow, QMessageBox, QStackedWidget

from flowdesk.app import projects
from flowdesk.app.settings import AppSettings
from flowdesk.platform.commands import probe_environment
from flowdesk.ui.home import HomeScreen
from flowdesk.ui.shell import ProjectShell
from flowdesk.ui.theme import apply_theme


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("FlowDesk")
        self.resize(1400, 900)

        self.settings = AppSettings.load()
        self.env = probe_environment()

        self._stack = QStackedWidget()
        self.home = HomeScreen(self.env, self.settings)
        self.home.create_requested.connect(self._create_project)
        self.home.open_requested.connect(self._open_project)
        self._stack.addWidget(self.home)
        self.setCentralWidget(self._stack)
        self._shell: ProjectShell | None = None

    def _create_project(self, name: str, location: Path, template: str) -> None:
        try:
            session = projects.create_project(name, location, template, self.settings)
        except (ValueError, FileExistsError, OSError) as exc:
            QMessageBox.critical(self, "Could not create project", str(exc))
            return
        self._show_project(session)

    def _open_project(self, path: Path) -> None:
        try:
            session = projects.open_project(path, self.settings)
        except (FileNotFoundError, ValueError) as exc:
            QMessageBox.critical(self, "Could not open project", str(exc))
            return
        self._show_project(session)

    def _show_project(self, session: projects.ProjectSession) -> None:
        if self._shell is not None:
            self._stack.removeWidget(self._shell)
            self._shell.deleteLater()
        self._shell = ProjectShell(session, self.env)
        self._stack.addWidget(self._shell)
        self._stack.setCurrentWidget(self._shell)
        self.setWindowTitle(f"FlowDesk — {session.model.meta.name}")


def main() -> int:
    app = QApplication(sys.argv)
    apply_theme(app)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
