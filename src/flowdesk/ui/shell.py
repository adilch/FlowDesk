"""Project window shell (PRD §5.1): rail | stage content | drawer | status bar.

One window, one project. The single shared viewer instance migrates between
viewer-dominant stages. On open, a live solver run is re-attached (§4.7).
"""

from __future__ import annotations

import contextlib

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from flowdesk.app.projects import ProjectSession
from flowdesk.model.findings import Severity, Stage
from flowdesk.platform.commands import Environment
from flowdesk.ui.drawer import RunDrawer
from flowdesk.ui.rail import WorkflowRail
from flowdesk.ui.stages.boundaries import BoundariesStage, patch_color
from flowdesk.ui.stages.geometry import GeometryStage
from flowdesk.ui.stages.mesh import MeshStage
from flowdesk.ui.stages.numerics import NumericsStage
from flowdesk.ui.stages.physics import PhysicsStage
from flowdesk.ui.stages.results import ResultsStage
from flowdesk.ui.stages.run import RunStage
from flowdesk.ui.viewer import ViewerWidget


class ProjectShell(QWidget):
    close_requested = pyqtSignal()

    def __init__(self, session: ProjectSession, env: Environment,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.session = session
        self.env = env

        self.viewer = ViewerWidget()
        self.rail = WorkflowRail()
        self.drawer = RunDrawer()

        self.geometry_stage = GeometryStage(session)
        self.mesh_stage = MeshStage(session, env)
        self.physics_stage = PhysicsStage(session)
        self.boundaries_stage = BoundariesStage(session)
        self.numerics_stage = NumericsStage(session)
        self.run_stage = RunStage(session, env)
        self.results_stage = ResultsStage(session, self.viewer)
        self._stages: dict[Stage, QWidget] = {
            Stage.GEOMETRY: self.geometry_stage,
            Stage.MESH: self.mesh_stage,
            Stage.PHYSICS: self.physics_stage,
            Stage.BOUNDARIES: self.boundaries_stage,
            Stage.NUMERICS: self.numerics_stage,
            Stage.RUN: self.run_stage,
            Stage.RESULTS: self.results_stage,
        }

        self._stack = QStackedWidget()
        for stage in Stage:
            self._stack.addWidget(self._stages[stage])

        # Stage header / breadcrumb bar (top of the center column)
        self._header = self._build_header()

        from PyQt6.QtCore import Qt
        from PyQt6.QtWidgets import QSplitter

        from flowdesk.ui.theme import DRAWER_HEIGHT

        center = QVBoxLayout()
        center.setContentsMargins(0, 0, 0, 0)
        center.setSpacing(0)
        center.addWidget(self._header)
        # stack | drawer in a draggable vertical splitter (resizable log)
        vsplit = QSplitter(Qt.Orientation.Vertical)
        vsplit.addWidget(self._stack)
        vsplit.addWidget(self.drawer)
        vsplit.setStretchFactor(0, 1)
        vsplit.setStretchFactor(1, 0)
        vsplit.setChildrenCollapsible(False)
        vsplit.setHandleWidth(6)
        vsplit.setSizes([600, DRAWER_HEIGHT])
        center.addWidget(vsplit, stretch=1)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addWidget(self.rail)
        body.addLayout(center, stretch=1)

        self._status_strip = self._build_status_bar()

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addLayout(body, stretch=1)
        root.addWidget(self._status_strip)

        # Signals
        self.rail.stage_selected.connect(self.show_stage)
        for stage_widget in (self.geometry_stage, self.mesh_stage, self.physics_stage,
                             self.boundaries_stage, self.numerics_stage,
                             self.run_stage):
            stage_widget.model_changed.connect(self._on_model_changed)
        self.geometry_stage.model_changed.connect(lambda _s: self.mesh_stage.refresh())
        self.physics_stage.model_changed.connect(
            lambda _s: self.boundaries_stage.refresh())
        # The drawer attaches the moment a mesh pipeline starts, so progress
        # and every blockMesh/snappy line stream into the log live
        self.mesh_stage.mesh_started.connect(self.drawer.attach)
        self.mesh_stage.mesh_completed.connect(self._on_mesh_completed)
        # click a meshed patch -> highlight it (distinct colours for multiple)
        self.mesh_stage.patches_selected.connect(self.viewer.color_selected_patches)
        self.geometry_stage.visibility_toggled.connect(self.viewer.set_surface_visible)
        self.boundaries_stage.selection_changed.connect(
            self.viewer.highlight_patches)
        self.run_stage.run_finished.connect(lambda _ok: self._refresh_status())

        # Live canvas previews while editing spatial inputs (SimFlow-style:
        # you see the domain / regions / water column as you type them)
        background = self.mesh_stage.background
        for vec in (background.bounds_min, background.bounds_max):
            vec.valueChanged.connect(lambda *_a: self._preview_domain())
        self.mesh_stage.snappy.changed.connect(self._preview_snappy)
        physics = self.physics_stage
        physics.free_surface_chk.toggled.connect(lambda _c: self._preview_column())
        for vec in (physics.column_min, physics.column_max):
            vec.valueChanged.connect(lambda *_a: self._preview_column())

        # Keyboard (§5.2): Ctrl+1..7 stages, Ctrl+S save, Ctrl+R run, F fit viewer
        for i, stage in enumerate(Stage, start=1):
            shortcut = QShortcut(QKeySequence(f"Ctrl+{i}"), self)
            shortcut.activated.connect(lambda s=stage: self.show_stage(s))
        QShortcut(QKeySequence("Ctrl+S"), self).activated.connect(self.save_project)
        QShortcut(QKeySequence("Ctrl+R"), self).activated.connect(
            lambda: self.show_stage(Stage.RUN))
        QShortcut(QKeySequence("F"), self).activated.connect(self.viewer.fit)

        # Save + Close project (rail bottom); labels shrink with the rail
        from flowdesk.ui.components import make_button
        from flowdesk.ui.icons import icon
        from flowdesk.ui.theme import COLORS

        self._save_btn = make_button("Save project", "secondary")
        self._save_btn.setIcon(icon("save", COLORS["text-1"], 18))
        self._save_btn.setToolTip("Write the case files + project sidecar to disk (Ctrl+S)")
        self._save_btn.clicked.connect(self.save_project)
        self.rail.layout().addWidget(self._save_btn)
        self._close_btn = make_button("Close project", "ghost")
        self._close_btn.setIcon(icon("chevron-left", COLORS["accent"], 18))
        self._close_btn.clicked.connect(self.request_close)
        self.rail.layout().addWidget(self._close_btn)
        self.rail.collapse_toggled.connect(self._on_rail_collapsed)

        self.show_stage(Stage.GEOMETRY)
        self.rail.select(Stage.GEOMETRY)
        self._refresh_status()

        # §4.7 re-attach: a solver left running by a dead GUI is picked up
        self._connected_supervisor = None
        if self.run_stage.try_reattach():
            self.show_stage(Stage.RUN)
            self.rail.select(Stage.RUN)
        self._connect_supervisor_log()

    # ------------------------------------------------------------------ navigation

    def show_stage(self, stage: Stage) -> None:
        self._stack.setCurrentWidget(self._stages[stage])
        from flowdesk.ui.rail import STAGE_INFO

        number, label = STAGE_INFO[stage]
        self._crumb_stage.setText(f"{number} · {label}")
        self._move_viewer(stage)
        if stage is Stage.BOUNDARIES:
            self.boundaries_stage.refresh()
            self._color_patches()
        elif stage is Stage.RESULTS:
            self.results_stage.refresh()
        elif stage is Stage.RUN:
            # write controls track the current steady/transient choice
            self.run_stage.refresh_write_controls()
        elif stage is Stage.MESH:
            self._refresh_mesh_view()
        else:
            self._refresh_viewer()

    def _refresh_mesh_view(self) -> None:
        """On the Mesh stage: show the last generated mesh (per-patch, so patches
        can be clicked to highlight) if one exists, otherwise the inputs (domain
        box + geometry)."""
        meshed = (self.session.case_dir / "constant" / "polyMesh" / "points").exists()
        if meshed and self.session.model.mesh.result is not None:
            with contextlib.suppress(Exception):
                names = self.viewer.show_mesh_patches(self.session.case_dir)
                if names:
                    # restore any current patch-list selection in the view
                    self.mesh_stage._on_patch_selection()
                    return
        self._refresh_viewer()

    def _move_viewer(self, stage: Stage) -> None:
        slots = {
            Stage.GEOMETRY: self.geometry_stage.viewer_slot,
            Stage.MESH: self.mesh_stage.viewer_slot,
            Stage.PHYSICS: self.physics_stage.viewer_slot,
            Stage.BOUNDARIES: self.boundaries_stage.viewer_slot,
            Stage.RESULTS: self.results_stage.viewer_slot,
        }
        slot = slots.get(stage)
        if slot is None:
            return
        self.viewer.setParent(None)
        slot.addWidget(self.viewer)

    def _refresh_viewer(self) -> None:
        model = self.session.model
        block = model.mesh.block
        with contextlib.suppress(Exception):
            # full rebuild so deleted geometry/regions don't linger as actors
            self.viewer.plotter.clear()
            self.viewer.show_domain_box(block.bounds_min, block.bounds_max)
            hidden = self.geometry_stage.hidden_surfaces()
            for surface in model.geometry.surfaces:
                stl = self.session.case_dir / "constant" / "triSurface" / f"{surface.name}.stl"
                if stl.exists():
                    self.viewer.load_surface(stl, name=surface.name)
                    if surface.name in hidden:
                        self.viewer.set_surface_visible(surface.name, False)
            for region in model.mesh.snappy.regions:
                self.viewer.show_region_overlay(region.name, region.geometry)
            if model.mesh.snappy.location_in_mesh is not None:
                self.viewer.show_location_marker(model.mesh.snappy.location_in_mesh)
            # init volume (free surface): visible wherever the domain is shown
            fs = model.physics.free_surface
            if fs is not None:
                self.viewer.show_water_column(fs.water_column_min,
                                              fs.water_column_max)
            else:
                self.viewer.hide_water_column()

    # ---------------------------------------------------------- live previews

    def _preview_domain(self) -> None:
        """Domain box follows the Background form as it is edited."""
        with contextlib.suppress(Exception):
            background = self.mesh_stage.background
            self.viewer.show_domain_box(background.bounds_min.value(),
                                        background.bounds_max.value())
            self.viewer.plotter.render()

    def _preview_snappy(self) -> None:
        """Region/material-point overlays follow the Refinement tab live."""
        with contextlib.suppress(Exception):
            self.mesh_stage.snappy.collect_into_model()
            self._refresh_viewer()
            self.viewer.plotter.render()

    def _preview_column(self) -> None:
        """Water-init volume follows the Physics form live (free surface)."""
        with contextlib.suppress(Exception):
            physics = self.physics_stage
            if physics.free_surface_chk.isChecked():
                self.viewer.show_water_column(physics.column_min.value(),
                                              physics.column_max.value())
            else:
                self.viewer.hide_water_column()
            self.viewer.plotter.render()

    def _color_patches(self) -> None:
        """BC stage viewer: meshed patches colored by assignment (§4.5/§6.1)."""
        with contextlib.suppress(Exception):
            assignments = {
                patch: patch_color(self.session.model.boundaries.get(patch))
                for patch in self.session.model.expected_patches()
            }
            self.viewer.show_patches(self.session.case_dir, assignments)

    def _on_mesh_completed(self, ok: bool) -> None:
        if not ok:
            return
        self.boundaries_stage.refresh()
        with contextlib.suppress(Exception):
            self.viewer.show_mesh_patches(self.session.case_dir)

    # ------------------------------------------------------------------ status

    def _on_model_changed(self, _stage: Stage) -> None:
        self._connect_supervisor_log()
        self._refresh_status()
        # reflect geometry add/delete/edit in the canvas immediately
        if self._stack.currentWidget() is self.geometry_stage:
            self._refresh_viewer()
        # the model-select wizard can toggle free surface: refresh the water box
        elif self._stack.currentWidget() is self.physics_stage:
            self._preview_column()

    def request_close(self) -> None:
        """Close the project (§5.2: confirm if running). The detached solver
        keeps running either way - reopening the project re-attaches."""
        from flowdesk.exec.solver import RunState

        supervisor = self.run_stage.supervisor
        if supervisor is not None and supervisor.state in (
                RunState.RUNNING, RunState.DECOMPOSING, RunState.RECONSTRUCTING):
            answer = QMessageBox.question(
                self, "Close project",
                "A solver is running. It will keep running in the background "
                "(detached) and FlowDesk will re-attach when you reopen this "
                "project.\n\nClose anyway?")
            if answer != QMessageBox.StandardButton.Yes:
                return
            supervisor.detach()  # stop tailing; the process is untouched
        self.session.save_model()
        self.close_requested.emit()

    def save_project(self) -> None:
        """Explicit save: persist the sidecar, and write the full case files to
        disk when the model is valid (so the on-disk OpenFOAM case is current).
        An invalid model still saves the sidecar - work is never lost."""
        from flowdesk.model.case import InvalidCaseError

        self.session.save_model()
        try:
            validated = self.session.model.validated()
        except InvalidCaseError:
            self.status_bar.setText(
                "  Project saved ✔  (sidecar only — case has validation errors)")
            return
        try:
            from flowdesk.foam import writer

            writer.write_case(validated, self.session.case_dir)
            self.status_bar.setText("  Project saved ✔  (case files written)")
        except Exception as exc:  # writing is best-effort; sidecar already saved
            self.status_bar.setText(f"  Project sidecar saved ✔  (case write: {exc})")

    # back-compat alias for the Ctrl+S binding name used elsewhere
    _force_save = save_project

    def _connect_supervisor_log(self) -> None:
        supervisor = self.run_stage.supervisor
        if supervisor is not None and supervisor is not self._connected_supervisor:
            supervisor.line.connect(self.drawer.log.append_line)
            self._connected_supervisor = supervisor

    # ---------------------------------------------------------- header & status

    def _build_header(self) -> QFrame:
        from flowdesk.ui.theme import HEADER_HEIGHT

        header = QFrame()
        header.setProperty("header", "true")
        header.setFixedHeight(HEADER_HEIGHT)
        h = QHBoxLayout(header)
        h.setContentsMargins(16, 0, 16, 0)
        self._crumb_project = QLabel(self.session.model.meta.name)
        self._crumb_project.setProperty("role", "crumb")
        sep = QLabel("›")
        sep.setProperty("role", "crumb")
        self._crumb_stage = QLabel("Geometry")
        self._crumb_stage.setProperty("role", "crumb-active")
        h.addWidget(self._crumb_project)
        h.addWidget(sep)
        h.addWidget(self._crumb_stage)
        h.addStretch()
        self._header_info = QLabel("")
        self._header_info.setProperty("role", "caption")
        h.addWidget(self._header_info)
        return header

    def _build_status_bar(self) -> QFrame:
        from flowdesk.ui.components import make_button

        strip = QFrame()
        strip.setProperty("statusbar", "true")
        h = QHBoxLayout(strip)
        h.setContentsMargins(16, 4, 16, 4)
        self.status_bar = QLabel("")
        self.status_bar.setProperty("role", "caption")
        h.addWidget(self.status_bar)
        h.addStretch()
        self._validation_btn = make_button("", "ghost")
        self._validation_btn.clicked.connect(self._jump_to_first_finding)
        h.addWidget(self._validation_btn)
        return strip

    def _on_rail_collapsed(self, collapsed: bool) -> None:
        self._save_btn.setText("" if collapsed else "Save project")
        self._close_btn.setText("" if collapsed else "Close project")

    def _jump_to_first_finding(self) -> None:
        findings = self.session.model.validate_full()
        ordered = [f for f in findings if f.severity is Severity.ERROR] or findings
        if ordered:
            self.show_stage(ordered[0].stage)
            self.rail.select(ordered[0].stage)

    def _refresh_status(self) -> None:
        statuses = self.session.stage_statuses()
        enabled = {s: True for s in Stage}
        enabled[Stage.RUN] = self.session.run_enabled()
        result = self.session.model.mesh.result
        # §4.0: Results enabled when at least one time directory exists
        enabled[Stage.RESULTS] = self.session._started(Stage.RESULTS)
        self.rail.update_statuses(statuses, enabled)

        findings = self.session.model.validate_full()
        n_err = sum(1 for f in findings if f.severity is Severity.ERROR)
        n_warn = sum(1 for f in findings if f.severity is Severity.WARNING)

        # header info (right side): env, cells, run state
        env = "✔ env" if self.env.available else "❌ env"
        cells = f" • {result.cell_count:,} cells" if result else ""
        run_state = self._run_state_text()
        self._header_info.setText(f"{env}{cells}{run_state}")

        # status bar (bottom): clickable validation summary
        if n_err:
            self._validation_btn.setText(f"❌ {n_err} error{'s' if n_err > 1 else ''}"
                                         + (f"  ⚠ {n_warn}" if n_warn else ""))
            self._validation_btn.setToolTip("Jump to the first error")
            self._validation_btn.setVisible(True)
        elif n_warn:
            self._validation_btn.setText(f"⚠ {n_warn} warning{'s' if n_warn > 1 else ''}")
            self._validation_btn.setToolTip("Jump to the first warning")
            self._validation_btn.setVisible(True)
        else:
            self._validation_btn.setText("✔ no issues")
            self._validation_btn.setVisible(True)

    def _run_state_text(self) -> str:
        supervisor = self.run_stage.supervisor
        if supervisor is None:
            return ""
        return f" • {supervisor.state.value}"
