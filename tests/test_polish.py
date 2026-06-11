"""M6 polish: coach marks, settings fields, bundled fonts, new templates, NFR timing."""

from __future__ import annotations

import time
from pathlib import Path

from flowdesk.app.settings import AppSettings
from flowdesk.app.templates import open_channel, pipe_flow
from flowdesk.ui.coach import CAVITY_STEPS, CoachMarks


def test_new_templates_validate_clean() -> None:
    pipe_flow("p").validated()
    open_channel("c").validated()


def test_open_channel_is_rigid_lid() -> None:
    model = open_channel("c")
    assert model.boundaries["surface"].kind == "slip"  # honest single-phase MVP
    assert model.boundaries["bed"].kind == "wall"


def test_coach_marks_step_through(qtbot) -> None:
    marks = CoachMarks()
    qtbot.addWidget(marks)
    assert marks.counter.text() == f"1/{len(CAVITY_STEPS)}"
    finished = []
    marks.finished.connect(lambda: finished.append(True))
    for _ in range(len(CAVITY_STEPS) - 1):
        marks._next()
    assert marks.next_btn.text() == "Done"
    marks._next()
    assert finished == [True]


def test_coach_marks_skip(qtbot) -> None:
    marks = CoachMarks()
    qtbot.addWidget(marks)
    finished = []
    marks.finished.connect(lambda: finished.append(True))
    marks.skip_btn.click()
    assert finished == [True]


def test_settings_new_fields_roundtrip(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(AppSettings, "_path",
                        classmethod(lambda cls: tmp_path / "s.json"))
    s = AppSettings(coach_done=True, paraview_path=r"C:\pv\paraview.exe")
    s.save()
    loaded = AppSettings.load()
    assert loaded.coach_done is True
    assert loaded.paraview_path == r"C:\pv\paraview.exe"


def test_bundled_fonts_present_and_loadable(qtbot) -> None:
    fonts_dir = (Path(__file__).parent.parent / "src" / "flowdesk" / "ui"
                 / "assets" / "fonts")
    ttfs = list(fonts_dir.glob("*.ttf"))
    assert len(ttfs) >= 2, "Inter + JetBrains Mono must ship with the app"
    assert (fonts_dir / "OFL-Inter.txt").exists()  # OFL requires license shipping
    assert (fonts_dir / "OFL-JetBrainsMono.txt").exists()

    from flowdesk.ui.theme import load_bundled_fonts

    families = load_bundled_fonts()
    assert any("Inter" in f for f in families)
    assert any("JetBrains" in f for f in families)


def test_cold_start_to_home_under_nfr(qtbot) -> None:
    """NFR §9: cold start to interactive Home <= 3 s (5 s worst). Offscreen
    construction is the controllable proxy; the env probe (network/WSL) is
    excluded by reusing a prebuilt Environment."""
    from flowdesk.app.settings import AppSettings as Settings
    from flowdesk.platform.commands import Environment
    from flowdesk.ui.home import HomeScreen

    env = Environment(True, False, "Ubuntu-24.04", "test")
    start = time.perf_counter()
    home = HomeScreen(env, Settings())
    qtbot.addWidget(home)
    elapsed = time.perf_counter() - start
    assert elapsed < 3.0, f"Home took {elapsed:.2f}s to construct"
