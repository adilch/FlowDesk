"""Build argv for OpenFOAM commands, native (Linux) or across the WSL bridge (Windows).

The execution engine feeds these to QProcess; nothing else may construct
OpenFOAM command lines (PRD §8.3/§8.4 centralization rule).
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath

from flowdesk.platform import wsl


@dataclass(frozen=True)
class Environment:
    """Where OpenFOAM lives, as discovered by probe_environment()."""

    available: bool
    native: bool  # True: Linux host; False: via WSL
    distro: str | None
    detail: str


def probe_environment() -> Environment:
    if sys.platform != "win32":
        if Path(wsl.OPENFOAM_BASHRC).exists():
            return Environment(True, True, None, "OpenFOAM v2506 (native)")
        return Environment(False, True, None, "OpenFOAM v2506 not found at "
                           + wsl.OPENFOAM_BASHRC)
    status = wsl.probe()
    if not status.installed or not status.distros:
        return Environment(False, False, None, "WSL2 is not installed")
    result = wsl.run(f"test -f {wsl.OPENFOAM_BASHRC}", timeout=30)
    if result.returncode != 0:
        return Environment(False, False, status.default_distro,
                           f"OpenFOAM v2506 not found in {status.default_distro}")
    return Environment(True, False, status.default_distro,
                       f"OpenFOAM v2506 via WSL ({status.default_distro})")


def openfoam_argv(command: str, case_dir: Path, env: Environment) -> list[str]:
    """argv that runs `command` inside the case directory with OpenFOAM sourced."""
    if not env.available:
        raise RuntimeError(f"OpenFOAM is not available: {env.detail}")
    if env.native:
        bash_line = (
            f"source {wsl.OPENFOAM_BASHRC} && "
            f"cd {wsl.shell_quote(str(case_dir))} && {command}"
        )
        return ["bash", "-lc", bash_line]
    linux_case = wsl.windows_to_wsl_path(PureWindowsPath(case_dir), env.distro or "")
    bash_line = (
        f"source {wsl.OPENFOAM_BASHRC} && "
        f"cd {wsl.shell_quote(str(linux_case))} && {command}"
    )
    argv = ["wsl.exe"]
    if env.distro:
        argv += ["-d", env.distro]
    return argv + ["--", "bash", "-lc", bash_line]


def default_projects_dir(env: Environment) -> Path:
    """§8.4 policy: on Windows, projects live on the Linux filesystem (browsable
    via \\\\wsl$); on Linux, in ~/FlowDesk."""
    if env.native or not env.distro:
        return Path.home() / "FlowDesk"
    user = wsl.run("whoami", distro=env.distro, timeout=30).stdout.strip() or "root"
    unc = wsl.wsl_to_windows_path(PurePosixPath(f"/home/{user}/flowdesk"), env.distro)
    return Path(unc)


def is_slow_location(path: Path, env: Environment) -> bool:
    """True when a Windows-drive path would be /mnt/* inside WSL (5-20x slower, §8.4)."""
    if env.native:
        return False
    s = str(path)
    return not (s.startswith("\\\\wsl$") or s.startswith("\\\\wsl.localhost"))
