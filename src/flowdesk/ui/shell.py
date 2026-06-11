"""Project window shell (PRD §5.1): rail | stage content | drawer | status bar.

One window, one project. The single shared viewer instance migrates between
viewer-dominant stages. On open, a live solver run is re-attached (§4.7).
"""

from __future__ import annotations

import contextlib

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import (
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

        center = QVBoxLayout()
        center.setContentsMargins(0, 0, 0, 0)
        center.addWidget(self._stack, stretch=1)
        center.addWidget(self.drawer)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addWidget(self.rail)
        body.addLayout(center, stretch=1)

        self.status_bar = QLabel("")
        self.status_bar.setProperty("role", "caption")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addLayout(body, stretch=1)
        root.addWidget(self.status_bar)

        # Signals
        self.rail.stage_selected.connect(self.show_stage)
        for stage_widget in (self.geometry_stage, self.mesh_stage, self.physics_stage,
                             self.boundaries_stage, self.numerics_stage,
                             self.run_stage):
            stage_widget.model_changed.connect(self._on_model_changed)
        self.geometry_stage.model_changed.connect(lambda _s: self.mesh_stage.refresh())
        self.physics_stage.model_changed.connect(
            lambda _s: self.boundaries_stage.refresh())
        self.mesh_stage.mesh_completed.connect(self._on_mesh_completed)
        self.run_stage.run_finished.connect(lambda _ok: self._refresh_status())

        # Keyboard (§5.2): Ctrl+1..7 stages, Ctrl+S save, Ctrl+R run, F fit viewer
        for i, stage in enumerate(Stage, start=1):
            shortcut = QShortcut(QKeySequence(f"Ctrl+{i}"), self)
            shortcut.activated.connect(lambda s=stage: self.show_stage(s))
        QShortcut(QKeySequence("Ctrl+S"), self).activated.connect(self._force_save)
        QShortcut(QKeySequence("Ctrl+R"), self).activated.connect(
            lambda: self.show_stage(Stage.RUN))
        QShortcut(QKeySequence("F"), self).activated.connect(self.viewer.fit)

        # Close project: back to Home (rail bottom; confirm when a run is live)
        from flowdesk.ui.components import make_button

        close_btn = make_button("←  Close project", "ghost")
        close_btn.clicked.connect(self.request_close)
        self.rail.layout().addWidget(close_btn)

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
        self._move_viewer(stage)
        if stage is Stage.BOUNDARIES:
            self.boundaries_stage.refresh()
            self._color_patches()
        elif stage is Stage.RESULTS:
            self.results_stage.refresh()
        else:
            self._refresh_viewer()

    def _move_viewer(self, stage: Stage) -> None:
        slots = {
            Stage.GEOMETRY: self.geometry_stage.viewer_slot,
            Stage.MESH: self.mesh_stage.viewer_slot,
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
            self.viewer.show_domain_box(block.bounds_min, block.bounds_max)
            for surface in model.geometry.surfaces:
                stl = self.session.case_dir / "constant" / "triSurface" / f"{surface.name}.stl"
                if stl.exists():
                    self.viewer.load_surface(stl, name=surface.name)
            for region in model.mesh.snappy.regions:
                self.viewer.show_region_overlay(region.name, region.geometry)
            if model.mesh.snappy.location_in_mesh is not None:
                self.viewer.show_location_marker(model.mesh.snappy.location_in_mesh)

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
            self.viewer.load_openfoam_mesh(self.session.case_dir)

    # ------------------------------------------------------------------ status

    def _on_model_changed(self, _stage: Stage) -> None:
        if self.mesh_stage.runner is not None:
            self.drawer.attach(self.mesh_stage.runner)
        self._connect_supervisor_log()
        self._refresh_status()

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

    def _force_save(self) -> None:
        self.session.save_model()
        self.status_bar.setText("  model saved ✔")

    def _connect_supervisor_log(self) -> None:
        supervisor = self.run_stage.supervisor
        if supervisor is not None and supervisor is not self._connected_supervisor:
            supervisor.line.connect(self.drawer.log.append_line)
            self._connected_supervisor = supervisor

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
        cells = f"{result.cell_count:,} cells • " if result else ""
        env = "✔ env" if self.env.available else "❌ env"
        self.status_bar.setText(
            f"  {env} • {cells}{n_err} errors, {n_warn} warnings"
        )
