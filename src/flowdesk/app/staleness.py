"""Staleness propagation (PRD §5.2): directed graph over stages.

Geometry -> Mesh -> {Boundaries (patch list), Results}
Physics -> {Boundaries (field set), Numerics}
Any upstream Apply marks downstream ⟳ with a one-line diff of what changed.
"""

from __future__ import annotations

from flowdesk.model.findings import Stage

EDGES: dict[Stage, list[Stage]] = {
    Stage.GEOMETRY: [Stage.MESH],
    Stage.MESH: [Stage.BOUNDARIES, Stage.RESULTS],
    Stage.PHYSICS: [Stage.BOUNDARIES, Stage.NUMERICS],
    Stage.BOUNDARIES: [],
    Stage.NUMERICS: [],
    Stage.RUN: [Stage.RESULTS],
    Stage.RESULTS: [],
}


def downstream(stage: Stage) -> list[Stage]:
    """All stages transitively downstream of `stage` (breadth-first, no dupes)."""
    seen: list[Stage] = []
    queue = list(EDGES[stage])
    while queue:
        s = queue.pop(0)
        if s not in seen:
            seen.append(s)
            queue.extend(EDGES[s])
    return seen


class StalenessTracker:
    """Per-session record of stale stages and why ('patch list changed: + spillway')."""

    def __init__(self) -> None:
        self._stale: dict[Stage, str] = {}

    def mark_applied(self, stage: Stage, change_summary: str = "") -> list[Stage]:
        """Upstream Apply happened; returns the stages newly marked stale."""
        affected = downstream(stage)
        for s in affected:
            self._stale[s] = change_summary or f"{stage.value} changed"
        return affected

    def clear(self, stage: Stage) -> None:
        self._stale.pop(stage, None)

    def is_stale(self, stage: Stage) -> bool:
        return stage in self._stale

    def reason(self, stage: Stage) -> str:
        return self._stale.get(stage, "")


def patch_diff_summary(old: list[str], new: list[str]) -> str:
    """'patch list changed: + spillway, − xMax' (§5.2)."""
    added = [p for p in new if p not in old]
    removed = [p for p in old if p not in new]
    if not added and not removed:
        return ""
    parts = [f"+ {p}" for p in added] + [f"− {p}" for p in removed]
    return "patch list changed: " + ", ".join(parts)
