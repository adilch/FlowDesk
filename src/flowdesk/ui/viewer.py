"""Shared 3D viewer widget (PRD §4.2) - M0 spike scope: embed PyVista in Qt, load STL,
orbit/pan/zoom, fit, and report rendering FPS.
"""

from __future__ import annotations

from pathlib import Path

import pyvista as pv
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QVBoxLayout, QWidget
from pyvistaqt import QtInteractor

from flowdesk.ui.theme import COLORS


class ViewerWidget(QWidget):
    """PyVista plotter embedded as a Qt widget. One instance is shared across stages."""

    fpsMeasured = pyqtSignal(float)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.plotter = QtInteractor(self)
        self.plotter.set_background(COLORS["viewport-bottom"], top=COLORS["viewport-top"])
        layout.addWidget(self.plotter)
        self._meshes: dict[str, pv.DataSet] = {}

        # FPS via VTK render-event timing
        self.plotter.iren.add_observer("RenderEvent", self._on_render)

    def _on_render(self, *_args) -> None:
        seconds = self.plotter.renderer.GetLastRenderTimeInSeconds()
        if seconds > 0:
            self.fpsMeasured.emit(1.0 / seconds)

    def load_surface(
        self, path: Path, name: str | None = None, color: str | None = None
    ) -> pv.DataSet:
        """Load an STL/OBJ surface and show it. Returns the mesh for diagnostics."""
        mesh = pv.read(str(path))
        key = name or path.stem
        self._meshes[key] = mesh
        self.plotter.add_mesh(
            mesh,
            name=key,
            color=color or COLORS["text-2"],
            smooth_shading=True,
            show_edges=False,
        )
        self.plotter.reset_camera()
        return mesh

    def fit(self) -> None:
        self.plotter.reset_camera()
