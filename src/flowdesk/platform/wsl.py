"""WSL2 bridge (PRD §8.3): run commands inside the managed distro, translate paths.

All OpenFOAM invocations on Windows go through this module. No other module may
construct cross-boundary paths or wsl.exe command lines.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import PurePosixPath, PureWindowsPath

OPENFOAM_BASHRC = "/usr/lib/openfoam/openfoam2506/etc/bashrc"

# wsl.exe emits UTF-16LE by default; WSL_UTF8=1 forces UTF-8 (PRD §8.3).
_WSL_ENV = {"WSL_UTF8": "1"}


@dataclass(frozen=True)
class WslStatus:
    installed: bool
    default_distro: str | None
    distros: tuple[str, ...]
    detail: str  # human-readable probe summary, surfaced honestly in the env panel


def probe() -> WslStatus:
    """Detect WSL availability and distros. Never raises; absence is a result, not an error."""
    import os

    env = {**os.environ, **_WSL_ENV}
    try:
        result = subprocess.run(
            ["wsl.exe", "--list", "--quiet"],
            capture_output=True,
            text=True,
            timeout=10,
            env=env,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return WslStatus(False, None, (), f"wsl.exe not available: {exc}")

    if result.returncode != 0:
        message = (result.stdout + result.stderr).strip()
        return WslStatus(False, None, (), message or "WSL is not installed")

    distros = tuple(line.strip() for line in result.stdout.splitlines() if line.strip())
    default = distros[0] if distros else None
    return WslStatus(True, default, distros, f"{len(distros)} distro(s) found")


def run(
    command: str,
    distro: str | None = None,
    cwd: PurePosixPath | None = None,
    source_openfoam: bool = False,
    timeout: float | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a shell command inside WSL via `bash -lc`, streaming-compatible.

    This is the synchronous form used by probes and tests; the execution engine
    (flowdesk.exec) wraps the same command construction in a supervised QProcess.
    """
    import os

    parts = []
    if source_openfoam:
        parts.append(f"source {OPENFOAM_BASHRC}")
    if cwd is not None:
        parts.append(f"cd {shell_quote(str(cwd))}")
    parts.append(command)
    bash_line = " && ".join(parts)

    argv = ["wsl.exe"]
    if distro:
        argv += ["-d", distro]
    argv += ["--", "bash", "-lc", bash_line]

    env = {**os.environ, **_WSL_ENV}
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout, env=env)


def shell_quote(s: str) -> str:
    """POSIX single-quote escaping for path/argument safety inside bash -lc."""
    return "'" + s.replace("'", "'\\''") + "'"


def windows_to_wsl_path(path: PureWindowsPath, distro: str) -> PurePosixPath:
    """C:\\Users\\x -> /mnt/c/Users/x. For \\\\wsl$ UNC paths, strip back to the Linux path."""
    s = str(path)
    unc_prefixes = (f"\\\\wsl$\\{distro}", f"\\\\wsl.localhost\\{distro}")
    for prefix in unc_prefixes:
        if s.startswith(prefix):
            remainder = s[len(prefix):].replace("\\", "/")
            return PurePosixPath(remainder or "/")
    drive = path.drive.rstrip(":").lower()
    if not drive:
        raise ValueError(f"cannot translate relative path: {path}")
    tail = "/".join(path.parts[1:])
    return PurePosixPath(f"/mnt/{drive}/{tail}")


def wsl_to_windows_path(path: PurePosixPath, distro: str) -> PureWindowsPath:
    """/home/x -> \\\\wsl$\\<distro>\\home\\x; /mnt/c/x -> C:\\x."""
    parts = path.parts
    if len(parts) >= 3 and parts[1] == "mnt" and len(parts[2]) == 1:
        drive = parts[2].upper()
        return PureWindowsPath(f"{drive}:\\" + "\\".join(parts[3:]))
    return PureWindowsPath(f"\\\\wsl$\\{distro}" + str(path).replace("/", "\\"))
