"""Bottom run drawer (PRD §5.1): log + pipeline progress, shared by mesh and solver runs."""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from flowdesk.exec.pipeline import PipelineRunner, PipelineState
from flowdesk.ui.components import LogView, make_button
from flowdesk.ui.theme import DRAWER_HEIGHT


class RunDrawer(QFrame):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setProperty("panel", "true")
        self.setFixedHeight(DRAWER_HEIGHT)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 8, 16, 8)

        header = QHBoxLayout()
        self.state_label = QLabel("Idle")
        self.state_label.setProperty("role", "caption")
        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.progress.setFormat("step %v / %m")
        self.cancel_btn = make_button("Stop", "danger")
        self.cancel_btn.setEnabled(False)
        header.addWidget(self.state_label, stretch=1)
        header.addWidget(self.progress, stretch=2)
        header.addWidget(self.cancel_btn)
        layout.addLayout(header)

        self.log = LogView()
        layout.addWidget(self.log)

        self._runner: PipelineRunner | None = None

    def attach(self, runner: PipelineRunner) -> None:
        """Wire a pipeline's signals into the drawer for the duration of a run."""
        self._runner = runner
        runner.line.connect(self._on_line)
        runner.step_started.connect(self._on_step_started)
        runner.state_changed.connect(self._on_state)
        self.cancel_btn.clicked.connect(runner.cancel)
        self.cancel_btn.setEnabled(True)

    def _on_line(self, text: str, stream: str) -> None:
        prefix = "· " if stream == "flowdesk" else ""
        self.log.append_line(prefix + text)

    def _on_step_started(self, name: str, index: int, total: int) -> None:
        self.state_label.setText(f"Running {name} ({index + 1}/{total})")
        self.progress.setRange(0, total)
        self.progress.setValue(index)

    def _on_state(self, state: PipelineState) -> None:
        labels = {
            PipelineState.IDLE: "Idle",
            PipelineState.RUNNING: "Running…",
            PipelineState.DONE: "Done ✔",
            PipelineState.FAILED: "Failed ❌ — see log",
            PipelineState.CANCELLED: "Stopped",
        }
        if state in (PipelineState.DONE, PipelineState.FAILED, PipelineState.CANCELLED):
            self.cancel_btn.setEnabled(False)
            if state is PipelineState.DONE:
                self.progress.setValue(self.progress.maximum())
        self.state_label.setText(labels[state])
