"""Full environment probe (PRD §8.1) + .wslconfig helper (§8.6) + ParaView detection.

Async-friendly: every probe is a plain function returning a Report row; the UI
runs them in a worker. Nothing here mutates state except write_wslconfig
(explicit user consent required by its caller).
"""

from __future__ import annotations

import configparser
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

from flowdesk.platform import wsl
from flowdesk.platform.commands import Environment


@dataclass(frozen=True)
class ProbeRow:
    component: str
    ok: bool
    detail: str
    fix_hint: str = ""  # empty = nothing to fix


@dataclass
class EnvironmentReport:
    rows: list[ProbeRow] = field(default_factory=list)

    @property
    def all_ok(self) -> bool:
        return all(r.ok for r in self.rows)


def full_probe(env: Environment) -> EnvironmentReport:
    """The §8.1 sequence. Fast (<3 s when WSL is up); call from a worker thread."""
    report = EnvironmentReport()
    if sys.platform == "win32":
        status = wsl.probe()
        report.rows.append(ProbeRow(
            "WSL2", status.installed,
            status.detail if not status.installed
            else f"installed, distro: {status.default_distro}",
            "" if status.installed else "Install WSL2 (admin + possible reboot)"))
        if not status.installed:
            return report  # nothing else is probeable

    report.rows.append(ProbeRow(
        "OpenFOAM v2506", env.available, env.detail,
        "" if env.available else "Install OpenFOAM v2506 into the distro"))
    if not env.available:
        return report

    mpi = _in_env(env, "mpirun --version | head -n1")
    report.rows.append(ProbeRow(
        "MPI", mpi is not None, mpi or "mpirun not found",
        "" if mpi else "openfoam2506-default should provide OpenMPI - reinstall"))

    nproc = _in_env(env, "nproc")
    ram = _in_env(env, "free -m | awk '/^Mem:/{print $2}'")
    cores = int(nproc) if nproc and nproc.isdigit() else None
    ram_mb = int(ram) if ram and ram.isdigit() else None
    report.rows.append(ProbeRow(
        "Compute resources", cores is not None,
        f"{cores or '?'} cores, {ram_mb or '?'} MB RAM visible to "
        + ("WSL" if not env.native else "the system")))

    if sys.platform == "win32":
        report.rows.append(_wslconfig_row(ram_mb))

    paraview = find_paraview()
    report.rows.append(ProbeRow(
        "ParaView", paraview is not None,
        str(paraview) if paraview else "not found",
        "" if paraview else "ParaView is free - download, or point FlowDesk at "
                            "an existing install"))
    return report


def _in_env(env: Environment, command: str) -> str | None:
    try:
        if env.native:
            import subprocess

            r = subprocess.run(["bash", "-lc", command], capture_output=True,
                               text=True, timeout=20)
        else:
            r = wsl.run(command, distro=env.distro, timeout=20)
        return r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else None
    except Exception:
        return None


# ------------------------------------------------------------------- .wslconfig


def wslconfig_path() -> Path:
    return Path(os.environ.get("USERPROFILE", str(Path.home()))) / ".wslconfig"


def read_wslconfig_limits() -> dict[str, str]:
    """memory/processors entries from [wsl2], if the file exists."""
    path = wslconfig_path()
    if not path.exists():
        return {}
    parser = configparser.ConfigParser()
    try:
        parser.read(path)
    except configparser.Error:
        return {}
    if not parser.has_section("wsl2"):
        return {}
    return {k: v for k, v in parser.items("wsl2") if k in ("memory", "processors")}


def _wslconfig_row(wsl_ram_mb: int | None) -> ProbeRow:
    limits = read_wslconfig_limits()
    if limits:
        detail = ", ".join(f"{k}={v}" for k, v in limits.items())
        return ProbeRow(".wslconfig", True, f"explicit limits: {detail}")
    # No file: WSL defaults to 50% of host RAM - can starve big meshes (§8.6)
    detail = "not present - WSL defaults to 50% of host RAM"
    if wsl_ram_mb:
        detail += f" (currently {wsl_ram_mb} MB visible)"
    return ProbeRow(".wslconfig", True, detail,
                    "Optionally raise the memory cap for large meshes")


def recommended_wslconfig(host_ram_mb: int) -> str:
    """80% of host RAM, all processors. Written only with explicit consent;
    requires `wsl --shutdown` to take effect (§8.6 honesty)."""
    memory_gb = max(4, int(host_ram_mb * 0.8 / 1024))
    return (
        "# Written by FlowDesk (with your consent). Effective after: wsl --shutdown\n"
        "[wsl2]\n"
        f"memory={memory_gb}GB\n"
    )


def host_ram_mb() -> int | None:
    if sys.platform != "win32":
        return None
    try:
        import ctypes

        class MemoryStatus(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong),
                        ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong),
                        ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong),
                        ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong),
                        ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

        status = MemoryStatus()
        status.dwLength = ctypes.sizeof(MemoryStatus)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
        return int(status.ullTotalPhys / (1024 * 1024))
    except Exception:
        return None


def write_wslconfig(content: str) -> Path:
    """Write ~/.wslconfig. Caller must have obtained user consent and must tell
    the user a `wsl --shutdown` restart is needed."""
    path = wslconfig_path()
    if path.exists():
        backup = path.with_suffix(".wslconfig.flowdesk-backup")
        backup.write_bytes(path.read_bytes())
    path.write_text(content, encoding="utf-8", newline="\n")
    return path


# -------------------------------------------------------------------- ParaView


def find_paraview(extra_candidates: list[Path] | None = None) -> Path | None:
    """Windows ParaView detection (§8.5): Program Files glob + optional manual path."""
    candidates = list(extra_candidates or [])
    if sys.platform == "win32":
        for root in (os.environ.get("PROGRAMFILES", r"C:\Program Files"),
                     os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")):
            base = Path(root)
            if base.exists():
                candidates += sorted(base.glob("ParaView*/bin/paraview.exe"),
                                     reverse=True)  # newest version first
    else:
        import shutil

        which = shutil.which("paraview")
        if which:
            candidates.append(Path(which))
    for c in candidates:
        if c and Path(c).exists():
            return Path(c)
    return None


def launch_paraview(paraview_exe: Path, case_foam: Path) -> None:
    """Open the case in Windows ParaView against the \\\\wsl$ (or local) path (§8.5)."""
    import subprocess

    case_foam.touch()
    creationflags = 0x00000008 if sys.platform == "win32" else 0  # DETACHED_PROCESS
    subprocess.Popen([str(paraview_exe), str(case_foam)],
                     creationflags=creationflags,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


PARAVIEW_DOWNLOAD_URL = "https://www.paraview.org/download/"
