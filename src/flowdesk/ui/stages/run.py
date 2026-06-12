"""Run stage (PRD §4.7): settings, parallel execution, live residual plot,
Courant/continuity readouts, stop/kill, failure panel with explanations."""

from __future__ import annotations

import time

import pyqtgraph as pg
from PyQt6.QtCore import QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from flowdesk.app.projects import ProjectSession
from flowdesk.exec import errors as error_explain
from flowdesk.exec.solver import RunState, SolverSupervisor
from flowdesk.model.case import InvalidCaseError
from flowdesk.model.findings import Stage
from flowdesk.model.numerics import Preset, RunMode
from flowdesk.platform.commands import Environment
from flowdesk.ui.components import Banner, SegmentedControl, make_button
from flowdesk.ui.theme import COLORS, PANEL_PADDING, RIGHT_PANEL_WIDTH

SERIES_COLORS = ["#3D9BE9", "#E0A93E", "#3FB970", "#E25D5D", "#8B6FE8", "#56B4E9"]


class RunStage(QWidget):
    model_changed = pyqtSignal(Stage)
    run_finished = pyqtSignal(bool)

    def __init__(self, session: ProjectSession, env: Environment,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.session = session
        self.env = env
        self.supervisor: SolverSupervisor | None = None
        self._curves: dict[str, pg.PlotDataItem] = {}
        self._run_started_at: float | None = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # --- center: live monitoring ---
        center = QVBoxLayout()
        center.setContentsMargins(PANEL_PADDING, PANEL_PADDING, 0, PANEL_PADDING)
        pg.setConfigOption("background", COLORS["bg-0"])
        pg.setConfigOption("foreground", COLORS["text-2"])
        self.plot = pg.PlotWidget(title="Residuals")
        self.plot.setLogMode(y=True)
        self.plot.setLabel("bottom", "iteration / time")
        self.plot.addLegend(offset=(10, 10))
        self.plot.showGrid(x=True, y=True, alpha=0.2)
        center.addWidget(self.plot, stretch=1)

        status_row = QHBoxLayout()
        self.state_label = QLabel("Idle")
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setFormat("%p%")
        self.eta_label = QLabel("")
        self.eta_label.setProperty("role", "caption")
        self.courant_label = QLabel("")
        self.courant_label.setProperty("role", "caption")
        self.continuity_label = QLabel("")
        self.continuity_label.setProperty("role", "caption")
        status_row.addWidget(self.state_label)
        status_row.addWidget(self.progress, stretch=1)
        status_row.addWidget(self.eta_label)
        status_row.addWidget(self.courant_label)
        status_row.addWidget(self.continuity_label)
        center.addLayout(status_row)

        self.error_panel = QPlainTextEdit()
        self.error_panel.setReadOnly(True)
        self.error_panel.setProperty("role", "log")
        self.error_panel.setVisible(False)
        self.error_panel.setMaximumHeight(180)
        center.addWidget(self.error_panel)
        self._explanation_slot = QVBoxLayout()
        center.addLayout(self._explanation_slot)
        layout.addLayout(center, stretch=1)

        # --- right: settings ---
        panel = QWidget()
        panel.setFixedWidth(RIGHT_PANEL_WIDTH)
        form = QVBoxLayout(panel)
        form.setContentsMargins(PANEL_PADDING, PANEL_PADDING, PANEL_PADDING,
                                PANEL_PADDING)
        layout.addWidget(panel)

        title = QLabel("Run")
        title.setProperty("role", "title")
        form.addWidget(title)

        run_model = session.model.run
        grid = QGridLayout()
        grid.addWidget(QLabel("Mode"), 0, 0)
        self.mode_seg = SegmentedControl(
            ["Serial", "Parallel"],
            current=0 if run_model.mode is RunMode.SERIAL else 1)
        grid.addWidget(self.mode_seg, 0, 1)
        grid.addWidget(QLabel("Cores"), 1, 0)
        self.cores = QSpinBox()
        self.cores.setRange(1, 256)
        self.cores.setValue(run_model.cores)
        grid.addWidget(self.cores, 1, 1)
        grid.addWidget(QLabel("Decomposition"), 2, 0)
        self.decomp = QComboBox()
        self.decomp.addItems(["scotch", "hierarchical", "simple"])
        self.decomp.setCurrentText(run_model.decomposition)
        grid.addWidget(self.decomp, 2, 1)
        grid.addWidget(QLabel("Max iterations / end time"), 3, 0)
        self.max_iter = QSpinBox()
        self.max_iter.setRange(1, 1_000_000)
        self.max_iter.setValue(run_model.max_iterations)
        grid.addWidget(self.max_iter, 3, 1)
        form.addLayout(grid)

        # --- Write controls (controlDict, §4.7) ---
        write_title = QLabel("WRITE CONTROLS (controlDict)")
        write_title.setProperty("role", "section")
        form.addWidget(write_title)
        wgrid = QGridLayout()
        steady = session.model.physics.is_steady
        self.write_every_label = QLabel(
            "Write every (iterations)" if steady else "Write every (seconds)")
        wgrid.addWidget(self.write_every_label, 0, 0)
        self.write_interval = QDoubleSpinBox()
        self.write_interval.setDecimals(0 if steady else 4)
        self.write_interval.setRange(1e-6, 1_000_000)
        self.write_interval.setValue(
            run_model.write_interval_steady if steady
            else session.model.physics.time.output_interval)
        self.write_interval.setToolTip(
            "OpenFOAM keyword: writeInterval (writeControl timeStep for steady, "
            "adjustableRunTime for transient)")
        wgrid.addWidget(self.write_interval, 0, 1)

        wgrid.addWidget(QLabel("Keep last N writes (0 = all)"), 1, 0)
        self.purge = QSpinBox()
        self.purge.setRange(0, 1000)
        self.purge.setValue(run_model.purge_write if steady
                            else run_model.purge_write_transient)
        self.purge.setToolTip("OpenFOAM keyword: purgeWrite — 0 keeps every "
                              "written time directory")
        wgrid.addWidget(self.purge, 1, 1)

        wgrid.addWidget(QLabel("Write format"), 2, 0)
        self.write_format = QComboBox()
        self.write_format.addItems(["binary", "ascii"])
        self.write_format.setCurrentText(run_model.write_format)
        wgrid.addWidget(self.write_format, 2, 1)

        wgrid.addWidget(QLabel("Write precision"), 3, 0)
        self.write_precision = QSpinBox()
        self.write_precision.setRange(6, 15)
        self.write_precision.setValue(run_model.write_precision)
        wgrid.addWidget(self.write_precision, 3, 1)
        form.addLayout(wgrid)

        self.disk_estimate = QLabel("")
        self.disk_estimate.setProperty("role", "caption")
        form.addWidget(self.disk_estimate)
        for w in (self.write_interval, self.purge, self.max_iter):
            w.valueChanged.connect(lambda _v: self._update_disk_estimate())
        self._update_disk_estimate()

        self.run_btn = make_button("Run", "primary")
        self.run_btn.clicked.connect(self.start_run)
        self.stop_btn = make_button("Stop", "secondary")
        self.stop_btn.clicked.connect(self._stop)
        self.stop_btn.setEnabled(False)
        self.kill_btn = make_button("Kill", "danger")
        self.kill_btn.clicked.connect(self._kill)
        self.kill_btn.setEnabled(False)
        buttons = QHBoxLayout()
        buttons.addWidget(self.run_btn)
        buttons.addWidget(self.stop_btn)
        buttons.addWidget(self.kill_btn)
        form.addLayout(buttons)

        self.reset_btn = make_button("Reset case & rerun…")
        self.reset_btn.setToolTip(
            "Delete results, decomposed processor dirs, and run logs (keeps the "
            "mesh, dictionaries, and initial fields), then start a fresh run")
        self.reset_btn.clicked.connect(self.reset_and_rerun)
        form.addWidget(self.reset_btn)

        self._banner_slot = QVBoxLayout()
        form.addLayout(self._banner_slot)
        form.addStretch()

        self._ui_timer = QTimer(self)
        self._ui_timer.setInterval(500)  # plot refresh <= 2 Hz; data arrives at tail rate
        self._ui_timer.timeout.connect(self._refresh_monitoring)

    def refresh_write_controls(self) -> None:
        """Re-sync write controls to the current time treatment. Without this,
        a steady 'every 200 iterations' leaks into a transient run as 'every
        200 seconds' - which, past a short endTime, writes zero results."""
        steady = self.session.model.physics.is_steady
        self.write_every_label.setText(
            "Write every (iterations)" if steady else "Write every (seconds)")
        self.write_interval.blockSignals(True)
        self.write_interval.setDecimals(0 if steady else 4)
        self.write_interval.setValue(
            self.session.model.run.write_interval_steady if steady
            else self.session.model.physics.time.output_interval)
        self.write_interval.blockSignals(False)
        self.purge.blockSignals(True)
        self.purge.setValue(self.session.model.run.purge_write if steady
                            else self.session.model.run.purge_write_transient)
        self.purge.blockSignals(False)
        self._update_disk_estimate()

    # ------------------------------------------------------------------ start

    def collect(self) -> None:
        run_model = self.session.model.run
        run_model.mode = RunMode.SERIAL if self.mode_seg.current() == 0 \
            else RunMode.PARALLEL
        run_model.cores = self.cores.value()
        run_model.decomposition = self.decomp.currentText()
        run_model.max_iterations = self.max_iter.value()
        # write controls -> the right home per time treatment
        if self.session.model.physics.is_steady:
            run_model.write_interval_steady = int(self.write_interval.value())
            run_model.purge_write = self.purge.value()
        else:
            self.session.model.physics.time.output_interval = \
                self.write_interval.value()
            run_model.purge_write_transient = self.purge.value()
        run_model.write_format = self.write_format.currentText()
        run_model.write_precision = self.write_precision.value()

    def _update_disk_estimate(self) -> None:
        """§4.7: rough projected disk use; warn above 20 GB."""
        result = self.session.model.mesh.result
        if result is None or result.cell_count == 0:
            self.disk_estimate.setText("")
            return
        if self.session.model.physics.is_steady:
            n_writes = max(1, int(self.max_iter.value()
                                  / max(1.0, self.write_interval.value())))
        else:
            end = self.session.model.physics.time.end_time
            n_writes = max(1, int(end / max(1e-9, self.write_interval.value())))
        if self.purge.value() > 0:
            n_writes = min(n_writes, self.purge.value())
        n_fields = 6  # U(3) + p + turb pair, order of magnitude
        gb = result.cell_count * n_fields * 8 * n_writes / 1e9
        warn = "  ⚠ consider purging" if gb > 20 else ""
        self.disk_estimate.setText(
            f"≈ {n_writes} write(s) ≈ {gb:.2f} GB on disk{warn}")

    def start_run(self) -> None:
        self._clear_banners()
        self.collect()
        try:
            validated = self.session.model.validated()  # full pre-run gate (§4.0)
        except InvalidCaseError as exc:
            for finding in exc.findings[:5]:
                self._add_banner(finding.message, "error")
            return
        if not self.env.available:
            self._add_banner(f"OpenFOAM is not available: {self.env.detail}", "error")
            return
        from flowdesk.app.projects import openfoam_path_problem

        path_problem = openfoam_path_problem(self.session.case_dir)
        if path_problem:
            self._add_banner(path_problem, "error")
            return
        if not (self.session.case_dir / "constant" / "polyMesh" / "points").exists():
            self._add_banner("The case is not meshed. → Mesh → Generate Mesh.",
                             "error")
            return

        from flowdesk.foam import polymesh, writer

        writer.write_case(validated, self.session.case_dir)
        polymesh.sync_boundary_types(self.session.model, self.session.case_dir)
        first_order = self._prepare_first_order_start()
        self.session.save_model()

        self._reset_monitoring()
        self.supervisor = SolverSupervisor(self.session.case_dir, self.env, self)
        self._wire_supervisor()
        self.supervisor.start(self.session.model, first_order)
        self._run_started_at = time.monotonic()
        self._ui_timer.start()
        self.run_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.kill_btn.setEnabled(True)
        self.model_changed.emit(Stage.RUN)

    def _prepare_first_order_start(self) -> int | None:
        """§4.6 assist: write the upwind leg-1 fvSchemes + stash the target."""
        n = self.session.model.numerics
        if not (n.first_order_start.enabled and self.session.model.physics.is_steady):
            return None
        if "upwind" in n.div_u:
            return None  # already first-order; nothing to switch
        from flowdesk.foam import generators
        from flowdesk.model.numerics import make_preset

        target_text = generators.fv_schemes(self.session.model)
        (self.session.case_dir / "system" / "fvSchemes.flowdesk-target").write_text(
            target_text, encoding="utf-8", newline="\n")
        upwind_model = self.session.model.model_copy(deep=True)
        upwind_model.numerics = make_preset(Preset.ROBUST)
        upwind_text = generators.fv_schemes(upwind_model)
        (self.session.case_dir / "system" / "fvSchemes").write_text(
            upwind_text, encoding="utf-8", newline="\n")
        return n.first_order_start.switch_iteration

    def try_reattach(self) -> bool:
        """Called by the shell on project open (§4.7 re-attach)."""
        supervisor = SolverSupervisor(self.session.case_dir, self.env, self)
        if not (self.session.case_dir / "flowdesk.pid").exists():
            return False
        self.supervisor = supervisor
        self._reset_monitoring()
        self._wire_supervisor()
        attached = supervisor.attach()
        if attached:
            self._ui_timer.start()
            self.run_btn.setEnabled(False)
            self.stop_btn.setEnabled(True)
            self.kill_btn.setEnabled(True)
        return attached

    def _wire_supervisor(self) -> None:
        assert self.supervisor is not None
        self.supervisor.state_changed.connect(self._on_state)
        self.supervisor.finished.connect(self._on_finished)

    # ------------------------------------------------------------------ reset

    def reset_and_rerun(self, confirm: bool = True) -> None:
        """Delete results + run artifacts (with confirmation), then run again."""
        from flowdesk.app import case_ops
        from flowdesk.exec.solver import RunState

        if self.supervisor is not None and self.supervisor.state in (
                RunState.RUNNING, RunState.DECOMPOSING, RunState.RECONSTRUCTING):
            self._add_banner("A solver is running — Stop or Kill it before "
                             "resetting.", "warn")
            return
        items = case_ops.resettable_items(self.session.case_dir)
        if not items:
            self.start_run()
            return
        if confirm:
            from PyQt6.QtWidgets import QMessageBox

            names = ", ".join(p.name for p in items[:8])
            more = f" (+{len(items) - 8} more)" if len(items) > 8 else ""
            answer = QMessageBox.question(
                self, "Reset case",
                f"Delete results and run artifacts?\n\n{names}{more}\n\n"
                "The mesh, dictionaries, and initial fields are kept.")
            if answer != QMessageBox.StandardButton.Yes:
                return
        removed = case_ops.reset_case(self.session.case_dir)
        self._clear_banners()
        self._add_banner(f"Reset: removed {len(removed)} item(s). Starting a "
                         "fresh run.", "info")
        self.model_changed.emit(Stage.RUN)
        self.start_run()

    # ------------------------------------------------------------------ stop/kill

    def _stop(self) -> None:
        if self.supervisor:
            self.supervisor.stop()
            self.stop_btn.setEnabled(False)

    def _kill(self) -> None:
        if self.supervisor:
            self.supervisor.kill()

    # ------------------------------------------------------------------ monitoring

    def _reset_monitoring(self) -> None:
        self.plot.clear()
        self.plot.addLegend(offset=(10, 10))
        self._curves = {}
        self.error_panel.setVisible(False)
        self.error_panel.clear()
        while self._explanation_slot.count():
            item = self._explanation_slot.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _refresh_monitoring(self) -> None:
        if self.supervisor is None:
            return
        parser = self.supervisor.parser

        for fld, series in sorted(parser.residuals.items()):
            if fld not in self._curves:
                color = SERIES_COLORS[len(self._curves) % len(SERIES_COLORS)]
                self._curves[fld] = self.plot.plot(
                    [], [], pen=pg.mkPen(color, width=1.5), name=fld)
            xs = [p[0] for p in series]
            ys = [max(p[1], 1e-16) for p in series]
            self._curves[fld].setData(xs, ys)

        end = (self.session.model.run.max_iterations
               if self.session.model.physics.is_steady
               else self.session.model.physics.time.end_time)
        if end > 0 and parser.current_time > 0:
            fraction = min(parser.current_time / end, 1.0)
            self.progress.setValue(int(fraction * 1000))
            if self._run_started_at and 0 < fraction < 1:
                elapsed = time.monotonic() - self._run_started_at
                remaining = elapsed / fraction * (1 - fraction)
                self.eta_label.setText(f"ETA ~{int(remaining)}s")

        if parser.courant_max and not self.session.model.physics.is_steady:
            mean, peak = parser.courant_max[-1]
            self.courant_label.setText(f"Co {mean:.2f} / max {peak:.2f}")
        if parser.continuity is not None:
            self.continuity_label.setText(f"continuity {parser.continuity:.2e}")

    def _on_state(self, state: RunState) -> None:
        labels = {
            RunState.IDLE: "Idle", RunState.WRITING: "Writing case…",
            RunState.DECOMPOSING: "Decomposing…", RunState.RUNNING: "Running",
            RunState.RECONSTRUCTING: "Reconstructing…", RunState.DONE: "Done ✔",
            RunState.FAILED: "Failed ❌", RunState.STOPPED: "Stopped",
        }
        self.state_label.setText(labels[state])

    def _on_finished(self, ok: bool) -> None:
        self._ui_timer.stop()
        self._refresh_monitoring()  # final flush
        self.run_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.kill_btn.setEnabled(False)
        (self.session.case_dir / "flowdesk.pid").unlink(missing_ok=True)

        parser = self.supervisor.parser if self.supervisor else None
        if not ok and parser and parser.fatal_context:
            # Failure panel (§4.7): verbatim FOAM block + plain-language layer
            block = "\n".join(parser.fatal_context)
            self.error_panel.setPlainText(block)
            self.error_panel.setVisible(True)
            self._explanation_slot.addWidget(
                Banner(error_explain.explain(block), "error"))
        elif not ok:
            self._add_banner("Run did not complete — see the log in the drawer; "
                             "the OpenFOAM output is authoritative.", "warn")
        self.model_changed.emit(Stage.RUN)
        self.run_finished.emit(ok)

    # ------------------------------------------------------------------ banners

    def _add_banner(self, message: str, severity: str) -> None:
        self._banner_slot.addWidget(Banner(message, severity))

    def _clear_banners(self) -> None:
        while self._banner_slot.count():
            item = self._banner_slot.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
