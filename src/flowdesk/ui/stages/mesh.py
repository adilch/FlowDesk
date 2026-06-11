"""Mesh stage (PRD §4.3): Background (blockMesh) + Refinement (snappy) sub-tabs,
persistent quality report, Generate Mesh pipeline, mesh preview hook."""

from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from flowdesk.app import mesh_suggest
from flowdesk.app.projects import ProjectSession
from flowdesk.app.staleness import patch_diff_summary
from flowdesk.exec.meshing import (
    apply_mesh_result,
    mesh_pipeline,
    projected_cell_note,
)
from flowdesk.exec.parsers import CheckMeshParser, SnappyLayerParser, verdict
from flowdesk.exec.pipeline import PipelineRunner, PipelineState
from flowdesk.model.case import MESH_SCOPE, InvalidCaseError
from flowdesk.model.findings import Stage
from flowdesk.platform.commands import Environment
from flowdesk.ui.components import Banner, TrafficLightRow, Vec3Input, make_button
from flowdesk.ui.stages.snappy_panel import SnappyPanel
from flowdesk.ui.theme import PANEL_PADDING, RIGHT_PANEL_WIDTH


class BackgroundPanel(QWidget):
    """The blockMesh form (§4.3.1)."""

    def __init__(self, session: ProjectSession, parent: QWidget | None = None):
        super().__init__(parent)
        self.session = session
        form = QVBoxLayout(self)
        form.setContentsMargins(0, 8, 0, 0)

        block = session.model.mesh.block
        grid = QGridLayout()
        grid.addWidget(QLabel("Domain min"), 0, 0)
        self.bounds_min = Vec3Input(unit="m", value=block.bounds_min)
        grid.addWidget(self.bounds_min, 0, 1)
        grid.addWidget(QLabel("Domain max"), 1, 0)
        self.bounds_max = Vec3Input(unit="m", value=block.bounds_max)
        grid.addWidget(self.bounds_max, 1, 1)
        grid.addWidget(QLabel("Cells (nx, ny, nz)"), 2, 0)
        cells_row = QHBoxLayout()
        self.cells: list[QSpinBox] = []
        for i in range(3):
            spin = QSpinBox()
            spin.setRange(1, 10_000)
            spin.setValue(block.cells[i])
            self.cells.append(spin)
            cells_row.addWidget(spin)
        holder = QWidget()
        holder.setLayout(cells_row)
        grid.addWidget(holder, 2, 1)
        form.addLayout(grid)

        self.fit_btn = make_button("Fit to geometry")
        self.fit_btn.setToolTip(
            "Bounding box of imported surfaces + 1× diagonal padding; "
            "cell size = diagonal / 40 (§4.3.1 defaults)")
        self.fit_btn.clicked.connect(self.fit_to_geometry)
        form.addWidget(self.fit_btn)

        self.cell_estimate = QLabel("")
        self.cell_estimate.setProperty("role", "caption")
        form.addWidget(self.cell_estimate)
        for spin in self.cells:
            spin.valueChanged.connect(self._update_estimate)
        self._update_estimate()

        form.addWidget(QLabel("Patches"))
        self.patch_table = QTableWidget(0, 3)
        self.patch_table.setHorizontalHeaderLabels(["Name", "Type", "Faces"])
        self.patch_table.setMaximumHeight(170)
        form.addWidget(self.patch_table)
        self._fill_patch_table()
        form.addStretch()

    def fit_to_geometry(self) -> None:
        suggestion = mesh_suggest.suggest_bounds(self.session.model, external=True)
        if suggestion is None:
            return
        lo, hi = suggestion
        size = mesh_suggest.suggest_cell_size(lo, hi)
        nx, ny, nz = mesh_suggest.cells_from_size(lo, hi, size)
        self.bounds_min.set_values(lo)
        self.bounds_max.set_values(hi)
        for spin, n in zip(self.cells, (nx, ny, nz), strict=True):
            spin.setValue(n)

    def _update_estimate(self) -> None:
        n = self.cells[0].value() * self.cells[1].value() * self.cells[2].value()
        self.cell_estimate.setText(f"≈ {n:,} background cells")

    def _fill_patch_table(self) -> None:
        patches = self.session.model.mesh.block.patches
        self.patch_table.setRowCount(len(patches))
        for row, p in enumerate(patches):
            self.patch_table.setItem(row, 0, QTableWidgetItem(p.name))
            self.patch_table.setItem(row, 1, QTableWidgetItem(p.type))
            self.patch_table.setItem(row, 2,
                                     QTableWidgetItem(", ".join(f.value for f in p.faces)))

    def collect(self) -> None:
        block = self.session.model.mesh.block
        block.bounds_min = self.bounds_min.value()
        block.bounds_max = self.bounds_max.value()
        block.cells = tuple(s.value() for s in self.cells)
        for row in range(self.patch_table.rowCount()):
            name_item = self.patch_table.item(row, 0)
            type_item = self.patch_table.item(row, 1)
            if name_item and row < len(block.patches):
                block.patches[row].name = name_item.text().strip()
            if type_item and row < len(block.patches):
                block.patches[row].type = type_item.text().strip()


