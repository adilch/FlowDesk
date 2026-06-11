"""Results stage (PRD §4.8): time selector, slice/contour views, glyphs, probe,
screenshot, ParaView handoff."""

from __future__ import annotations

import webbrowser
from pathlib import Path

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from flowdesk.app import results_io
from flowdesk.app.projects import ProjectSession
from flowdesk.model.findings import Stage
from flowdesk.platform import environment as env_probe
from flowdesk.ui.components import (
    Banner,
    SegmentedControl,
    UnitLineEdit,
    Vec3Input,
    make_button,
)
from flowdesk.ui.theme import COLORS, PANEL_PADDING, RIGHT_PANEL_WIDTH


class ResultsStage(QWidget):
    model_changed = pyqtSignal(Stage)

    def __init__(self, session: ProjectSession, viewer, parent: QWidget | None = None):
        super().__init__(parent)
        self.session = session
        self.viewer = viewer  # shared ViewerWidget (shell moves it here)
        self.results: results_io.LoadedResults | None = None
        self._paraview = env_probe.find_paraview()

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.viewer_slot = QVBoxLayout()
        layout.addLayout(self.viewer_slot, stretch=1)

        panel = QWidget()
        panel.setFixedWidth(RIGHT_PANEL_WIDTH + 40)
        form = QVBoxLayout(panel)
        form.setContentsMargins(PANEL_PADDING, PANEL_PADDING, PANEL_PADDING,
                                PANEL_PADDING)
        layout.addWidget(panel)

        title = QLabel("Results")
        title.setProperty("role", "title")
        form.addWidget(title)

        # Time selector (§4.8: dropdown + first/prev/next/last, no animation)
        time_row = QHBoxLayout()
        self.time_combo = QComboBox()
        self.time_combo.currentTextChanged.connect(lambda _t: self._reload())
        for label, step in (("⏮", "first"), ("◀", "prev"), ("▶", "next"), ("⏭", "last")):
            btn = make_button(label, "ghost")
            btn.setFixedWidth(36)
            btn.clicked.connect(lambda _=False, s=step: self._step_time(s))
            time_row.addWidget(btn)
        time_row.insertWidget(0, self.time_combo, stretch=1)
        form.addLayout(time_row)

        grid = QGridLayout()
        grid.addWidget(QLabel("View"), 0, 0)
        self.mode_seg = SegmentedControl(["Slice", "Surface contours"])
        self.mode_seg.selectionChanged.connect(lambda _i: self.render())
        grid.addWidget(self.mode_seg, 0, 1)
        grid.addWidget(QLabel("Field"), 1, 0)
        self.field_combo = QComboBox()
        self.field_combo.currentTextChanged.connect(lambda _t: self.render())
        grid.addWidget(self.field_combo, 1, 1)
        grid.addWidget(QLabel("Colormap"), 2, 0)
        self.cmap_combo = QComboBox()
        self.cmap_combo.addItems(list(results_io.COLORMAPS))
        self.cmap_combo.currentTextChanged.connect(lambda _t: self.render())
        grid.addWidget(self.cmap_combo, 2, 1)
        grid.addWidget(QLabel("Slice normal"), 3, 0)
        self.normal_seg = SegmentedControl(["X", "Y", "Z"], current=2)
        self.normal_seg.selectionChanged.connect(lambda _i: self.render())
        grid.addWidget(self.normal_seg, 3, 1)
        grid.addWidget(QLabel("Slice origin"), 4, 0)
        self.origin = Vec3Input(unit="m", value=self._domain_center())
        self.origin.valueChanged.connect(lambda *_a: self.render())
        grid.addWidget(self.origin, 4, 1)
        form.addLayout(grid)

        glyph_row = QHBoxLayout()
        self.glyphs_chk = QCheckBox("Vector glyphs")
        self.glyphs_chk.toggled.connect(lambda _c: self.render())
        self.glyph_every = QSpinBox()
        self.glyph_every.setRange(1, 1000)
        self.glyph_every.setValue(20)
        self.glyph_scale = UnitLineEdit(value=0.1, minimum=1e-9)
        glyph_row.addWidget(self.glyphs_chk)
        glyph_row.addWidget(QLabel("every"))
        glyph_row.addWidget(self.glyph_every)
        glyph_row.addWidget(QLabel("scale"))
        glyph_row.addWidget(self.glyph_scale)
        form.addLayout(glyph_row)

        # Probe (§4.8)
        probe_title = QLabel("PROBE")
        probe_title.setProperty("role", "section")
        form.addWidget(probe_title)
        probe_row = QHBoxLayout()
        self.probe_point = Vec3Input(unit="m", value=self._domain_center())
        probe_btn = make_button("Probe")
        probe_btn.clicked.connect(self._probe)
        probe_row.addWidget(self.probe_point)
        probe_row.addWidget(probe_btn)
        form.addLayout(probe_row)
        self.probe_readout = QLabel("")
        self.probe_readout.setProperty("role", "caption")
        self.probe_readout.setWordWrap(True)
        form.addWidget(self.probe_readout)

        # Screenshot + ParaView
        action_row = QHBoxLayout()
        self.shot_scale = QComboBox()
        self.shot_scale.addItems(["1×", "2×", "4×"])
        self.shot_scale.setCurrentText("2×")
        shot_btn = make_button("Screenshot…")
        shot_btn.clicked.connect(self._screenshot)
        self.paraview_btn = make_button("Open in ParaView", "primary")
        self.paraview_btn.clicked.connect(self._open_paraview)
        action_row.addWidget(self.shot_scale)
        action_row.addWidget(shot_btn)
        action_row.addWidget(self.paraview_btn)
        form.addLayout(action_row)

        self._banner_slot = QVBoxLayout()
        form.addLayout(self._banner_slot)
        form.addStretch()

    # ------------------------------------------------------------------ loading

    def _domain_center(self):
        block = self.session.model.mesh.block
        return tuple((lo + hi) / 2 for lo, hi in
                     zip(block.bounds_min, block.bounds_max, strict=True))

    def refresh(self) -> None:
        """Re-list times and load the latest (called on stage entry / run end)."""
        self._clear_banners()
        try:
            times = results_io.list_time_values(self.session.case_dir)
        except Exception as exc:
            self._add_banner(f"No readable results yet ({exc}).", "info")
            return
        self.time_combo.blockSignals(True)
        self.time_combo.clear()
        self.time_combo.addItems([f"{t:g}" for t in times])
        if times:
            self.time_combo.setCurrentIndex(len(times) - 1)
        self.time_combo.blockSignals(False)
        self._reload()

    def _reload(self) -> None:
        text = self.time_combo.currentText()
        if not text:
            return
        self._clear_banners()
        try:
            self.results = results_io.load(self.session.case_dir, float(text))
        except Exception as exc:
            self._add_banner(f"Could not load results: {exc}", "error")
            return
        guard = results_io.preview_guard(self.results.n_cells)
        if guard:
            self._add_banner(guard, "warn" if "moment" in guard else "error")
            if self.results.n_cells > results_io.PREVIEW_DISABLED_CELLS:
                self.results = None
                return
        current_field = self.field_combo.currentText()
        fields = self.results.available_fields()
        self.field_combo.blockSignals(True)
        self.field_combo.clear()
        self.field_combo.addItems(fields)
        if current_field in fields:
            self.field_combo.setCurrentText(current_field)
        self.field_combo.blockSignals(False)
        self.render()

    def _step_time(self, step: str) -> None:
        count = self.time_combo.count()
        if count == 0:
            return
        index = {"first": 0, "prev": max(0, self.time_combo.currentIndex() - 1),
                 "next": min(count - 1, self.time_combo.currentIndex() + 1),
                 "last": count - 1}[step]
        self.time_combo.setCurrentIndex(index)

    # ------------------------------------------------------------------ rendering

    def render(self) -> None:
        if self.results is None:
            return
        field = self.field_combo.currentText()
        if not field:
            return
        self._clear_banners()
        if field == "p":
            self._add_banner(
                "kinematic pressure (p/ρ, m²/s²) — multiply by ρ for Pa", "warn")
        elif field == "p_rgh":
            self._add_banner(
                "p_rgh is p − ρgh in Pa (interFoam) — true pressure minus the "
                "hydrostatic column", "info")
        cmap = results_io.COLORMAPS[self.cmap_combo.currentText()]
        plotter = self.viewer.plotter
        plotter.clear()

        try:
            if self.mode_seg.current() == 0:  # slice
                normal = ["x", "y", "z"][self.normal_seg.current()]
                sliced = results_io.slice_plane(self.results, self.origin.value(),
                                                normal)
                key, _ = results_io.scalar_array(sliced, field)
                plotter.add_mesh(sliced, scalars=key, cmap=cmap,
                                 scalar_bar_args={"title": field})
                if self.glyphs_chk.isChecked():
                    glyphs = results_io.glyphs_on_slice(
                        sliced, self.glyph_every.value(), self.glyph_scale.value())
                    if glyphs is not None:
                        plotter.add_mesh(glyphs, color=COLORS["text-1"])
            else:  # surface contours on patches
                if self.results.boundaries is None:
                    self._add_banner("No boundary data in results.", "info")
                    return
                names = self.results.boundaries.keys()
                for name in names:
                    patch = self.results.boundaries[name]
                    try:
                        key, _ = results_io.scalar_array(patch, field)
                        plotter.add_mesh(patch, scalars=key, cmap=cmap)
                    except KeyError:
                        plotter.add_mesh(patch, color=COLORS["text-2"], opacity=0.3)
            plotter.reset_camera()
        except Exception as exc:
            self._add_banner(f"Preview failed: {exc} — Open in ParaView for the "
                             "full picture.", "error")

    # ------------------------------------------------------------------ actions

    def _probe(self) -> None:
        if self.results is None:
            return
        values = results_io.probe_point(self.results, self.probe_point.value())
        if not values:
            self.probe_readout.setText("No data at that point (outside the mesh?)")
            return
        parts = []
        for name, value in sorted(values.items()):
            if isinstance(value, tuple):
                parts.append(f"{name} = ({', '.join(f'{v:.4g}' for v in value)})")
            else:
                parts.append(f"{name} = {value:.4g}")
        self.probe_readout.setText("   ".join(parts))

    def _screenshot(self) -> None:
        path_str, _ = QFileDialog.getSaveFileName(
            self, "Save screenshot",
            str(Path.home() / f"{self.session.model.meta.name}.png"), "PNG (*.png)")
        if not path_str:
            return
        scale = {"1×": 1, "2×": 2, "4×": 4}[self.shot_scale.currentText()]
        self.screenshot_to(Path(path_str), scale)

    def screenshot_to(self, path: Path, scale: int = 2) -> Path:
        """PNG with title block (project, field, time) - §4.8."""
        plotter = self.viewer.plotter
        title = (f"{self.session.model.meta.name} — {self.field_combo.currentText()}"
                 f" — t={self.time_combo.currentText()}")
        actor = plotter.add_text(title, font_size=10, color=COLORS["text-1"])
        try:
            plotter.screenshot(str(path), scale=scale)
        finally:
            plotter.remove_actor(actor)
        return path

    def _open_paraview(self) -> None:
        self._paraview = self._paraview or env_probe.find_paraview()
        if self._paraview is None:
            self._add_banner(
                "ParaView is free — download it, then point FlowDesk at "
                "paraview.exe in Settings. Opening the download page.", "info")
            webbrowser.open(env_probe.PARAVIEW_DOWNLOAD_URL)
            return
        env_probe.launch_paraview(self._paraview, self.session.case_dir / "case.foam")

    # ------------------------------------------------------------------ banners

    def _add_banner(self, message: str, severity: str) -> None:
        self._banner_slot.addWidget(Banner(message, severity))

    def _clear_banners(self) -> None:
        while self._banner_slot.count():
            item = self._banner_slot.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
