"""App settings & recent projects, persisted to ~/.flowdesk/settings.json."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

MAX_RECENT = 12  # §4.1


@dataclass
class RecentProject:
    name: str
    path: str
    solver: str = ""
    cell_count: int = 0
    last_opened: str = ""  # ISO 8601


@dataclass
class AppSettings:
    recent: list[RecentProject] = field(default_factory=list)
    last_location: str = ""
    coach_done: bool = False  # §5.3: the tutorial overlay never repeats unless asked
    paraview_path: str = ""  # manual override when auto-detection misses

    @classmethod
    def _path(cls) -> Path:
        return Path.home() / ".flowdesk" / "settings.json"

    @classmethod
    def load(cls) -> AppSettings:
        path = cls._path()
        if not path.exists():
            return cls()
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            recent = [RecentProject(**r) for r in raw.get("recent", [])]
            return cls(recent=recent, last_location=raw.get("last_location", ""),
                       coach_done=raw.get("coach_done", False),
                       paraview_path=raw.get("paraview_path", ""))
        except (json.JSONDecodeError, TypeError):
            return cls()  # corrupted settings are not fatal

    def save(self) -> None:
        path = self._path()
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {"recent": [asdict(r) for r in self.recent],
                "last_location": self.last_location,
                "coach_done": self.coach_done,
                "paraview_path": self.paraview_path}
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(path)

    def touch_recent(self, entry: RecentProject) -> None:
        self.recent = [r for r in self.recent if r.path != entry.path]
        self.recent.insert(0, entry)
        del self.recent[MAX_RECENT:]

    def remove_recent(self, path: str) -> None:
        self.recent = [r for r in self.recent if r.path != path]
