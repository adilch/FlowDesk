"""Shared 3D viewer widget (PRD §4.2) - M0 spike scope: embed PyVista in Qt, load STL,
orbit/pan/zoom, fit, and report rendering FPS.
"""

from __future__ import annotations

from pathlib import Path

import pyvista as pv
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
from pyvistaqt import QtInteractor

from flowdesk.ui.components import make_button
from flowdesk.ui.theme import COLORS


class ViewerWidget(QWidget):
    """PyVista plotter embedded as a Qt widget. One instance is shared across stages."""

    fpsMeasured = pyqtSignal(float)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Viewer toolbar (§4.2): standard views + fit, travels with the viewer
        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(4, 2, 4, 2)
        toolbar.addStretch()
        for label, slot in (("X", self.view_x), ("Y", self.view_y),
                            ("Z", self.view_z), ("Fit", self.fit)):
            btn = make_button(label, "ghost")
            btn.setFixedWidth(40 if label == "Fit" else 28)
            btn.setToolTip(f"Look along the {label} axis"
                           if label != "Fit" else "Fit view to scene (F)")
            btn.clicked.connect(slot)
            toolbar.addWidget(btn)
        layout.addLayout(toolbar)

        self.plotter = QtInteractor(self)
        self.plotter.set_background(COLORS["viewport-bottom"], top=COLORS["viewport-top"])
        layout.addWidget(self.plotter)
        self._meshes: dict[str, pv.DataSet] = {}

        # Orientation triad, bottom-right: which way is x/y/z at a glance
        self.plotter.add_axes(viewport=(0.80, 0.0, 1.0, 0.25), line_width=2)

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

    def show_region_overlay(self, name: str, geometry) -> None:
        """Translucent refinement-region overlay (§4.3.2): box/sphere/cylinder."""
        from flowdesk.model.mesh import BoxRegion, CylinderRegion, SphereRegion

        if isinstance(geometry, BoxRegion):
            (x0, y0, z0), (x1, y1, z1) = geometry.min, geometry.max
            shape = pv.Box(bounds=(x0, x1, y0, y1, z0, z1))
        elif isinstance(geometry, SphereRegion):
            shape = pv.Sphere(center=geometry.centre, radius=geometry.radius)
        elif isinstance(geometry, CylinderRegion):
            p1, p2 = geometry.point1, geometry.point2
            center = tuple((a + b) / 2 for a, b in zip(p1, p2, strict=True))
            direction = tuple(b - a for a, b in zip(p1, p2, strict=True))
            height = sum(d * d for d in direction) ** 0.5
            shape = pv.Cylinder(center=center, direction=direction,
                                radius=geometry.radius, height=height)
        else:
            return
        self.plotter.add_mesh(shape, name=f"_region_{name}", color=COLORS["run"],
                              opacity=0.25)

    def clear_region_overlays(self, names: list[str]) -> None:
        for name in names:
            self.plotter.remove_actor(f"_region_{name}")

    def show_location_marker(self, point) -> None:
        """The locationInMesh material point, rendered as a marker (§4.3.2)."""
        marker = pv.Sphere(center=point, radius=self._marker_radius())
        self.plotter.add_mesh(marker, name="_location_marker", color=COLORS["warn"])

    def _marker_radius(self) -> float:
        bounds = self.plotter.bounds
        diag = ((bounds[1] - bounds[0]) ** 2 + (bounds[3] - bounds[2]) ** 2
                + (bounds[5] - bounds[4]) ** 2) ** 0.5
        return max(diag / 150.0, 1e-6)

    def show_patches(self, case_dir: Path, assignments: dict[str, str | None]) -> bool:
        """BC stage (§4.5): meshed boundary patches as actors colored by their
        assigned BC (Okabe-Ito palette); unassigned renders hazard-amber."""
        foam_file = case_dir / "case.foam"
        try:
            foam_file.touch()
            reader = pv.OpenFOAMReader(str(foam_file))
            reader.enable_all_patch_arrays()
            data = reader.read()
            boundaries = data["boundary"]
        except Exception:
            return False
        self.plotter.clear()
        self._patch_actors = {}
        patch_names = boundaries.keys()  # MultiBlock: .keys() is the only name API
        for name in patch_names:
            patch = boundaries[name]
            color = assignments.get(name) or COLORS["warn"]
            actor = self.plotter.add_mesh(
                patch, name=f"_patch_{name}", color=color,
                opacity=1.0 if assignments.get(name) else 0.85,
                show_edges=False, smooth_shading=False,
            )
            self._patch_actors[name] = (actor, color)
        self.plotter.reset_camera()
        return True

    def highlight_patches(self, selected: set[str]) -> None:
        """BC stage (§4.5): selected patches pop, the rest fade. Empty selection
        restores everyone. No-op when no patches are loaded."""
        actors = getattr(self, "_patch_actors", {})
        for name, (actor, _base) in actors.items():
            prop = actor.GetProperty()
            if not selected:
                prop.SetOpacity(1.0)
                actor.SetVisibility(True)
                prop.EdgeVisibilityOff()
            elif name in selected:
                prop.SetOpacity(1.0)
                prop.EdgeVisibilityOn()
                prop.SetEdgeColor(1.0, 1.0, 1.0)
                prop.SetLineWidth(2)
            else:
                prop.SetOpacity(0.18)
                prop.EdgeVisibilityOff()
        self.plotter.render()

    # Distinct highlight colours (Okabe-Ito categorical) for selected patches.
    _PATCH_PALETTE = ["#0072B2", "#D55E00", "#009E73", "#CC79A7",
                      "#56B4E9", "#E69F00", "#F0E442", "#999999"]

    @staticmethod
    def _hex_rgb(hex_color: str) -> tuple[float, float, float]:
        h = hex_color.lstrip("#")
        return tuple(int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))

    def show_mesh_patches(self, case_dir: Path) -> list[str]:
        """Mesh stage: load the meshed boundary patches as individually-
        colorable actors (neutral grey, edged). Returns the patch names, or []
        when the reader can't load them."""
        foam_file = case_dir / "case.foam"
        try:
            foam_file.touch()
            reader = pv.OpenFOAMReader(str(foam_file))
            reader.enable_all_patch_arrays()
            boundaries = reader.read()["boundary"]
        except Exception:
            return []
        self.plotter.clear()
        self._mesh_patch_actors = {}
        names = list(boundaries.keys())
        for name in names:
            actor = self.plotter.add_mesh(
                boundaries[name], name=f"_mpatch_{name}",
                color=COLORS["text-2"], show_edges=True,
                edge_color=COLORS["border"], smooth_shading=False)
            self._mesh_patch_actors[name] = actor
        self.plotter.reset_camera()
        return names

    def color_selected_patches(self, selected: list[str]) -> None:
        """Highlight the selected meshed patches, each a distinct colour; fade
        the rest. Empty selection restores the neutral mesh."""
        actors = getattr(self, "_mesh_patch_actors", {})
        sel = list(selected)
        neutral = self._hex_rgb(COLORS["text-2"])
        for name, actor in actors.items():
            prop = actor.GetProperty()
            if not sel:
                prop.SetColor(*neutral)
                prop.SetOpacity(1.0)
            elif name in sel:
                color = self._PATCH_PALETTE[sel.index(name) % len(self._PATCH_PALETTE)]
                prop.SetColor(*self._hex_rgb(color))
                prop.SetOpacity(1.0)
            else:
                prop.SetColor(*neutral)
                prop.SetOpacity(0.2)
        self.plotter.render()

    def load_openfoam_mesh(self, case_dir: Path) -> int | None:
        """Mesh preview (§4.3.3): surface-with-edges of the current polyMesh.

        Returns the cell count, or None when the reader can't load it
        (preview is best-effort; the quality report is authoritative)."""
        foam_file = case_dir / "case.foam"
        try:
            foam_file.touch()
            reader = pv.OpenFOAMReader(str(foam_file))
            data = reader.read()
            internal = data["internalMesh"]
            surface = internal.extract_surface()
            self.plotter.remove_actor("_domain_box")
            self.plotter.add_mesh(surface, name="_mesh_preview",
                                  color=COLORS["text-2"], show_edges=True,
                                  edge_color=COLORS["border"])
            self.plotter.reset_camera()
            return internal.n_cells
        except Exception:
            return None

    def show_domain_box(self, bounds_min, bounds_max) -> None:
        """Wireframe outline of the blockMesh background box (§4.3.1)."""
        (x0, y0, z0), (x1, y1, z1) = bounds_min, bounds_max
        box = pv.Box(bounds=(x0, x1, y0, y1, z0, z1))
        self.plotter.add_mesh(
            box.extract_all_edges(),
            name="_domain_box",
            color=COLORS["accent"],
            line_width=1,
        )
        self.plotter.reset_camera()

    def show_water_column(self, bounds_min, bounds_max) -> None:
        """Free-surface init volume: the water column as a translucent blue box
        (the SimFlow-style 'water_init' region - initialization, never meshed)."""
        (x0, y0, z0), (x1, y1, z1) = bounds_min, bounds_max
        box = pv.Box(bounds=(x0, x1, y0, y1, z0, z1))
        self.plotter.add_mesh(
            box, name="_water_column",
            color="#0072B2", opacity=0.30, show_edges=True,
        )

    def hide_water_column(self) -> None:
        self.plotter.remove_actor("_water_column", render=False)

    def closeEvent(self, event) -> None:
        # Release the GL context before the native window dies (silences
        # vtkWin32OpenGLRenderWindow teardown errors)
        self.plotter.close()
        super().closeEvent(event)

    def set_surface_visible(self, name: str, visible: bool) -> None:
        """Toggle a loaded surface actor without reloading (§4.2 per-surface
        visibility). No-op if the surface is not currently shown."""
        actor = self.plotter.renderer.actors.get(name)
        if actor is not None:
            actor.SetVisibility(visible)
            self.plotter.render()

    def fit(self) -> None:
        self.plotter.reset_camera()

    # Standard views (§4.2): camera looking along the named axis
    def view_x(self) -> None:
        self.plotter.view_yz()
        self.plotter.reset_camera()

    def view_y(self) -> None:
        self.plotter.view_xz()
        self.plotter.reset_camera()

    def view_z(self) -> None:
        self.plotter.view_xy()
        self.plotter.reset_camera()
