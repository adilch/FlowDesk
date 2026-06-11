"""Project window shell (PRD §5.1): rail | stage content | drawer | status bar.

One window, one project. The single shared viewer instance migrates between
viewer-dominant stages.
"""

from __future__ import annotations

from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from flowdesk.app.projects import ProjectSession
from flowdesk.model.findings import Severity, Stage
from flowdesk.platform.commands import Environment
from flowdesk.ui.drawer import RunDrawer
from flowdesk.ui.rail import WorkflowRail
from flowdesk.ui.stages.geometry import GeometryStage, PlaceholderStage
from flowdesk.ui.stages.mesh import MeshStage
from flowdesk.ui.viewer import ViewerWidget


class ProjectShell(QWidget):
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
        self._stages: dict[Stage, QWidget] = {
            Stage.GEOMETRY: self.geometry_stage,
            Stage.MESH: self.mesh_stage,
            Stage.PHYSICS: PlaceholderStage("Physics", "M4"),
            Stage.BOUNDARIES: PlaceholderStage("Boundary Conditions", "M4"),
            Stage.NUMERICS: PlaceholderStage("Numerics", "M4"),
            Stage.RUN: PlaceholderStage("Run", "M4"),
            Stage.RESULTS: PlaceholderStage("Results", "M5"),
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
        self.geometry_stage.model_changed.connect(self._on_model_changed)
        self.mesh_stage.model_changed.connect(self._on_model_changed)
        self.mesh_stage.mesh_completed.connect(lambda _ok: self._refresh_viewer())

        # Keyboard: Ctrl+1..7 (§5.2)
        for i, stage in enumerate(Stage, start=1):
            shortcut = QShortcut(QKeySequence(f"Ctrl+{i}"), self)
            shortcut.activated.connect(lambda s=stage: self.show_stage(s))

        self.show_stage(Stage.GEOMETRY)
        self.rail.select(Stage.GEOMETRY)
        self._refresh_status()

    # ------------------------------------------------------------------ navigation

    def show_stage(self, stage: Stage) -> None:
        self._stack.setCurrentWidget(self._stages[stage])
        self._move_viewer(stage)
        self._refresh_viewer()

    def _move_viewer(self, stage: Stage) -> None:
        """The one viewer instance lives in whichever active stage wants it."""
        slots = {
            Stage.GEOMETRY: self.geometry_stage.viewer_slot,
            Stage.MESH: self.mesh_stage.viewer_slot,
        }
        slot = slots.get(stage)
        if slot is None:
            return
        self.viewer.setParent(None)
        slot.addWidget(self.viewer)

    def _refresh_viewer(self) -> None:
        """Show imported surfaces + the background-mesh box outline."""
        model = self.session.model
        block = model.mesh.block
        try:
            self.viewer.show_domain_box(block.bounds_min, block.bounds_max)
            for surface in model.geometry.surfaces:
                stl = self.session.case_dir / "constant" / "triSurface" / f"{surface.name}.stl"
                if stl.exists():
                    self.viewer.load_surface(stl, name=surface.name)
        except Exception:
            pass  # viewer is best-effort; stage content never depends on it

    # ------------------------------------------------------------------ status

    def _on_model_changed(self, _stage: Stage) -> None:
        if self.mesh_stage.runner is not None:
            self.drawer.attach(self.mesh_stage.runner)
        self._refresh_status()

    def _refresh_status(self) -> None:
        statuses = self.session.stage_statuses()
        enabled = {s: True for s in Stage}
        enabled[Stage.RUN] = self.session.run_enabled()
        result = self.session.model.mesh.result
        enabled[Stage.RESULTS] = False  # M5
        self.rail.update_statuses(statuses, enabled)

        findings = self.session.model.validate_full()
        n_err = sum(1 for f in findings if f.severity is Severity.ERROR)
        n_warn = sum(1 for f in findings if f.severity is Severity.WARNING)
        cells = f"{result.cell_count:,} cells • " if result else ""
        env = "✔ env" if self.env.available else "❌ env"
        self.status_bar.setText(
            f"  {env} • {cells}{n_err} errors, {n_warn} warnings"
        )
