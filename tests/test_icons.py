"""SVG icon set renders to non-null themed QIcons."""

from __future__ import annotations

import pytest


@pytest.fixture(scope="module", autouse=True)
def _app():
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


def test_all_icons_render() -> None:
    from flowdesk.ui import icons

    for name in icons._ICONS:
        ic = icons.icon(name, "#E8EDF2", 20)
        assert not ic.isNull(), name
        assert ic.availableSizes(), name


def test_every_stage_has_an_icon() -> None:
    from flowdesk.model.findings import Stage
    from flowdesk.ui import icons

    for stage in Stage:
        assert stage.value in icons._ICONS, f"no icon for stage {stage.value}"


def test_icon_is_cached() -> None:
    from flowdesk.ui import icons

    a = icons.icon("mesh", "#E8EDF2", 20)
    b = icons.icon("mesh", "#E8EDF2", 20)
    assert a is b  # lru_cache returns the same QIcon
