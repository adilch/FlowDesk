"""Refinement (snappyHexMesh) sub-tab of the Mesh stage (PRD §4.3.2).

Per-surface refinement table, refinement regions, locationInMesh with
Suggest, and the global controls with progressive disclosure.
"""

from __future__ import annotations

import re

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from flowdesk.app import mesh_suggest
from flowdesk.app.projects import ProjectSession
from flowdesk.model.geometry import Vec3
from flowdesk.model.mesh import (
    BoxRegion,
    CylinderRegion,
    LayerSpec,
    RefineRegion,
    SphereRegion,
    SurfaceRefinement,
)
from flowdesk.ui.components import Banner, CollapsibleGroup, UnitLineEdit, Vec3Input, make_button

SURFACE_COLUMNS = ["Surface", "Min", "Max", "Feat. lvl", "Angle °",
                   "Layers", "n", "Expansion", "Final thk", "Min thk"]
REGION_COLUMNS = ["Name", "Shape", "Dimensions", "Mode", "Level"]

_VEC = r"\(\s*([\d.eE+-]+)\s+([\d.eE+-]+)\s+([\d.eE+-]+)\s*\)"


def _fmt_vec(v: Vec3) -> str:
    return f"({v[0]:g} {v[1]:g} {v[2]:g})"


def format_region_dims(region: RefineRegion) -> str:
    g = region.geometry
    if isinstance(g, BoxRegion):
        return f"{_fmt_vec(g.min)} {_fmt_vec(g.max)}"
    if isinstance(g, SphereRegion):
        return f"{_fmt_vec(g.centre)} r {g.radius:g}"
    return f"{_fmt_vec(g.point1)} {_fmt_vec(g.point2)} r {g.radius:g}"


def parse_region_dims(shape: str, text: str):
    """Inverse of format_region_dims. Returns a region geometry or None on bad input."""
    vecs = [tuple(float(x) for x in m) for m in re.findall(_VEC, text)]
    radius_match = re.search(r"r\s+([\d.eE+-]+)", text)
    try:
        if shape == "box" and len(vecs) == 2:
            return BoxRegion(min=vecs[0], max=vecs[1])
        if shape == "sphere" and len(vecs) == 1 and radius_match:
            return SphereRegion(centre=vecs[0], radius=float(radius_match.group(1)))
        if shape == "cylinder" and len(vecs) == 2 and radius_match:
            return CylinderRegion(point1=vecs[0], point2=vecs[1],
                                  radius=float(radius_match.group(1)))
    except (ValueError, TypeError):
        return None
    return None


