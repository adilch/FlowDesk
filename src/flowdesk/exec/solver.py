"""Detached solver execution with re-attach (PRD §4.7 sequence + §7.5 crash safety).

The solver runs as a setsid-detached script inside WSL (or native bash), with
all output appended to log.flowdesk in the case directory. FlowDesk *tails the
file* - it never owns the process's stdout - so killing the GUI leaves the
solver running, and a relaunched FlowDesk re-attaches by PID file + tail.

State machine (§4.7): Idle -> Writing -> Decomposing -> Running ->
Reconstructing -> Done/Failed/Stopped.
"""

from __future__ import annotations

import sys
from enum import Enum
from pathlib import Path, PureWindowsPath

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from flowdesk.exec.residuals import SolverLogParser
from flowdesk.model.case import CaseModel
from flowdesk.model.numerics import RunMode
from flowdesk.platform import wsl
from flowdesk.platform.commands import Environment

LOG_NAME = "log.flowdesk"
PID_NAME = "flowdesk.pid"
EXIT_NAME = "flowdesk.exit"
SCRIPT_NAME = "flowdesk-run.sh"
TARGET_SCHEMES = "fvSchemes.flowdesk-target"


class RunState(Enum):
    IDLE = "idle"
    WRITING = "writing"
    DECOMPOSING = "decomposing"
    RUNNING = "running"
    RECONSTRUCTING = "reconstructing"
    DONE = "done"
    FAILED = "failed"
    STOPPED = "stopped"


def build_run_script(model: CaseModel, first_order_switch: int | None,
                     set_fields: bool = False) -> str:
    """The detached run script. Markers drive the state machine; every FlowDesk
    intervention is an explicit, visible log line (honesty rule).

    set_fields: initialize the free-surface water column (only on a virgin
    case - a latestTime restart must not re-flood the domain)."""
    parallel = model.run.mode is RunMode.PARALLEL
    solver = model.physics.solver
    n = model.run.cores
    end = model.run.max_iterations if model.physics.is_steady \
        else model.physics.time.end_time

    lines = [
        "#!/bin/bash",
        'cd "$(dirname "$0")"',
        f"echo $$ > {PID_NAME}",  # the supervisor reads this; $$ is the session PID
        f"source {wsl.OPENFOAM_BASHRC}",
        f"rm -f {EXIT_NAME}",
        "set -o pipefail",
        "fail() { echo \"FLOWDESK_STATE: failed\"; echo $1 > " + EXIT_NAME + "; exit $1; }",
    ]
    if set_fields:
        lines += [
            'echo "FlowDesk: initializing the water column (setFields)"',
            "setFields || fail $?",
        ]
    if parallel:
        lines += [
            'echo "FLOWDESK_STATE: decomposing"',
            "decomposePar -force || fail $?",
        ]
        solve = f"mpirun -np {n} {solver} -parallel"
    else:
        solve = solver

    if first_order_switch is not None:
        lines += [
            f'echo "FlowDesk: first-order start - leg 1 (upwind) to {first_order_switch}"',
            'echo "FLOWDESK_STATE: running"',
            f"foamDictionary -entry endTime -set {first_order_switch} "
            "system/controlDict || fail $?",
            f"{solve} || fail $?",
            f'echo "FlowDesk: switching to second-order at iteration {first_order_switch}"',
            f"cp system/{TARGET_SCHEMES} system/fvSchemes || fail $?",
            f"foamDictionary -entry endTime -set {end} system/controlDict || fail $?",
            f"{solve} || fail $?",
        ]
    else:
        lines += [
            'echo "FLOWDESK_STATE: running"',
            f"{solve} || fail $?",
        ]

    if parallel:
        lines += [
            'echo "FLOWDESK_STATE: reconstructing"',
            # -newTimes reconstructs every saved time not yet in the case root
            # (-latestTime per the PRD example dropped all earlier frames from
            # the Results view - found by a user)
            "reconstructPar -newTimes || fail $?",
        ]
    lines += [
        "touch case.foam",
        'echo "FLOWDESK_STATE: done"',
        f"echo 0 > {EXIT_NAME}",
    ]
    return "\n".join(lines) + "\n"


