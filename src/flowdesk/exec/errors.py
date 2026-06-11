"""Error-explanation layer v1 (PRD §4.7): pattern -> plain-language explanation.

The verbatim FOAM error is always shown; the explanation is layered on top.
Unmatched errors get the honest default - never a fake explanation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

RULES_FILE = Path(__file__).parent / "error_explanations.yaml"

HONEST_DEFAULT = (
    "FlowDesk doesn't recognize this error. The full OpenFOAM message above "
    "is authoritative."
)


@dataclass(frozen=True)
class Explanation:
    pattern: re.Pattern[str]
    explanation: str


def load_rules(path: Path = RULES_FILE) -> list[Explanation]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    return [Explanation(re.compile(r["pattern"], re.DOTALL), r["explanation"])
            for r in raw]


_RULES: list[Explanation] | None = None


def explain(error_text: str) -> str:
    """Plain-language explanation for a FOAM error block, or the honest default."""
    global _RULES
    if _RULES is None:
        _RULES = load_rules()
    for rule in _RULES:
        if rule.pattern.search(error_text):
            return rule.explanation
    return HONEST_DEFAULT
