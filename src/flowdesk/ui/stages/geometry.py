"""Geometry stage (PRD §4.2): viewer-dominant, surface list + diagnostics, import."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from flowdesk.app import geometry_io
from flowdesk.app.projects import ProjectSession
from flowdesk.model.findings import Stage
from flowdesk.ui.components import Banner, TrafficLightRow, make_button
from flowdesk.ui.theme import PANEL_PADDING, RIGHT_PANEL_WIDTH


class GeometryStage(QWidget):
    """Center = shared viewer (inserted by the shell); right = surfaces panel."""

    model_changed = pyqtSignal(Stage)

    def __init__(self, session: ProjectSession, parent: QWidget | None = None):
        super().__init__(parent)
        self.session = session

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.viewer_slot = QVBoxLayout()
        layout.addLayout(self.viewer_slot, stretch=1)

        panel = QWidget()
        panel.setFixedWidth(RIGHT_PANEL_WIDTH)
        self._panel_layout = QVBoxLayout(panel)
        self._panel_layout.setContentsMargins(
            PANEL_PADDING, PANEL_PADDING, PANEL_PADDING, PANEL_PADDING)
        layout.addWidget(panel)

        title = QLabel("Geometry")
        title.setProperty("role", "title")
        self._panel_layout.addWidget(title)

        self.import_btn = make_button("Import STL…", "primary")
        self.import_btn.clicked.connect(self._import_dialog)
        self._panel_layout.addWidget(self.import_btn)

        self.blockmesh_only = QCheckBox("blockMesh-only case (no STL geometry)")
        self.blockmesh_only.setChecked(session.model.geometry.blockmesh_only)
        self.blockmesh_only.toggled.connect(self._on_blockmesh_only)
        self._panel_layout.addWidget(self.blockmesh_only)

        self._surfaces_box = QVBoxLayout()
        self._panel_layout.addLayout(self._surfaces_box)
        self._panel_layout.addStretch()
        self.refresh()

    # ------------------------------------------------------------------ actions

    def _on_blockmesh_only(self, checked: bool) -> None:
        self.session.model.geometry.blockmesh_only = checked
        self.session.save_model()
        self.model_changed.emit(Stage.GEOMETRY)

    def _import_dialog(self) -> None:
        path_str, _ = QFileDialog.getOpenFileName(
            self, "Import geometry", "", "Surface meshes (*.stl *.obj)")
        if path_str:
            self.import_stl(Path(path_str))

    def import_stl(self, path: Path, scale: float | None = None) -> None:
        """Import with diagnostics; prompts for unit scaling when suspect (§4.2)."""
        if scale is None:
            diag = geometry_io.analyze(path)
            prompt = geometry_io.units_suspect(diag)
            scale = 1.0
            if prompt:
                scale = self._ask_scale(prompt)

        surface = geometry_io.import_surface(path, self.session.case_dir, scale)
        geo = self.session.model.geometry
        geo.surfaces = [s for s in geo.surfaces if s.name != surface.name]
        geo.surfaces.append(surface)
        geo.blockmesh_only = False
        self.session.save_model()
        self.session.staleness.mark_applied(Stage.GEOMETRY, f"geometry changed: + {surface.name}")
        self.refresh()
        self.model_changed.emit(Stage.GEOMETRY)

    def _ask_scale(self, prompt: str) -> float:
        box = QMessageBox(self)
        box.setWindowTitle("Units check")
        box.setText(prompt)
        buttons = {
            box.addButton("mm → m (×0.001)", QMessageBox.ButtonRole.AcceptRole): 0.001,
            box.addButton("cm → m (×0.01)", QMessageBox.ButtonRole.AcceptRole): 0.01,
            box.addButton("in → m (×0.0254)", QMessageBox.ButtonRole.AcceptRole): 0.0254,
            box.addButton("Already meters", QMessageBox.ButtonRole.RejectRole): 1.0,
        }
        box.exec()
        clicked = box.clickedButton()
        return buttons.get(clicked, 1.0)

    # ------------------------------------------------------------------ display

    def refresh(self) -> None:
        while self._surfaces_box.count():
            item = self._surfaces_box.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        surfaces = self.session.model.geometry.surfaces
        if not surfaces:
            note = QLabel("No surfaces imported.")
            note.setProperty("role", "caption")
            self._surfaces_box.addWidget(note)
            return
        for s in surfaces:
            d = s.diagnostics
            header = QLabel(f"{s.name} — {d.triangle_count:,} triangles"
                            + (f" (×{s.scale:g})" if s.scale != 1.0 else ""))
            self._surfaces_box.addWidget(header)
            self._surfaces_box.addWidget(TrafficLightRow(
                "Watertight", "yes" if d.watertight else "no",
                "pass" if d.watertight else "warn"))
            self._surfaces_box.addWidget(TrafficLightRow(
                "Normals outward", "yes" if d.normals_outward else "check",
                "pass" if d.normals_outward else "warn"))
            if not d.watertight:
                self._surfaces_box.addWidget(Banner(
                    f"'{s.name}' is not watertight — fine for snapping, not as a "
                    "closed region.", "warn"))


class PlaceholderStage(QWidget):
    """Empty-state panel for stages arriving in later milestones (§6.4)."""

    def __init__(self, title: str, milestone: str, parent: QWidget | None = None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        label = QLabel(f"{title} arrives in {milestone}.")
        label.setProperty("role", "caption")
        layout.addStretch()
        layout.addWidget(label)
        layout.addStretch()