class SolverSupervisor(QObject):
    """Launches/attaches to a detached run and tails its log."""

    line = pyqtSignal(str)
    state_changed = pyqtSignal(RunState)
    finished = pyqtSignal(bool)  # success

    def __init__(self, case_dir: Path, env: Environment, parent: QObject | None = None):
        super().__init__(parent)
        self.case_dir = case_dir
        self.env = env
        self.parser = SolverLogParser()
        self._state = RunState.IDLE
        self._offset = 0
        self._poll_count = 0
        self._pid: int | None = None
        self._timer = QTimer(self)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self._poll)

    @property
    def state(self) -> RunState:
        return self._state

    @property
    def pid(self) -> int | None:
        return self._pid

    # ------------------------------------------------------------------ control

    def start(self, model: CaseModel, first_order_switch: int | None = None) -> None:
        self._set_state(RunState.WRITING)
        # Free-surface cases get their water column on a virgin case only;
        # restarts continue from the saved alpha.water field.
        needs_set_fields = (model.physics.free_surface is not None
                            and not self._has_result_times())
        script = build_run_script(model, first_order_switch,
                                  set_fields=needs_set_fields)
        (self.case_dir / SCRIPT_NAME).write_text(script, encoding="utf-8", newline="\n")
        (self.case_dir / LOG_NAME).write_text("", encoding="utf-8")  # fresh log
        (self.case_dir / EXIT_NAME).unlink(missing_ok=True)
        (self.case_dir / PID_NAME).unlink(missing_ok=True)
        self._offset = 0
        self.parser = SolverLogParser()

        # setsid --fork detaches atomically in the foreground: no background
        # job for the dying wsl.exe session to SIGHUP before setsid runs
        # (a plain `nohup ... &` raced session teardown and lost).
        linux_case = self._linux_case()
        launch = (f"cd {wsl.shell_quote(str(linux_case))} && "
                  f"setsid --fork bash {SCRIPT_NAME} >> {LOG_NAME} 2>&1 < /dev/null")
        result = self._bash(launch)
        if result.returncode != 0:
            self.line.emit(f"FlowDesk: failed to launch run: {result.stderr.strip()}")
            self._set_state(RunState.FAILED)
            self.finished.emit(False)
            return
        pid = self._await_pid_file()
        if pid is None:
            self.line.emit("FlowDesk: run script never started (no PID file)")
            self._set_state(RunState.FAILED)
            self.finished.emit(False)
            return
        self._pid = pid
        self.line.emit(f"FlowDesk: run started (pid {self._pid}, detached - "
                       "survives FlowDesk closing)")
        self._timer.start()

    def _has_result_times(self) -> bool:
        return any(
            p.is_dir() and p.name != "0"
            and p.name.replace(".", "", 1).replace("e-", "", 1).isdigit()
            for p in self.case_dir.iterdir())

    def _await_pid_file(self, timeout_s: float = 10.0) -> int | None:
        import time

        deadline = time.monotonic() + timeout_s
        pid_file = self.case_dir / PID_NAME
        while time.monotonic() < deadline:
            if pid_file.exists():
                text = pid_file.read_text().strip()
                if text.isdigit():
                    return int(text)
            time.sleep(0.1)
        return None

    def attach(self) -> bool:
        """Re-attach to a run found on disk (§4.7 re-attach). Returns True when
        there is something to monitor (alive, or finished with results to fold)."""
        pid_file = self.case_dir / PID_NAME
        if not pid_file.exists():
            return False
        self._pid = int(pid_file.read_text().strip() or 0)
        self._offset = 0
        self.parser = SolverLogParser()
        alive = self._pid_alive()
        if alive:
            self.line.emit(f"FlowDesk: re-attached to running solver (pid {self._pid})")
            self._set_state(RunState.RUNNING)
        self._timer.start()  # one poll folds the log even if already finished
        return True

    def detach(self) -> None:
        """Stop monitoring without touching the process (used by tests/the
        'GUI died' scenario - the solver keeps running)."""
        self._timer.stop()

    def stop(self) -> None:
        """Graceful stop (§4.7): stopAt writeNow via runTimeModifiable, then
        SIGTERM after a 30 s grace period."""
        from foamlib import FoamFile

        try:
            FoamFile(self.case_dir / "system" / "controlDict")["stopAt"] = "writeNow"
            self.line.emit("FlowDesk: requested graceful stop (stopAt writeNow); "
                           "SIGTERM in 30 s if still running")
        except Exception as exc:
            self.line.emit(f"FlowDesk: could not rewrite controlDict ({exc}); "
                           "sending SIGTERM")
        QTimer.singleShot(30_000, self._term_if_alive)

    def kill(self) -> None:
        if self._pid is not None:
            self._bash(f"kill -KILL -{self._pid} 2>/dev/null; kill -KILL {self._pid} "
                       "2>/dev/null; true")
            self.line.emit("FlowDesk: sent SIGKILL")

    def _term_if_alive(self) -> None:
        if self._state in (RunState.RUNNING, RunState.DECOMPOSING,
                           RunState.RECONSTRUCTING) and self._pid_alive():
            self._bash(f"kill -TERM -{self._pid} 2>/dev/null; kill -TERM {self._pid} "
                       "2>/dev/null; true")
            self.line.emit("FlowDesk: grace period elapsed - sent SIGTERM")

    # ------------------------------------------------------------------ internals

    def _linux_case(self):
        if self.env.native:
            return self.case_dir
        return wsl.windows_to_wsl_path(PureWindowsPath(self.case_dir),
                                       self.env.distro or "")

    def _bash(self, command: str):
        if self.env.native or sys.platform != "win32":
            import subprocess

            return subprocess.run(["bash", "-lc", command], capture_output=True,
                                  text=True, timeout=60)
        return wsl.run(command, distro=self.env.distro, timeout=60)

    def _pid_alive(self) -> bool:
        if self._pid is None:
            return False
        return self._bash(f"kill -0 {self._pid} 2>/dev/null").returncode == 0

    def _poll(self) -> None:
        log = self.case_dir / LOG_NAME
        if log.exists():
            size = log.stat().st_size
            if size > self._offset:
                with log.open("r", encoding="utf-8", errors="replace") as f:
                    f.seek(self._offset)
                    chunk = f.read()
                    self._offset = f.tell()
                for text in chunk.splitlines():
                    self.parser.feed(text)
                    self.line.emit(text)
                self._apply_marker()

        exit_file = self.case_dir / EXIT_NAME
        if exit_file.exists():
            self._timer.stop()
            code = (exit_file.read_text().strip() or "1")
            ok = code == "0" and not self.parser.fatal_seen
            if self._state is not RunState.STOPPED:
                self._set_state(RunState.DONE if ok else RunState.FAILED)
            self.finished.emit(ok)
            return

        # Liveness check throttled to ~3s: each check spawns a wsl.exe, and the
        # periodic WSL touch also keeps the VM from idle-stopping mid-run.
        self._poll_count += 1
        if self._poll_count % 12 == 0 and self._state in (
                RunState.RUNNING, RunState.DECOMPOSING, RunState.RECONSTRUCTING) \
                and not self._pid_alive():
            # process vanished without writing an exit code: killed
            self._timer.stop()
            self._set_state(RunState.STOPPED)
            self.line.emit("FlowDesk: solver process is gone (killed or crashed) - "
                           "no exit code was written")
            self.finished.emit(False)

    def _apply_marker(self) -> None:
        marker = self.parser.state_marker
        mapping = {
            "decomposing": RunState.DECOMPOSING,
            "running": RunState.RUNNING,
            "reconstructing": RunState.RECONSTRUCTING,
            "done": RunState.DONE,
            "failed": RunState.FAILED,
        }
        if marker in mapping and self._state not in (RunState.DONE, RunState.FAILED,
                                                     RunState.STOPPED):
            target = mapping[marker]
            if target is not self._state and target not in (RunState.DONE,
                                                            RunState.FAILED):
                self._set_state(target)

    def _set_state(self, state: RunState) -> None:
        self._state = state
        self.state_changed.emit(state)
