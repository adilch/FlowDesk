"""Solver log parsing (PRD §4.7 monitoring table): residuals, time, Courant,
continuity, bounding/FATAL markers, and FlowDesk state markers."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_RESIDUAL = re.compile(r"Solving for (\w+), Initial residual = ([\d.eE+-]+)")
_TIME = re.compile(r"^Time = ([\d.eE+-]+)")
_COURANT = re.compile(r"Courant Number mean: ([\d.eE+-]+) max: ([\d.eE+-]+)")
_CONTINUITY = re.compile(r"continuity errors.*sum local = ([\d.eE+-]+)")
_BOUNDING = re.compile(r"^bounding (\w+),")
_FATAL = re.compile(r"FOAM FATAL")
_STATE = re.compile(r"^FLOWDESK_STATE: (\w+)")
_END = re.compile(r"^End$")


@dataclass
class SolverLogParser:
    """Feed lines; accumulates series for the live plot and flags for the UI."""

    residuals: dict[str, list[tuple[float, float]]] = field(default_factory=dict)
    times: list[float] = field(default_factory=list)
    courant_max: list[tuple[float, float]] = field(default_factory=list)
    continuity: float | None = None
    bounding_fields: set[str] = field(default_factory=set)
    fatal_seen: bool = False
    fatal_context: list[str] = field(default_factory=list)
    state_marker: str | None = None
    ended: bool = False

    _current_time: float = 0.0
    _fatal_capture: int = 0

    def feed(self, line: str) -> None:
        if self._fatal_capture > 0:
            self.fatal_context.append(line)
            self._fatal_capture -= 1

        if m := _TIME.match(line):
            self._current_time = float(m.group(1))
            self.times.append(self._current_time)
        elif m := _RESIDUAL.search(line):
            fld, value = m.group(1), float(m.group(2))
            self.residuals.setdefault(fld, []).append((self._current_time, value))
        elif m := _COURANT.search(line):
            self.courant_max.append((float(m.group(1)), float(m.group(2))))
        elif m := _CONTINUITY.search(line):
            self.continuity = float(m.group(1))
        elif m := _BOUNDING.match(line):
            self.bounding_fields.add(m.group(1))
        elif m := _STATE.match(line):
            self.state_marker = m.group(1)
        elif _FATAL.search(line):
            self.fatal_seen = True
            self.fatal_context.append(line)
            self._fatal_capture = 25  # capture the verbatim FOAM error block
        elif _END.match(line.strip()):
            self.ended = True

    @property
    def current_time(self) -> float:
        return self._current_time

    def latest_residuals(self) -> dict[str, float]:
        return {f: series[-1][1] for f, series in self.residuals.items() if series}
