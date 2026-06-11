"""Smoke tests: every core component constructs and behaves under the theme (pytest-qt)."""

from __future__ import annotations

import pytest

from flowdesk.ui.components import (
    Banner,
    CollapsibleGroup,
    EmptyState,
    LogView,
    SegmentedControl,
    StatusChip,
    TrafficLightRow,
    UnitLineEdit,
    Vec3Input,
    make_button,
)
from flowdesk.ui.theme import STAGE_STATUSES, build_qss


def test_qss_builds_nonempty() -> None:
    qss = build_qss()
    assert "QPushButton" in qss
    assert "#3D9BE9" in qss  # accent token made it in


def test_buttons(qtbot) -> None:
    for variant in ("primary", "secondary", "ghost", "danger"):
        btn = make_button("X", variant)
        qtbot.addWidget(btn)


def test_unit_line_edit_normalizes_mm(qtbot) -> None:
    field = UnitLineEdit(unit="m", value=1.0)
    qtbot.addWidget(field)
    field._edit.setText("200 mm")
    field._commit()
    assert field.value() == pytest.approx(0.2)
    assert field._edit.text() == "0.2"


def test_unit_line_edit_flags_invalid(qtbot) -> None:
    field = UnitLineEdit(unit="m", value=1.0, minimum=0.0)
    qtbot.addWidget(field)
    field._edit.setText("-5")
    field._commit()
    assert field._edit.property("invalid") == "true"
    assert field.value() == 1.0  # last good value retained


def test_vec3(qtbot) -> None:
    v = Vec3Input(value=(1.0, 2.0, 3.0))
    qtbot.addWidget(v)
    assert v.value() == (1.0, 2.0, 3.0)


def test_segmented(qtbot) -> None:
    seg = SegmentedControl(["Steady", "Transient"], current=0)
    qtbot.addWidget(seg)
    assert seg.current() == 0


def test_status_chip_all_states(qtbot) -> None:
    chip = StatusChip()
    qtbot.addWidget(chip)
    for key in STAGE_STATUSES:
        chip.set_status(key)
        assert chip.property("status") == key


def test_banner_severities(qtbot) -> None:
    for severity in ("info", "warn", "error"):
        banner = Banner("message", severity)
        qtbot.addWidget(banner)
        assert banner.property("banner") == severity


def test_traffic_light(qtbot) -> None:
    for verdict in ("pass", "warn", "fail"):
        qtbot.addWidget(TrafficLightRow("metric", "1.0", verdict))


def test_collapsible_group_toggles(qtbot) -> None:
    group = CollapsibleGroup("Advanced")
    qtbot.addWidget(group)
    assert not group.body.isVisibleTo(group)
    group._toggle.setChecked(True)
    assert group.body.isVisibleTo(group)


def test_log_view_caps_lines(qtbot) -> None:
    log = LogView(max_lines=10)
    qtbot.addWidget(log)
    for i in range(50):
        log.append_line(f"line {i}")
    assert log.document().blockCount() <= 10


def test_empty_state(qtbot) -> None:
    qtbot.addWidget(EmptyState("X", "Nothing here.", "Do something"))
