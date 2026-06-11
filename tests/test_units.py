"""Unit-suffixed numeric entry: '200 mm' -> 0.2 m (PRD §4 conventions, §6.4)."""

from __future__ import annotations

import pytest

from flowdesk.ui.components import parse_quantity


@pytest.mark.parametrize(
    ("text", "si_unit", "expected"),
    [
        ("0.05", "m", 0.05),
        ("200 mm", "m", 0.2),
        ("2 m/s", "m/s", 2.0),
        ("1.5e-5", "m2/s", 1.5e-5),
        ("3 in", "m", 0.0762),
        ("-1.5", "m", -1.5),
        ("2e3 mm", "m", 2.0),
        ("5", "%", 5.0),
    ],
)
def test_parse_quantity(text: str, si_unit: str, expected: float) -> None:
    assert parse_quantity(text, si_unit) == pytest.approx(expected)


@pytest.mark.parametrize("text", ["", "abc", "2 furlongs", "1 2 3"])
def test_parse_quantity_rejects(text: str) -> None:
    assert parse_quantity(text, "m") is None
