"""Design-system enforcement (PRD §6): no inline styles outside theme.py.

A single theme.py owns all QSS; any setStyleSheet call elsewhere is a violation.
"""

from __future__ import annotations

import re
from pathlib import Path

SRC = Path(__file__).parent.parent / "src" / "flowdesk"

# Matches an actual call site, not prose in docstrings.
_CALL = re.compile(r"\.setStyleSheet\(")


def test_no_setstylesheet_outside_theme() -> None:
    violations = []
    for py in SRC.rglob("*.py"):
        if py.name == "theme.py":
            continue
        if _CALL.search(py.read_text(encoding="utf-8")):
            violations.append(str(py.relative_to(SRC)))
    assert not violations, f"Inline styles found (only theme.py may style): {violations}"