class SnappyPanel(QWidget):
    changed = pyqtSignal()

    def __init__(self, session: ProjectSession, parent: QWidget | None = None):
        super().__init__(parent)
        self.session = session
        # Set by MeshStage: collects the Background form into the model so
        # Suggest/regions see the domain the user typed, not stale bounds
        self.collect_background = lambda: None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 0)

        layout.addWidget(QLabel("Surface refinement"))
        self.surface_table = QTableWidget(0, len(SURFACE_COLUMNS))
        self.surface_table.setHorizontalHeaderLabels(SURFACE_COLUMNS)
        self.surface_table.setMaximumHeight(140)
        # this 10-column table is wider than the panel: let it scroll internally
        # rather than forcing a scrollbar on the whole panel
        self.surface_table.setMinimumWidth(160)
        self.surface_table.horizontalHeader().setMinimumSectionSize(44)
        layout.addWidget(self.surface_table)

        layout.addWidget(QLabel("Refinement regions"))
        region_buttons = QHBoxLayout()
        for shape in ("box", "sphere", "cylinder"):
            btn = make_button(f"+ {shape.capitalize()}")
            btn.clicked.connect(lambda _=False, s=shape: self._add_region(s))
            region_buttons.addWidget(btn)
        remove_btn = make_button("Remove selected", "ghost")
        remove_btn.clicked.connect(self._remove_region)
        region_buttons.addWidget(remove_btn)
        region_buttons.addStretch()
        layout.addLayout(region_buttons)

        self.region_table = QTableWidget(0, len(REGION_COLUMNS))
        self.region_table.setHorizontalHeaderLabels(REGION_COLUMNS)
        self.region_table.setMaximumHeight(110)
        layout.addWidget(self.region_table)

        # --- Material point ---
        grid = QGridLayout()
        grid.addWidget(QLabel("Material point"), 0, 0)
        location = self.session.model.mesh.snappy.location_in_mesh or (0.0, 0.0, 0.0)
        self.location_input = Vec3Input(unit="m", value=location)
        grid.addWidget(self.location_input, 0, 1)
        self.suggest_btn = make_button("Suggest")
        self.suggest_btn.clicked.connect(self.suggest_location)
        grid.addWidget(self.suggest_btn, 0, 2)

        g = self.session.model.mesh.snappy.globals
        grid.addWidget(QLabel("Cells between levels"), 1, 0)
        self.cells_between = QSpinBox()
        self.cells_between.setRange(1, 10)
        self.cells_between.setValue(g.cells_between_levels)
        grid.addWidget(self.cells_between, 1, 1)
        grid.addWidget(QLabel("Resolve feature angle"), 2, 0)
        self.feature_angle = UnitLineEdit(unit="deg", value=g.resolve_feature_angle,
                                          minimum=0, maximum=180)
        grid.addWidget(self.feature_angle, 2, 1)
        layout.addLayout(grid)

        advanced = CollapsibleGroup("Advanced")
        adv_grid = QGridLayout()
        adv_grid.addWidget(QLabel("Max global cells"), 0, 0)
        self.max_global = QSpinBox()
        self.max_global.setRange(1000, 2_000_000_000)
        self.max_global.setValue(g.max_global_cells)
        adv_grid.addWidget(self.max_global, 0, 1)
        adv_grid.addWidget(QLabel("Max local cells"), 1, 0)
        self.max_local = QSpinBox()
        self.max_local.setRange(1000, 2_000_000_000)
        self.max_local.setValue(g.max_local_cells)
        adv_grid.addWidget(self.max_local, 1, 1)
        adv_grid.addWidget(QLabel("Snap smoothing iters"), 2, 0)
        self.n_smooth = QSpinBox()
        self.n_smooth.setRange(0, 20)
        self.n_smooth.setValue(g.n_smooth_patch)
        adv_grid.addWidget(self.n_smooth, 2, 1)
        adv_grid.addWidget(QLabel("Snap tolerance"), 3, 0)
        self.snap_tol = UnitLineEdit(value=g.snap_tolerance, minimum=0.1)
        adv_grid.addWidget(self.snap_tol, 3, 1)
        holder = QWidget()
        holder.setLayout(adv_grid)
        advanced.body_layout.addWidget(holder)
        layout.addWidget(advanced)

        self._banner_slot = QVBoxLayout()
        layout.addLayout(self._banner_slot)
        layout.addStretch()
        self.refresh_from_model()

        # Live preview (region/marker overlays in the canvas) while editing
        self.region_table.cellChanged.connect(lambda *_a: self.changed.emit())
        self.location_input.valueChanged.connect(lambda *_a: self.changed.emit())

    # ------------------------------------------------------------------ model sync

    def refresh_from_model(self) -> None:
        # repopulating must not fire live-preview signals
        self.surface_table.blockSignals(True)
        self.region_table.blockSignals(True)
        try:
            self._refresh_tables()
        finally:
            self.surface_table.blockSignals(False)
            self.region_table.blockSignals(False)

    def _refresh_tables(self) -> None:
        snappy = self.session.model.mesh.snappy
        by_name = {r.surface: r for r in snappy.surfaces}
        surfaces = self.session.model.geometry.surfaces
        self.surface_table.setRowCount(len(surfaces))
        for row, surf in enumerate(surfaces):
            r = by_name.get(surf.name) or SurfaceRefinement(surface=surf.name)
            layers = r.layers or LayerSpec()
            values = [
                surf.name, str(r.level_min), str(r.level_max),
                str(r.feature_level if r.feature_level is not None else r.level_max),
                f"{r.included_angle:g}",
                "", str(layers.n_layers), f"{layers.expansion_ratio:g}",
                f"{layers.final_layer_thickness:g}", f"{layers.min_thickness:g}",
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                if col == 0:
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if col == 5:
                    item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                    item.setCheckState(Qt.CheckState.Checked if r.layers
                                       else Qt.CheckState.Unchecked)
                self.surface_table.setItem(row, col, item)

        self.region_table.setRowCount(len(snappy.regions))
        for row, region in enumerate(snappy.regions):
            cells = [region.name, region.geometry.shape, format_region_dims(region),
                     region.mode, str(region.level)]
            for col, value in enumerate(cells):
                item = QTableWidgetItem(value)
                if col == 1:
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.region_table.setItem(row, col, item)


    def collect_into_model(self) -> list[str]:
        """Table -> model. Returns human-readable problems (shown as banners)."""
        problems: list[str] = []
        snappy = self.session.model.mesh.snappy

        refinements: list[SurfaceRefinement] = []
        for row in range(self.surface_table.rowCount()):
            def text(col: int, row=row) -> str:
                item = self.surface_table.item(row, col)
                return item.text().strip() if item else ""

            name = text(0)
            try:
                layers_on = (self.surface_table.item(row, 5).checkState()
                             == Qt.CheckState.Checked)
                layers = LayerSpec(
                    n_layers=int(text(6) or 3),
                    expansion_ratio=float(text(7) or 1.2),
                    final_layer_thickness=float(text(8) or 0.3),
                    min_thickness=float(text(9) or 0.1),
                ) if layers_on else None
                refinements.append(SurfaceRefinement(
                    surface=name,
                    level_min=int(text(1) or 2),
                    level_max=int(text(2) or 3),
                    feature_level=int(text(3)) if text(3) else None,
                    included_angle=float(text(4) or 150),
                    layers=layers,
                ))
            except ValueError as exc:
                problems.append(f"Surface '{name}': {exc}")
        snappy.surfaces = refinements

        regions: list[RefineRegion] = []
        for row in range(self.region_table.rowCount()):
            def text(col: int, row=row) -> str:
                item = self.region_table.item(row, col)
                return item.text().strip() if item else ""

            shape = text(1)
            geometry = parse_region_dims(shape, text(2))
            if geometry is None:
                problems.append(
                    f"Region '{text(0)}': could not parse dimensions '{text(2)}' "
                    f"for shape {shape}.")
                continue
            mode = text(3) if text(3) in ("inside", "outside") else "inside"
            try:
                regions.append(RefineRegion(name=text(0) or f"region{row}",
                                            geometry=geometry, mode=mode,
                                            level=int(text(4) or 2)))
            except ValueError as exc:
                problems.append(f"Region '{text(0)}': {exc}")
        snappy.regions = regions

        snappy.location_in_mesh = self.location_input.value()
        g = snappy.globals
        g.cells_between_levels = self.cells_between.value()
        g.resolve_feature_angle = self.feature_angle.value()
        g.max_global_cells = self.max_global.value()
        g.max_local_cells = self.max_local.value()
        g.n_smooth_patch = self.n_smooth.value()
        g.snap_tolerance = self.snap_tol.value()
        return problems

    # ------------------------------------------------------------------ actions

    def suggest_location(self) -> None:
        self._clear_banners()
        self.collect_background()  # un-applied domain bounds count too
        self.collect_into_model()
        point = mesh_suggest.suggest_location_in_mesh(
            self.session.model, self.session.case_dir)
        if point is None:
            self._add_banner(
                "No good material point found automatically — the domain may be "
                "fully blocked by geometry. → Pick one manually in open fluid.",
                "warn")
            return
        self.location_input.set_values(point)
        self.session.model.mesh.snappy.location_in_mesh = point
        self.changed.emit()

    def diagnose_location(self) -> str | None:
        point = self.location_input.value()
        return mesh_suggest.location_diagnosis(
            self.session.model, self.session.case_dir, point)

    def _add_region(self, shape: str) -> None:
        self.collect_background()  # default region size derives from the domain
        block = self.session.model.mesh.block
        lo, hi = block.bounds_min, block.bounds_max
        center = tuple((a + b) / 2 for a, b in zip(lo, hi, strict=True))
        size = min(high - low for low, high in zip(lo, hi, strict=True)) / 4
        n = self.region_table.rowCount()
        if shape == "box":
            geometry = BoxRegion(
                min=tuple(c - size for c in center),
                max=tuple(c + size for c in center))
        elif shape == "sphere":
            geometry = SphereRegion(centre=center, radius=size)
        else:
            geometry = CylinderRegion(
                point1=(center[0], center[1], center[2] - size),
                point2=(center[0], center[1], center[2] + size), radius=size / 2)
        region = RefineRegion(name=f"refine{shape.capitalize()}{n}", geometry=geometry)
        self.session.model.mesh.snappy.regions.append(region)
        self.refresh_from_model()
        self.changed.emit()

    def _remove_region(self) -> None:
        row = self.region_table.currentRow()
        regions = self.session.model.mesh.snappy.regions
        if 0 <= row < len(regions):
            del regions[row]
            self.refresh_from_model()
            self.changed.emit()

    # ------------------------------------------------------------------ banners

    def _add_banner(self, message: str, severity: str) -> None:
        self._banner_slot.addWidget(Banner(message, severity))

    def _clear_banners(self) -> None:
        while self._banner_slot.count():
            item = self._banner_slot.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
