"""Case maintenance operations: reset results for a clean rerun.

Headless and conservative: only removes things FlowDesk (or the solver)
produced - never geometry, mesh, dictionaries, or the 0/ initial fields.
"""

from __future__ import annotations

import shutil
from pathlib import Path

# Run artifacts FlowDesk's execution engine creates
_RUN_FILES = ("log.flowdesk", "flowdesk.pid", "flowdesk.exit", "flowdesk-run.sh",
              "case.foam")


def _is_result_time_dir(path: Path) -> bool:
    """Numeric time directory other than 0 (0/ holds the initial fields)."""
    name = path.name
    return (path.is_dir() and name != "0"
            and name.replace(".", "", 1).replace("e-", "", 1).isdigit())


def resettable_items(case_dir: Path) -> list[Path]:
    """What reset_case would remove - shown to the user before confirming."""
    items: list[Path] = []
    for p in case_dir.iterdir():
        is_run_dir = p.is_dir() and (p.name.startswith("processor")
                                     or p.name == "postProcessing")
        if _is_result_time_dir(p) or is_run_dir or p.name in _RUN_FILES:
            items.append(p)
    return sorted(items)


def reset_case(case_dir: Path) -> list[str]:
    """Remove results, decomposed dirs, and run artifacts. Keeps the mesh,
    dictionaries, geometry, 0/ fields, and flowdesk.json. Returns what was
    removed (relative names), honestly reportable to the user.

    Caller is responsible for ensuring no solver is currently running."""
    removed: list[str] = []
    for item in resettable_items(case_dir):
        if item.is_dir():
            shutil.rmtree(item, ignore_errors=True)
        else:
            item.unlink(missing_ok=True)
        removed.append(item.name)
    return removed
