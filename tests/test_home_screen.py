"""Redesigned landing screen: left recent list, filter, open/remove, quick-create."""

from __future__ import annotations

from pathlib import Path

import pytest

from flowdesk.app.settings import AppSettings, RecentProject
from flowdesk.platform.commands import Environment
from flowdesk.ui.home import HomeScreen, _relative_time

_ENV = Environment(True, False, "Ubuntu-24.04", "OpenFOAM v2506 via WSL")


def _settings_with_recent(tmp_path, monkeypatch) -> AppSettings:
    monkeypatch.setattr(AppSettings, "_path", classmethod(lambda cls: tmp_path / "s.json"))
    s = AppSettings()
    real = tmp_path / "proj_a"
    real.mkdir()
    s.recent = [
        RecentProject(name="proj_a", path=str(real), solver="interFoam",
                      cell_count=130000, last_opened="2026-06-11T10:00:00+00:00"),
        RecentProject(name="weir_run", path=str(tmp_path / "missing"),
                      solver="simpleFoam", cell_count=88000),
    ]
    return s


def test_recent_list_populated_compactly(qtbot, tmp_path, monkeypatch) -> None:
    home = HomeScreen(_ENV, _settings_with_recent(tmp_path, monkeypatch))
    qtbot.addWidget(home)
    assert home.recent_list.count() == 2
    # each row is a compact fixed-height item (denser than the old tall buttons)
    assert home.recent_list.item(0).sizeHint().height() <= 48


def test_filter_hides_non_matching(qtbot, tmp_path, monkeypatch) -> None:
    home = HomeScreen(_ENV, _settings_with_recent(tmp_path, monkeypatch))
    qtbot.addWidget(home)
    home.filter_edit.setText("weir")
    assert home.recent_list.item(0).isHidden()      # proj_a hidden
    assert not home.recent_list.item(1).isHidden()  # weir_run shown
    home.filter_edit.setText("")
    assert not home.recent_list.item(0).isHidden()


def test_clicking_existing_project_opens(qtbot, tmp_path, monkeypatch) -> None:
    home = HomeScreen(_ENV, _settings_with_recent(tmp_path, monkeypatch))
    qtbot.addWidget(home)
    opened: list[Path] = []
    home.open_requested.connect(opened.append)
    home._open_item(home.recent_list.item(0))  # exists
    assert opened and opened[-1].name == "proj_a"
    home._open_item(home.recent_list.item(1))  # missing -> no open
    assert len(opened) == 1


def test_remove_from_recent(qtbot, tmp_path, monkeypatch) -> None:
    settings = _settings_with_recent(tmp_path, monkeypatch)
    home = HomeScreen(_ENV, settings)
    qtbot.addWidget(home)
    path = settings.recent[1].path
    home._remove_recent(path)
    assert all(r.path != path for r in settings.recent)
    assert home.recent_list.count() == 1


def test_quick_create_emits(qtbot, tmp_path, monkeypatch) -> None:
    home = HomeScreen(_ENV, _settings_with_recent(tmp_path, monkeypatch))
    qtbot.addWidget(home)
    created: list[tuple] = []
    home.create_requested.connect(lambda n, loc, t: created.append((n, t)))
    home._quick_create("Flow over a weir")
    assert created and created[-1][1] == "Flow over a weir"
    assert created[-1][0].startswith("flow-over-a-weir")


def test_empty_recent_shows_note(qtbot, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(AppSettings, "_path", classmethod(lambda cls: tmp_path / "s.json"))
    home = HomeScreen(_ENV, AppSettings())
    qtbot.addWidget(home)
    assert home.recent_list.count() == 0
    assert home._empty_note.isVisibleTo(home)


@pytest.mark.parametrize("iso,expected", [
    ("", ""),
    ("2026-06-11T11:59:30+00:00", None),  # 'just now'-ish; just exercise the path
])
def test_relative_time_safe(iso, expected) -> None:
    out = _relative_time(iso)
    if expected is not None:
        assert out == expected
    else:
        assert isinstance(out, str)
