"""New Project gallery (built-in + user templates) and the save-as-template shell action."""

from __future__ import annotations

import pytest

from flowdesk.app import projects, user_templates
from flowdesk.app.settings import AppSettings
from flowdesk.platform.commands import Environment

_ENV = Environment(False, True, None, "test")


@pytest.fixture(autouse=True)
def _isolated_templates(tmp_path, monkeypatch):
    monkeypatch.setattr(user_templates, "templates_dir",
                        lambda: tmp_path / "templates")


def test_new_project_dialog_lists_builtin_and_user(qtbot, tmp_path) -> None:
    from flowdesk.ui.home import NewProjectDialog

    session = projects.create_project("src", tmp_path / "p", "Lid-driven cavity")
    user_templates.save_as_template(session.model, session.case_dir, "My preset",
                                    "a description")
    dialog = NewProjectDialog(_ENV, AppSettings(), None)
    qtbot.addWidget(dialog)

    items = [dialog.template_combo.itemText(i)
             for i in range(dialog.template_combo.count())]
    assert "Lid-driven cavity" in items  # built-in
    assert "My preset" in items  # user template

    dialog.template_combo.setCurrentText("My preset")
    assert "a description" in dialog.template_desc.text()
    assert dialog.delete_template_btn.isVisibleTo(dialog)

    dialog.template_combo.setCurrentText("Lid-driven cavity")
    assert "benchmark" in dialog.template_desc.text().lower()
    assert not dialog.delete_template_btn.isVisibleTo(dialog)


def test_dialog_delete_removes_user_template(qtbot, tmp_path) -> None:
    from flowdesk.ui.home import NewProjectDialog

    session = projects.create_project("src", tmp_path / "p", "Lid-driven cavity")
    user_templates.save_as_template(session.model, session.case_dir, "Temp1")
    dialog = NewProjectDialog(_ENV, AppSettings(), None)
    qtbot.addWidget(dialog)
    dialog.template_combo.setCurrentText("Temp1")
    dialog._delete_template()
    assert user_templates.get_user_template("Temp1") is None
    items = [dialog.template_combo.itemText(i)
             for i in range(dialog.template_combo.count())]
    assert "Temp1" not in items


def test_shell_save_as_template(qtbot, tmp_path, monkeypatch) -> None:
    from flowdesk.ui.shell import ProjectShell

    session = projects.create_project("proj", tmp_path / "p", "Open channel")
    shell = ProjectShell(session, _ENV)
    qtbot.addWidget(shell)

    # auto-accept the dialog; let the real save run
    from PyQt6.QtWidgets import QDialog

    monkeypatch.setattr(QDialog, "exec", lambda self: QDialog.DialogCode.Accepted)
    shell.save_as_template()
    assert "saved template" in shell.status_bar.text().lower()
    assert user_templates.list_user_templates()
