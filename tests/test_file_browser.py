"""File browser/editor (§4.9 UI): ownership banners, read-only sidecar, highlighting."""

from __future__ import annotations

from pathlib import Path

from flowdesk.foam import writer
from flowdesk.model.case import CaseModel
from flowdesk.ui.file_browser import FileBrowserWidget, OpenFoamHighlighter


def _written_case(model: CaseModel, case_dir: Path) -> Path:
    writer.write_case(model.validated(), case_dir)
    return case_dir


def _banner_texts(browser: FileBrowserWidget) -> str:
    return " ".join(
        browser._banner_slot.itemAt(i).widget().text()
        for i in range(browser._banner_slot.count())
    )


def test_open_managed_file_shows_managed_banner(qtbot, box_model, tmp_path) -> None:
    case = _written_case(box_model, tmp_path)
    browser = FileBrowserWidget(case)
    qtbot.addWidget(browser)
    browser.open_file(case / "system" / "controlDict")
    assert not browser._editor.isReadOnly()
    assert browser._save_btn.isEnabled()
    assert "Managed by FlowDesk" in _banner_texts(browser)


def test_sidecar_is_read_only(qtbot, box_model, tmp_path) -> None:
    case = _written_case(box_model, tmp_path)
    browser = FileBrowserWidget(case)
    qtbot.addWidget(browser)
    browser.open_file(case / "flowdesk.json")
    assert browser._editor.isReadOnly()
    assert not browser._save_btn.isEnabled()


def test_user_owned_keys_banner(qtbot, box_model, tmp_path) -> None:
    case = _written_case(box_model, tmp_path)
    fv = case / "system" / "fvSolution"
    fv.write_text(fv.read_text().replace("U               0.5;", "U               0.9;"),
                  encoding="utf-8", newline="\n")
    writer.write_case(box_model.validated(), case)  # reconciles -> user-owned key

    browser = FileBrowserWidget(case)
    qtbot.addWidget(browser)
    browser.open_file(fv)
    assert "relaxationFactors" in _banner_texts(browser)


def test_highlighter_constructs(qtbot) -> None:
    from PyQt6.QtWidgets import QPlainTextEdit

    edit = QPlainTextEdit()
    qtbot.addWidget(edit)
    OpenFoamHighlighter(edit.document())
    edit.setPlainText('FoamFile { version 2.0; }\n// comment\nnu [0 2 -1 0 0 0 0] 1e-06;\n')
