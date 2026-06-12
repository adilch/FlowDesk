"""Read runtime-monitor output (postProcessing/*) into named scalar time series.

Function objects write postProcessing/<name>/<startTime>/<file>; FlowDesk reads
them for the live plot and the Results stage. Headless and tested against the
OpenFOAM v2506 output formats.
"""

from __future__ import annotations

import re
from pathlib import Path

from flowdesk.model.monitors import (
    FieldValueMonitor,
    FlowRateMonitor,
    ForcesMonitor,
    Monitor,
    ProbesMonitor,
)

_NUM = re.compile(r"[-+]?(?:\d+\.?\d*(?:[eE][-+]?\d+)?|nan|inf)")


def _floats(line: str) -> list[float]:
    """All numeric tokens on a data line; parenthesised vectors flatten to scalars."""
    return [float(t) for t in _NUM.findall(line)]


def read_dat(path: Path) -> tuple[list[str], list[list[float]]]:
    """(column header names, numeric rows). The header is the last '#' line."""
    header: list[str] = []
    rows: list[list[float]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith("#"):
            header = s.lstrip("#").replace("(", " ").replace(")", " ").split()
            continue
        nums = _floats(s)
        if nums:
            rows.append(nums)
    return header, rows


def _time_files(base: Path, names: tuple[str, ...]) -> list[Path]:
    """All matching output files across the monitor's start-time subdirs, in
    time order (a run restarted from latestTime appends a new subdir)."""
    if not base.exists():
        return []

    def as_float(p: Path) -> float:
        try:
            return float(p.name)
        except ValueError:
            return 0.0

    files = []
    for time_dir in sorted((d for d in base.iterdir() if d.is_dir()), key=as_float):
        for n in names:
            f = time_dir / n
            if f.exists():
                files.append(f)
                break
    return files


def _scalar_series(base: Path, names: tuple[str, ...], col: int) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for f in _time_files(base, names):
        _h, rows = read_dat(f)
        for r in rows:
            if len(r) > col:
                out.append((r[0], r[col]))
    return out


def _read_coeffs(base: Path) -> dict[str, list[tuple[float, float]]]:
    files = _time_files(base, ("coefficient.dat", "forceCoeffs.dat"))
    series: dict[str, list[tuple[float, float]]] = {}
    for f in files:
        header, rows = read_dat(f)
        # header: Time Cd Cs Cl ... ; map the names we care about to columns
        names = header[1:] if header and header[0].lower().startswith("time") else header
        want = {"Cd": None, "Cl": None, "Cm": None}
        for i, nm in enumerate(names):
            if nm in want and want[nm] is None:
                want[nm] = i + 1  # +1 for the leading time column
        for r in rows:
            for key, col in want.items():
                if col is not None and len(r) > col:
                    series.setdefault(key, []).append((r[0], r[col]))
    return {k: v for k, v in series.items() if v}


def _read_probes(base: Path, mon: ProbesMonitor) -> dict[str, list[tuple[float, float]]]:
    """One series per (field, probe): scalar fields directly, vectors as magnitude."""
    series: dict[str, list[tuple[float, float]]] = {}
    n_probes = max(len(mon.locations), 1)
    for field in mon.fields:
        for f in _time_files(base, (field,)):
            _h, rows = read_dat(f)
            for r in rows:
                t = r[0]
                values = r[1:]
                comps = (len(values) // n_probes) or 1
                for pi in range(n_probes):
                    chunk = values[pi * comps:(pi + 1) * comps]
                    if not chunk:
                        continue
                    val = chunk[0] if comps == 1 else sum(c * c for c in chunk) ** 0.5
                    series.setdefault(f"{field}@p{pi}", []).append((t, val))
    return series


def monitor_series(case_dir: Path, monitor: Monitor) -> dict[str, list[tuple[float, float]]]:
    """Named scalar time series for one monitor (empty until the run writes output)."""
    base = case_dir / "postProcessing" / monitor.name
    if isinstance(monitor, ForcesMonitor):
        return _read_coeffs(base)
    if isinstance(monitor, FlowRateMonitor):
        s = _scalar_series(base, ("surfaceFieldValue.dat",), 1)
        return {"flow rate (m³/s)": s} if s else {}
    if isinstance(monitor, FieldValueMonitor):
        s = _scalar_series(base, ("volFieldValue.dat",), 1)
        return {f"{monitor.operation}({monitor.field})": s} if s else {}
    if isinstance(monitor, ProbesMonitor):
        return _read_probes(base, monitor)
    return {}
