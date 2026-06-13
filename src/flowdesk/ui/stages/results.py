"""Results stage (PRD §4.8): time selector, slice/contour views, glyphs, probe,
screenshot, ParaView handoff."""

from __future__ import annotations

import webbrowser
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QSlider,
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
    split_viewer_panel,
)
from flowdesk.ui.theme import COLORS, PANEL_PADDING


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

        panel = QWidget()
        form = QVBoxLayout(panel)
        form.setContentsMargins(PANEL_PADDING, PANEL_PADDING, PANEL_PADDING,
                                PANEL_PADDING)
        split_viewer_panel(layout, self.viewer_slot, panel)

        title = QLabel("Results")
        title.setProperty("role", "title")
        form.addWidget(title)

        # Time selector + animation (play through the saved time steps)
        time_row = QHBoxLayout()
        self.time_combo = QComboBox()
        self.time_combo.currentTextChanged.connect(lambda _t: self._reload())
        time_row.addWidget(self.time_combo, stretch=1)
        for label, step in (("⏮", "first"), ("◀", "prev"), ("▶", "next"), ("⏭", "last")):
            btn = make_button(label, "ghost")
            btn.setFixedWidth(34)
            btn.clicked.connect(lambda _=False, s=step: self._step_time(s))
            time_row.addWidget(btn)
        self.play_btn = make_button("▶", "secondary")
        self.play_btn.setFixedWidth(34)
        self.play_btn.setToolTip("Play / pause through the time steps")
        self.play_btn.clicked.connect(self._toggle_play)
        time_row.addWidget(self.play_btn)
        form.addLayout(time_row)

        speed_row = QHBoxLayout()
        self.loop_chk = QCheckBox("Loop")
        self.loop_chk.setChecked(True)
        speed_row.addWidget(QLabel("Speed"))
        self.speed_slider = QSlider(Qt.Orientation.Horizontal)
        self.speed_slider.setRange(1, 20)  # frames per second
        self.speed_slider.setValue(4)
        self.speed_slider.valueChanged.connect(self._on_speed_changed)
        speed_row.addWidget(self.speed_slider, stretch=1)
        speed_row.addWidget(self.loop_chk)
        form.addLayout(speed_row)

        self._anim_timer = QTimer(self)
        self._anim_timer.setInterval(250)
        self._anim_timer.timeout.connect(self._advance_frame)

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
        self.normal_seg = SegmentedControl(["X", "Y", "Z"],
                                           current=self._default_normal_index())
        self.normal_seg.selectionChanged.connect(lambda _i: self.render())
        grid.addWidget(self.normal_seg, 3, 1)
        grid.addWidget(QLabel("Slice origin"), 4, 0)
        self.origin = Vec3Input(unit="m", value=self._domain_center())
        self.origin.valueChanged.connect(lambda *_a: self.render())
        grid.addWidget(self.origin, 4, 1)
        form.addLayout(grid)

        # Color range filter: auto (per-frame) or a fixed user range, with reset
        range_title = QLabel("COLOR RANGE")
        range_title.setProperty("role", "section")
        form.addWidget(range_title)
        self.auto_range_chk = QCheckBox("Auto (fit to each frame)")
        self.auto_range_chk.setChecked(True)
        self.auto_range_chk.toggled.connect(self._on_auto_range)
        form.addWidget(self.auto_range_chk)
        range_row = QHBoxLayout()
        range_row.addWidget(QLabel("min"))
        self.range_min = UnitLineEdit(value=0.0)
        self.range_min.valueChanged.connect(lambda *_a: self.render())
        range_row.addWidget(self.range_min)
        range_row.addWidget(QLabel("max"))
        self.range_max = UnitLineEdit(value=1.0)
        self.range_max.valueChanged.connect(lambda *_a: self.render())
        range_row.addWidget(self.range_max)
        self.reset_range_btn = make_button("Reset")
        self.reset_range_btn.setToolTip("Fill min/max from this field's data range")
        self.reset_range_btn.clicked.connect(self._reset_range)
        range_row.addWidget(self.reset_range_btn)
        self._range_row = range_row
        form.addLayout(range_row)
        self._set_range_enabled(False)

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

    def _default_normal_index(self) -> int:
        """A default slice that actually shows the flow:
        - quasi-2D case (an axis with <=3 cells): slice across the thin axis,
          i.e. the 2D plane itself;
        - free surface: a vertical cut (normal Y) through the domain - a
          horizontal default would slice the air above the water;
        - otherwise: Z (mid-depth horizontal cut)."""
        cells = self.session.model.mesh.block.cells
        thin = [i for i, c in enumerate(cells) if c <= 3]
        if thin:
            return thin[0]
        if self.session.model.physics.free_surface is not None:
            return 1
        return 2

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

    # ------------------------------------------------------------------ animation

    def _toggle_play(self) -> None:
        if self._anim_timer.isActive():
            self._stop_play()
        elif self.time_combo.count() > 1:
            self.play_btn.setText("⏸")
            self._anim_timer.start()

    def _stop_play(self) -> None:
        self._anim_timer.stop()
        self.play_btn.setText("▶")

    def _advance_frame(self) -> None:
        count = self.time_combo.count()
        if count <= 1:
            self._stop_play()
            return
        nxt = self.time_combo.currentIndex() + 1
        if nxt >= count:
            if not self.loop_chk.isChecked():
                self._stop_play()
                return
            nxt = 0
        self.time_combo.setCurrentIndex(nxt)

    def _on_speed_changed(self, fps: int) -> None:
        self._anim_timer.setInterval(int(1000 / max(1, fps)))

    def hideEvent(self, event) -> None:  # noqa: N802 (Qt override)
        self._stop_play()  # don't keep animating when the stage isn't visible
        super().hideEvent(event)

    # ------------------------------------------------------------------ color range

    def _set_range_enabled(self, on: bool) -> None:
        for i in range(self._range_row.count()):
            w = self._range_row.itemAt(i).widget()
            if w is not None:
                w.setEnabled(on)

    def _on_auto_range(self, auto: bool) -> None:
        self._set_range_enabled(not auto)
        if not auto and self.results is not None:
            self._reset_range()  # seed manual fields from the data on first switch
        else:
            self.render()

    def _reset_range(self) -> None:
        if self.results is None:
            return
        rng = results_io.field_range(self.results, self.field_combo.currentText())
        if rng is not None:
            self.range_min.set_value(rng[0])
            self.range_max.set_value(rng[1])
        self.render()

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
        clim = None if self.auto_range_chk.isChecked() else \
            [self.range_min.value(), self.range_max.value()]
        plotter = self.viewer.plotter
        plotter.clear()

        try:
            if self.mode_seg.current() == 0:  # slice
                normal = ["x", "y", "z"][self.normal_seg.current()]
                sliced = results_io.slice_plane(self.results, self.origin.value(),
                                                normal)
                if sliced.n_cells == 0:
                    block = self.session.model.mesh.block
                    self._add_banner(
                        f"The slice plane missed the mesh — nothing to show. → "
                        f"Move the slice origin inside the domain "
                        f"({block.bounds_min} … {block.bounds_max}).", "error")
                    return
                key, _ = results_io.scalar_array(sliced, field)
                plotter.add_mesh(sliced, scalars=key, cmap=cmap, clim=clim,
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
                        plotter.add_mesh(patch, scalars=key, cmap=cmap, clim=clim)
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
