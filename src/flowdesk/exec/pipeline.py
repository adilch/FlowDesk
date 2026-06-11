"""Declarative serial pipeline over QProcess (PRD §7.5).

No silent retries (retry=0 by honesty rule); post-conditions catch
zero-exit-code-but-broken runs; cancellation kills the current process.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from PyQt6.QtCore import QObject, QProcess, pyqtSignal


@dataclass
class Step:
    name: str  # e.g. "blockMesh"
    argv: list[str]
    # Called per stdout/stderr line (parsers accumulate state themselves)
    on_line: Callable[[str], None] | None = None
    # After exit 0: return an error message if the step actually failed
    post_condition: Callable[[], str | None] | None = None


class PipelineState(Enum):
    IDLE = "idle"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


class PipelineRunner(QObject):
    """Runs Steps sequentially; emits Qt signals consumed by the run drawer."""

    line = pyqtSignal(str, str)  # (text, stream: "stdout"|"stderr"|"flowdesk")
    step_started = pyqtSignal(str, int, int)  # (name, index, total)
    step_finished = pyqtSignal(str, int)  # (name, exit_code)
    state_changed = pyqtSignal(PipelineState)
    finished = pyqtSignal(bool)  # success

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._steps: list[Step] = []
        self._index = -1
        self._process: QProcess | None = None
        self._state = PipelineState.IDLE
        self._stdout_buffer = ""
        self._stderr_buffer = ""

    @property
    def state(self) -> PipelineState:
        return self._state

    def run(self, steps: list[Step]) -> None:
        if self._state is PipelineState.RUNNING:
            raise RuntimeError("pipeline already running")
        self._steps = steps
        self._index = -1
        self._set_state(PipelineState.RUNNING)
        self._next_step()

    def cancel(self) -> None:
        if self._process is not None and self._state is PipelineState.RUNNING:
            self._set_state(PipelineState.CANCELLED)
            self._process.kill()

    # ------------------------------------------------------------------ internals

    def _set_state(self, state: PipelineState) -> None:
        self._state = state
        self.state_changed.emit(state)

    def _next_step(self) -> None:
        self._index += 1
        if self._index >= len(self._steps):
            self._set_state(PipelineState.DONE)
            self.finished.emit(True)
            return
        step = self._steps[self._index]
        self.step_started.emit(step.name, self._index, len(self._steps))
        self.line.emit(f"FlowDesk: running {step.name}", "flowdesk")

        process = QProcess(self)
        self._process = process
        self._stdout_buffer = ""
        self._stderr_buffer = ""
        process.setProgram(step.argv[0])
        process.setArguments(step.argv[1:])
        process.readyReadStandardOutput.connect(lambda: self._drain(process, "stdout"))
        process.readyReadStandardError.connect(lambda: self._drain(process, "stderr"))
        process.finished.connect(self._on_finished)
        process.errorOccurred.connect(self._on_error)
        process.start()

    def _drain(self, process: QProcess, stream: str) -> None:
        if stream == "stdout":
            data = bytes(process.readAllStandardOutput()).decode("utf-8", errors="replace")
            self._stdout_buffer += data
            self._stdout_buffer = self._flush_lines(self._stdout_buffer, "stdout")
        else:
            data = bytes(process.readAllStandardError()).decode("utf-8", errors="replace")
            self._stderr_buffer += data
            self._stderr_buffer = self._flush_lines(self._stderr_buffer, "stderr")

    def _flush_lines(self, buffer: str, stream: str) -> str:
        step = self._steps[self._index]
        while "\n" in buffer:
            text, buffer = buffer.split("\n", 1)
            text = text.rstrip("\r")
            self.line.emit(text, stream)
            if step.on_line is not None:
                step.on_line(text)
        return buffer

    def _on_error(self, _error) -> None:
        if self._state is not PipelineState.RUNNING:
            return
        step = self._steps[self._index]
        self.line.emit(
            f"FlowDesk: failed to start {step.name} ({step.argv[0]})", "flowdesk")
        self._fail(step, exit_code=-1)

    def _on_finished(self, exit_code: int, _status) -> None:
        if self._state is PipelineState.CANCELLED:
            self.finished.emit(False)
            return
        step = self._steps[self._index]
        # flush trailing partial lines
        self._stdout_buffer = self._flush_lines(self._stdout_buffer + "\n", "stdout") \
            if self._stdout_buffer else ""
        self.step_finished.emit(step.name, exit_code)
        if exit_code != 0:
            self._fail(step, exit_code)
            return
        if step.post_condition is not None:
            problem = step.post_condition()
            if problem:
                self.line.emit(f"FlowDesk: {step.name} exited 0 but: {problem}", "flowdesk")
                self._fail(step, exit_code=0)
                return
        self._next_step()

    def _fail(self, step: Step, exit_code: int) -> None:
        self._set_state(PipelineState.FAILED)
        self.finished.emit(False)


def file_exists_condition(path: Path, description: str) -> Callable[[], str | None]:
    """Common post-condition: e.g. polyMesh/points must exist after blockMesh (§7.5)."""

    def check() -> str | None:
        return None if path.exists() else f"{description} ({path.name} missing)"

    return check
