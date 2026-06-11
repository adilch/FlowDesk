"""Environment panel (PRD §8.1/§8.2): probe rows + guided fix flows.

Live progress, not docs: install actions stream their output into the panel.
Transparency applies to setup too - the exact commands are always shown.
"""

from __future__ import annotations

import sys

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from flowdesk.exec.pipeline import PipelineRunner, Step
from flowdesk.platform import environment as env_probe
from flowdesk.platform.commands import Environment, probe_environment
from flowdesk.ui.components import Banner, LogView, TrafficLightRow, make_button

OPENFOAM_INSTALL = (
    "curl -s https://dl.openfoam.com/add-debian-repo.sh | sudo bash && "
    "sudo DEBIAN_FRONTEND=noninteractive apt-get install -y openfoam2506-default"
)


class _ProbeWorker(QThread):
    done = pyqtSignal(object)  # EnvironmentReport

    def __init__(self, env: Environment, parent=None):
        super().__init__(parent)
        self._env = env

    def run(self) -> None:
        self.done.emit(env_probe.full_probe(self._env))


class EnvironmentDialog(QDialog):
    """Settings → Environment: the one place every 'Fix…' link lands (§4.1)."""

    environment_changed = pyqtSignal()

    def __init__(self, env: Environment, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("FlowDesk — Environment")
        self.resize(640, 560)
        self.env = env

        layout = QVBoxLayout(self)
        title = QLabel("Environment")
        title.setProperty("role", "title")
        layout.addWidget(title)

        self._rows_box = QVBoxLayout()
        layout.addLayout(self._rows_box)

        self._actions_box = QHBoxLayout()
        layout.addLayout(self._actions_box)

        self.log = LogView()
        self.log.setMaximumHeight(220)
        layout.addWidget(self.log)

        self._banner_slot = QVBoxLayout()
        layout.addLayout(self._banner_slot)

        refresh_btn = make_button("Re-probe")
        refresh_btn.clicked.connect(self.probe)
        layout.addWidget(refresh_btn)

        self._worker: _ProbeWorker | None = None
        self._runner: PipelineRunner | None = None
        self.probe()

    # ------------------------------------------------------------------ probing

    def probe(self) -> None:
        self._clear(self._rows_box)
        loading = QLabel("Probing environment…")
        loading.setProperty("role", "caption")
        self._rows_box.addWidget(loading)
        self._worker = _ProbeWorker(self.env, self)
        self._worker.done.connect(self._show_report)
        self._worker.start()

    def _show_report(self, report: env_probe.EnvironmentReport) -> None:
        self._clear(self._rows_box)
        self._clear(self._actions_box)
        for row in report.rows:
            verdict = "pass" if row.ok else "fail"
            self._rows_box.addWidget(TrafficLightRow(row.component, row.detail, verdict))
            if row.fix_hint:
                hint = QLabel(f"    ↳ {row.fix_hint}")
                hint.setProperty("role", "caption")
                self._rows_box.addWidget(hint)

        by_name = {r.component: r for r in report.rows}
        if sys.platform == "win32" and not by_name.get(
                "WSL2", env_probe.ProbeRow("", True, "")).ok:
            btn = make_button("Install WSL2 (admin + possible reboot)", "primary")
            btn.clicked.connect(self._install_wsl)
            self._actions_box.addWidget(btn)
        elif not by_name.get("OpenFOAM v2506",
                             env_probe.ProbeRow("", True, "")).ok:
            btn = make_button("Install OpenFOAM v2506 into the distro", "primary")
            btn.clicked.connect(self._install_openfoam)
            self._actions_box.addWidget(btn)

        wslconfig = by_name.get(".wslconfig")
        if wslconfig is not None and wslconfig.fix_hint:
            btn = make_button("Write recommended .wslconfig…")
            btn.clicked.connect(self._write_wslconfig)
            self._actions_box.addWidget(btn)
        self._actions_box.addStretch()

    # ------------------------------------------------------------------ fix flows

    def _install_wsl(self) -> None:
        """§8.2: wsl --install elevated; the reboot cannot be hidden, only said."""
        self.log.append_line("FlowDesk: running elevated 'wsl --install "
                             "--no-distribution' — approve the UAC prompt.")
        import subprocess

        try:
            subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "Start-Process wsl.exe -ArgumentList '--install',"
                 "'--no-distribution' -Verb RunAs -Wait"],
                timeout=600, check=False)
            self.log.append_line("FlowDesk: install finished. If Windows asks for "
                                 "a reboot, reboot and reopen FlowDesk - setup "
                                 "resumes here.")
        except Exception as exc:
            self.log.append_line(f"FlowDesk: install failed to launch: {exc}")
        self.probe()

    def _install_openfoam(self) -> None:
        """§8.2: ESI's documented apt route, output streamed, commands shown."""
        from flowdesk.platform import wsl

        distro = self.env.distro or wsl.probe().default_distro
        if distro is None:
            self.log.append_line("FlowDesk: no WSL distro found - install "
                                 "Ubuntu first (wsl --install -d Ubuntu-24.04).")
            return
        self.log.append_line(f"FlowDesk: running in {distro} (needs sudo):")
        self.log.append_line(f"  {OPENFOAM_INSTALL}")
        argv = ["wsl.exe", "-d", distro, "--", "bash", "-lc", OPENFOAM_INSTALL]
        self._runner = PipelineRunner(self)
        self._runner.line.connect(lambda text, _s: self.log.append_line(text))
        self._runner.finished.connect(lambda ok: (
            self.log.append_line("FlowDesk: OpenFOAM install "
                                 + ("complete." if ok else "FAILED - see above.")),
            self.probe(),
            self.environment_changed.emit(),
        ))
        self._runner.run([Step(name="install openfoam2506", argv=argv)])

    def _write_wslconfig(self) -> None:
        """§8.6 helper: explicit consent, backup kept, restart honestly stated."""
        ram = env_probe.host_ram_mb()
        if ram is None:
            self.log.append_line("FlowDesk: could not read host RAM - not writing.")
            return
        content = env_probe.recommended_wslconfig(ram)
        path = env_probe.write_wslconfig(content)
        self.log.append_line(f"FlowDesk: wrote {path} (backup kept alongside):")
        for line in content.strip().splitlines():
            self.log.append_line(f"  {line}")
        self._banner_slot.addWidget(Banner(
            "Takes effect after WSL restarts: run 'wsl --shutdown' when no "
            "solver is running, then reopen FlowDesk.", "info"))

    # ------------------------------------------------------------------ util

    @staticmethod
    def _clear(box) -> None:
        while box.count():
            item = box.takeAt(0)
            if item.widget():
                item.widget().deleteLater()


def refresh_environment() -> Environment:
    return probe_environment()