class MeshStage(QWidget):
    model_changed = pyqtSignal(Stage)
    mesh_completed = pyqtSignal(bool)

    def __init__(self, session: ProjectSession, env: Environment,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.session = session
        self.env = env
        self.runner: PipelineRunner | None = None
        self._parser: CheckMeshParser | None = None
        self._layer_parser: SnappyLayerParser | None = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.viewer_slot = QVBoxLayout()
        layout.addLayout(self.viewer_slot, stretch=1)

        panel = QWidget()
        panel.setFixedWidth(RIGHT_PANEL_WIDTH + 160)
        form = QVBoxLayout(panel)
        form.setContentsMargins(PANEL_PADDING, PANEL_PADDING, PANEL_PADDING, PANEL_PADDING)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(panel)
        scroll.setFixedWidth(RIGHT_PANEL_WIDTH + 180)
        layout.addWidget(scroll)

        title = QLabel("Mesh")
        title.setProperty("role", "title")
        form.addWidget(title)

        self.background = BackgroundPanel(session)
        self.snappy = SnappyPanel(session)
        self.tabs = QTabWidget()
        self.tabs.addTab(self.background, "Background")
        self.tabs.addTab(self.snappy, "Refinement")
        self.tabs.setTabEnabled(1, bool(session.model.geometry.surfaces))
        form.addWidget(self.tabs)

        buttons = QHBoxLayout()
        self.apply_btn = make_button("Apply")
        self.apply_btn.clicked.connect(self.apply)
        self.generate_btn = make_button("Generate Mesh", "primary")
        self.generate_btn.clicked.connect(self.generate)
        buttons.addWidget(self.apply_btn)
        buttons.addWidget(self.generate_btn)
        form.addLayout(buttons)

        self._banner_slot = QVBoxLayout()
        form.addLayout(self._banner_slot)

        quality_title = QLabel("QUALITY")
        quality_title.setProperty("role", "section")
        form.addWidget(quality_title)
        self._quality_box = QVBoxLayout()
        form.addLayout(self._quality_box)
        form.addStretch()
        self._show_quality()

    def refresh(self) -> None:
        """Called when geometry changed upstream (surfaces added/removed)."""
        self.tabs.setTabEnabled(1, bool(self.session.model.geometry.surfaces))
        self.snappy.refresh_from_model()

    # ------------------------------------------------------------------ actions

    def apply(self) -> bool:
        self._clear_banners()
        self.background.collect()
        problems = self.snappy.collect_into_model() \
            if self.session.model.geometry.surfaces else []
        for p in problems:
            self._add_banner(p, "error")
        if problems:
            return False

        if self.session.model.geometry.surfaces:
            diagnosis = self.snappy.diagnose_location()
            if diagnosis:
                self._add_banner(diagnosis + " → Mesh → Refinement → Suggest or "
                                 "pick a better point.", "error")
                return False

        try:
            # Mesh generation legally precedes BC assignment (§3.4 step 5);
            # the scoped token writes everything except the 0/ field files.
            validated = self.session.model.validated(scope=MESH_SCOPE)
        except InvalidCaseError as exc:
            for finding in exc.findings[:4]:
                self._add_banner(finding.message, "error")
            self.session.save_model()
            self.model_changed.emit(Stage.MESH)
            return False

        from flowdesk.foam import writer

        report = writer.write_case(validated, self.session.case_dir)
        for rel in report.skipped_detached:
            self._add_banner(f"{rel} is detached — not rewritten.", "warn")
        self.model_changed.emit(Stage.MESH)
        return True

    def generate(self) -> None:
        if not self.apply():
            return
        if not self.env.available:
            self._add_banner(f"OpenFOAM is not available: {self.env.detail}", "error")
            return
        note = projected_cell_note(self.session.model)
        if note:
            self._add_banner(note, "info")

        old_patches = [p.name for p in (self.session.model.mesh.result.patches
                                        if self.session.model.mesh.result else [])]
        self._parser = CheckMeshParser()
        self._layer_parser = SnappyLayerParser()
        self.runner = PipelineRunner(self)
        steps = mesh_pipeline(self.session.model, self.session.case_dir, self.env,
                              self._parser, self._layer_parser)
        self.generate_btn.setEnabled(False)
        self.runner.finished.connect(lambda ok: self._on_pipeline_done(ok, old_patches))
        self.runner.run(steps)

    def _on_pipeline_done(self, ok: bool, old_patches: list[str]) -> None:
        self.generate_btn.setEnabled(True)
        if ok and self._parser is not None:
            result = apply_mesh_result(self.session.model, self.session.case_dir,
                                       self._parser, self._layer_parser)
            self.session.save_model()
            new_patches = [p.name for p in result.patches]
            diff = patch_diff_summary(old_patches or new_patches, new_patches)
            if diff:
                self.session.staleness.mark_applied(Stage.MESH, diff)
            self.session.staleness.clear(Stage.MESH)
        elif not ok and self.runner is not None \
                and self.runner.state is not PipelineState.CANCELLED:
            self._add_banner(
                "Mesh pipeline failed — the full OpenFOAM output above is "
                "authoritative. → Check the run log in the drawer.", "error")
        self._show_quality()
        self.model_changed.emit(Stage.MESH)
        self.mesh_completed.emit(ok)

    # ------------------------------------------------------------------ quality panel

    def _show_quality(self) -> None:
        while self._quality_box.count():
            item = self._quality_box.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        result = self.session.model.mesh.result
        if result is None:
            note = QLabel("Not meshed yet.")
            note.setProperty("role", "caption")
            self._quality_box.addWidget(note)
            return

        q = result.quality
        self._quality_box.addWidget(QLabel(f"{result.cell_count:,} cells"))
        rows = [
            ("Max non-orthogonality", q.max_non_ortho, "max_non_ortho"),
            ("Max skewness", q.max_skewness, "max_skewness"),
            ("Max aspect ratio", q.max_aspect_ratio, "max_aspect_ratio"),
        ]
        for label, value, metric in rows:
            v = verdict(metric, value)
            display = f"{value:g}" if value is not None else "—"
            self._quality_box.addWidget(TrafficLightRow(
                label, display, v if v != "unknown" else "warn"))
        self._quality_box.addWidget(TrafficLightRow(
            "Negative-volume cells", str(q.negative_volume_cells),
            "pass" if q.negative_volume_cells == 0 else "fail"))
        self._quality_box.addWidget(TrafficLightRow(
            "checkMesh verdict", "Mesh OK" if q.mesh_ok else "failed checks",
            "pass" if q.mesh_ok else "fail"))

        # §4.3.3: layer coverage per surface, warn < 70% of requested layers
        requested = {r.surface: r.layers.n_layers
                     for r in self.session.model.mesh.snappy.surfaces if r.layers}
        for cov in result.layer_coverage:
            want = requested.get(cov.surface, 0)
            fraction = cov.layers_achieved / want if want else 1.0
            self._quality_box.addWidget(TrafficLightRow(
                f"Layers on {cov.surface}",
                f"{cov.layers_achieved:g}/{want} layers, "
                f"{cov.thickness_overall:g} m overall",
                "pass" if fraction >= 0.7 else "warn"))

        patches = ", ".join(f"{p.name} ({p.n_faces})" for p in result.patches)
        patch_label = QLabel(f"Patches: {patches}")
        patch_label.setProperty("role", "caption")
        patch_label.setWordWrap(True)
        self._quality_box.addWidget(patch_label)

    # ------------------------------------------------------------------ banners

    def _add_banner(self, message: str, severity: str) -> None:
        self._banner_slot.addWidget(Banner(message, severity))

    def _clear_banners(self) -> None:
        while self._banner_slot.count():
            item = self._banner_slot.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
