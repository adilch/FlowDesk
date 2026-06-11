"""Validation findings (PRD §7.4): the only source of stage chip states and the pre-run gate."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Severity(Enum):
    ERROR = "error"  # blocks stage completion / case write
    WARNING = "warning"  # allowed, shown in rail and pre-run summary
    INFO = "info"


class Stage(Enum):
    GEOMETRY = "geometry"
    MESH = "mesh"
    PHYSICS = "physics"
    BOUNDARIES = "boundaries"
    NUMERICS = "numerics"
    RUN = "run"
    RESULTS = "results"


@dataclass(frozen=True)
class Finding:
    """One validation result. Message follows the §6.5 style:
    what's wrong -> where -> how to fix; jump_target identifies the field/patch."""

    severity: Severity
    stage: Stage
    message: str
    jump_target: str = ""


def errors(findings: list[Finding]) -> list[Finding]:
    return [f for f in findings if f.severity is Severity.ERROR]


def stage_status(findings: list[Finding], stage: Stage, started: bool) -> str:
    """Map findings to the §4.0 chip state for one stage."""
    mine = [f for f in findings if f.stage is stage]
    if any(f.severity is Severity.ERROR for f in mine):
        return "invalid"
    if not started:
        return "empty"
    if any(f.severity is Severity.WARNING for f in mine):
        return "warnings"
    return "complete"
