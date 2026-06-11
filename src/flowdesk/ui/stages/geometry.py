"""Geometry stage (PRD §4.2): viewer-dominant; geometry list with per-surface
visibility, in-app primitive creation (box/sphere/cylinder/cone/plane), import,
and diagnostics for the selected surface."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from flowdesk.app import geometry_io
from flowdesk.app.projects import ProjectSession
from flowdesk.model.findings import Stage
from flowdesk.model.geometry import (
    BoxPrimitive,
    ConePrimitive,
    CylinderPrimitive,
    PlanePrimitive,
    Primitive,
    SpherePrimitive,
    Surface,
)
from flowdesk.ui.components import Banner, TrafficLightRow, UnitLineEdit, Vec3Input, make_button
from flowdesk.ui.theme import PANEL_PADDING, RIGHT_PANEL_WIDTH

EYE_SHOWN = "👁"
EYE_HIDDEN = "—"

SHAPE_LABELS = {"box": "Box", "sphere": "Sphere", "cylinder": "Cylinder",
                "cone": "Cone", "plane": "Plane"}


def default_primitive(shape: str, centre, size: float) -> Primitive:
    """A sensibly-placed primitive of the given shape (centred, ~size across)."""
    cx, cy, cz = centre
    h = size / 2
    if shape == "box":
        return BoxPrimitive(min=(cx - h, cy - h, cz - h), max=(cx + h, cy + h, cz + h))
    if shape == "sphere":
        return SpherePrimitive(centre=centre, radius=h)
    if shape == "cylinder":
        return CylinderPrimitive(point1=(cx, cy, cz - h), point2=(cx, cy, cz + h),
                                 radius=h / 2)
    if shape == "cone":
        return ConePrimitive(base_centre=(cx, cy, cz - h), direction=(0.0, 0.0, 1.0),
                             radius=h / 2, height=size)
    return PlanePrimitive(centre=centre, normal=(0.0, 0.0, 1.0), i_size=size, j_size=size)


class PrimitiveDialog(QDialog):
    """Edit the parameters of one primitive. Returns the spec via .spec()."""

    def __init__(self, spec: Primitive, parent: QWidget | None = None):
        super().__init__(parent)
        self._shape = spec.shape
        self.setWindowTitle(f"{SHAPE_LABELS[spec.shape]} geometry")
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self._fields: dict[str, object] = {}

        def vec(label: str, key: str, value) -> None:
            w = Vec3Input(unit="m", value=value)
            self._fields[key] = w
            form.addRow(label, w)

        def num(label: str, key: str, value: float) -> None:
            w = UnitLineEdit(unit="m", value=value, minimum=1e-9)
            self._fields[key] = w
            form.addRow(label, w)

        if isinstance(spec, BoxPrimitive):
            vec("Min corner", "min", spec.min)
            vec("Max corner", "max", spec.max)
        elif isinstance(spec, SpherePrimitive):
            vec("Centre", "centre", spec.centre)
            num("Radius", "radius", spec.radius)
        elif isinstance(spec, CylinderPrimitive):
            vec("End 1", "point1", spec.point1)
            vec("End 2", "point2", spec.point2)
            num("Radius", "radius", spec.radius)
        elif isinstance(spec, ConePrimitive):
            vec("Base centre", "base_centre", spec.base_centre)
            vec("Axis direction", "direction", spec.direction)
            num("Radius", "radius", spec.radius)
            num("Height", "height", spec.height)
        elif isinstance(spec, PlanePrimitive):
            vec("Centre", "centre", spec.centre)
            vec("Normal", "normal", spec.normal)
            num("Width (i)", "i_size", spec.i_size)
            num("Height (j)", "j_size", spec.j_size)
        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def spec(self) -> Primitive:
        def v(key):
            return self._fields[key].value()

        if self._shape == "box":
            return BoxPrimitive(min=v("min"), max=v("max"))
        if self._shape == "sphere":
            return SpherePrimitive(centre=v("centre"), radius=v("radius"))
        if self._shape == "cylinder":
            return CylinderPrimitive(point1=v("point1"), point2=v("point2"),
                                     radius=v("radius"))
        if self._shape == "cone":
            return ConePrimitive(base_centre=v("base_centre"), direction=v("direction"),
                                 radius=v("radius"), height=v("height"))
        return PlanePrimitive(centre=v("centre"), normal=v("normal"),
                              i_size=v("i_size"), j_size=v("j_size"))


class GeometryStage(QWidget):
    """Center = shared viewer (inserted by the shell); right = geometry panel."""

    model_changed = pyqtSignal(Stage)
    visibility_toggled = pyqtSignal(str, bool)  # surface name, visible

    def __init__(self, session: ProjectSession, parent: QWidget | None = None):
        super().__init__(parent)
        self.session = session
        self._hidden: set[str] = set()  # session-only visibility

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

        actions = QHBoxLayout()
        self.import_btn = make_button("Import STL…", "primary")
        self.import_btn.clicked.connect(self._import_dialog)
        self.create_btn = QToolButton()
        self.create_btn.setText("Create ▾")
        self.create_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(self.create_btn)
        for shape, label in SHAPE_LABELS.items():
            menu.addAction(label, lambda s=shape: self._create_primitive(s))
        self.create_btn.setMenu(menu)
        actions.addWidget(self.import_btn)
        actions.addWidget(self.create_btn)
        self._panel_layout.addLayout(actions)

        self.blockmesh_only = QCheckBox("blockMesh-only case (no STL geometry)")
        self.blockmesh_only.setChecked(session.model.geometry.blockmesh_only)
        self.blockmesh_only.toggled.connect(self._on_blockmesh_only)
        self._panel_layout.addWidget(self.blockmesh_only)

        self.geometry_list = QListWidget()
        self.geometry_list.setMaximumHeight(180)
        self.geometry_list.currentRowChanged.connect(lambda _i: self._show_diagnostics())
        self.geometry_list.itemDoubleClicked.connect(self._edit_current)
        self._panel_layout.addWidget(self.geometry_list)

        row_actions = QHBoxLayout()
        self.edit_btn = make_button("Edit…", "ghost")
        self.edit_btn.clicked.connect(lambda: self._edit_current(None))
        self.delete_btn = make_button("Delete", "danger")
        self.delete_btn.clicked.connect(self._delete_current)
        row_actions.addWidget(self.edit_btn)
        row_actions.addWidget(self.delete_btn)
        row_actions.addStretch()
        self._panel_layout.addLayout(row_actions)

        self._diag_box = QVBoxLayout()
        self._panel_layout.addLayout(self._diag_box)
        self._panel_layout.addStretch()
        self.refresh()

    # ------------------------------------------------------------------ helpers

    def hidden_surfaces(self) -> set[str]:
        """Names the shell's viewer refresh should skip (session-only)."""
        return set(self._hidden)

    def _surface_names(self) -> list[str]:
        return [s.name for s in self.session.model.geometry.surfaces]

    def _selected_surface(self) -> Surface | None:
        row = self.geometry_list.currentRow()
        surfaces = self.session.model.geometry.surfaces
        return surfaces[row] if 0 <= row < len(surfaces) else None

    def _placement(self):
        """Centre + characteristic size for a new primitive (domain, else geom)."""
        block = self.session.model.mesh.block
        lo, hi = block.bounds_min, block.bounds_max
        if hi != lo:
            centre = tuple((a + b) / 2 for a, b in zip(lo, hi, strict=True))
            size = min(b - a for a, b in zip(lo, hi, strict=True)) / 3
            return centre, max(size, 1e-3)
        return (0.0, 0.0, 0.0), 1.0

    # ------------------------------------------------------------------ actions

    def _on_blockmesh_only(self, checked: bool) -> None:
        self.session.model.geometry.blockmesh_only = checked
        self.session.save_model()
        self.model_changed.emit(Stage.GEOMETRY)

    def _create_primitive(self, shape: str) -> None:
        centre, size = self._placement()
        dialog = PrimitiveDialog(default_primitive(shape, centre, size), self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        name = geometry_io.unique_surface_name(self._surface_names(), shape)
        surface = geometry_io.write_primitive(dialog.spec(), self.session.case_dir, name)
        self._add_surface(surface)

    def _edit_current(self, _item) -> None:
        surface = self._selected_surface()
        if surface is None:
            return
        if surface.primitive is None:
            QMessageBox.information(
                self, "Edit geometry",
                f"'{surface.name}' was imported from an STL — re-import to change "
                "it. Only primitives created in FlowDesk are editable here.")
            return
        dialog = PrimitiveDialog(surface.primitive, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        updated = geometry_io.write_primitive(dialog.spec(), self.session.case_dir,
                                              surface.name)
        geo = self.session.model.geometry
        geo.surfaces = [updated if s.name == surface.name else s for s in geo.surfaces]
        self.session.save_model()
        self.session.staleness.mark_applied(
            Stage.GEOMETRY, f"geometry changed: edited {surface.name}")
        self.refresh()
        self.model_changed.emit(Stage.GEOMETRY)

    def _delete_current(self) -> None:
        surface = self._selected_surface()
        if surface is None:
            return
        stl = self.session.case_dir / "constant" / "triSurface" / f"{surface.name}.stl"
        stl.unlink(missing_ok=True)
        geo = self.session.model.geometry
        geo.surfaces = [s for s in geo.surfaces if s.name != surface.name]
        # drop matching snappy refinement row, if any
        snappy = self.session.model.mesh.snappy
        snappy.surfaces = [r for r in snappy.surfaces if r.surface != surface.name]
        self._hidden.discard(surface.name)
        self.session.save_model()
        self.session.staleness.mark_applied(
            Stage.GEOMETRY, f"geometry changed: − {surface.name}")
        self.refresh()
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
        self._add_surface(surface)

    def _add_surface(self, surface: Surface) -> None:
        geo = self.session.model.geometry
        geo.surfaces = [s for s in geo.surfaces if s.name != surface.name]
        geo.surfaces.append(surface)
        geo.blockmesh_only = False
        self.blockmesh_only.setChecked(False)
        self.session.save_model()
        self.session.staleness.mark_applied(
            Stage.GEOMETRY, f"geometry changed: + {surface.name}")
        self.refresh()
        self.geometry_list.setCurrentRow(len(geo.surfaces) - 1)
        self.model_changed.emit(Stage.GEOMETRY)

    def _toggle_visibility(self, name: str) -> None:
        visible = name in self._hidden
        if visible:
            self._hidden.discard(name)
        else:
            self._hidden.add(name)
        self._refresh_eye(name)
        self.visibility_toggled.emit(name, visible)

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
        return buttons.get(box.clickedButton(), 1.0)

    # ------------------------------------------------------------------ display

    def refresh(self) -> None:
        self.geometry_list.clear()
        self._eye_buttons: dict[str, QToolButton] = {}
        for surface in self.session.model.geometry.surfaces:
            item = QListWidgetItem(self.geometry_list)
            row = self._make_row(surface)
            item.setSizeHint(row.sizeHint())
            self.geometry_list.addItem(item)
            self.geometry_list.setItemWidget(item, row)
        has = bool(self.session.model.geometry.surfaces)
        self.edit_btn.setEnabled(has)
        self.delete_btn.setEnabled(has)
        if has:
            self.geometry_list.setCurrentRow(self.geometry_list.count() - 1)
        self._show_diagnostics()

    def _make_row(self, surface: Surface) -> QWidget:
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(4, 2, 4, 2)
        eye = QToolButton()
        eye.setCheckable(True)
        eye.setText(EYE_HIDDEN if surface.name in self._hidden else EYE_SHOWN)
        eye.setToolTip("Show/hide in the 3D view")
        eye.clicked.connect(lambda _=False, n=surface.name: self._toggle_visibility(n))
        self._eye_buttons[surface.name] = eye
        kind = SHAPE_LABELS[surface.primitive.shape] if surface.primitive else "STL"
        label = QLabel(f"{surface.name}  ·  {kind}")
        h.addWidget(eye)
        h.addWidget(label, stretch=1)
        return row

    def _refresh_eye(self, name: str) -> None:
        eye = getattr(self, "_eye_buttons", {}).get(name)
        if eye is not None:
            eye.setText(EYE_HIDDEN if name in self._hidden else EYE_SHOWN)

    def _show_diagnostics(self) -> None:
        while self._diag_box.count():
            item = self._diag_box.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        surface = self._selected_surface()
        if surface is None:
            note = QLabel("No geometry yet — import an STL or create a primitive.")
            note.setProperty("role", "caption")
            note.setWordWrap(True)
            self._diag_box.addWidget(note)
            return
        d = surface.diagnostics
        header = QLabel(f"{surface.name} — {d.triangle_count:,} triangles"
                        + (f" (×{surface.scale:g})" if surface.scale != 1.0 else ""))
        self._diag_box.addWidget(header)
        self._diag_box.addWidget(TrafficLightRow(
            "Watertight", "yes" if d.watertight else "no",
            "pass" if d.watertight else "warn"))
        self._diag_box.addWidget(TrafficLightRow(
            "Normals outward", "yes" if d.normals_outward else "check",
            "pass" if d.normals_outward else "warn"))
        if not d.watertight:
            self._diag_box.addWidget(Banner(
                f"'{surface.name}' is not watertight — fine for snapping, not as a "
                "closed region.", "warn"))


class PlaceholderStage(QWidget):
    """Empty-state panel for stages arriving in later milestones (§6.4)."""

    def __init__(self, title: str, milestone: str, parent: QWidget | None = None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        label = QLabel(f"{title} arrives in {milestone}.")
        label.setProperty("role", "caption")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addStretch()
        layout.addWidget(label)
        layout.addStretch()
