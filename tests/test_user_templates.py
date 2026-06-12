"""Save-as-template: store a finished case and instantiate it into a new project."""

from __future__ import annotations

import pytest

from flowdesk.app import projects, user_templates
from flowdesk.model.mesh import MeshResult, QualityReport


@pytest.fixture(autouse=True)
def _isolated_templates(tmp_path, monkeypatch):
    monkeypatch.setattr(user_templates, "templates_dir",
                        lambda: tmp_path / "templates")


def test_save_and_list_roundtrip(tmp_path) -> None:
    session = projects.create_project("src", tmp_path / "p", "Lid-driven cavity")
    t = user_templates.save_as_template(
        session.model, session.case_dir, "My cavity", "a tuned cavity")
    assert t.name == "My cavity"
    assert t.solver == "simpleFoam"

    listed = user_templates.list_user_templates()
    assert [x.name for x in listed] == ["My cavity"]
    assert listed[0].description == "a tuned cavity"


def test_template_strips_mesh_result(tmp_path) -> None:
    session = projects.create_project("src", tmp_path / "p", "Lid-driven cavity")
    session.model.mesh.result = MeshResult(cell_count=999,
                                           quality=QualityReport(mesh_ok=True))
    user_templates.save_as_template(session.model, session.case_dir, "T")
    t = user_templates.get_user_template("T")
    model = user_templates.instantiate(t, "new", tmp_path / "out")
    assert model.mesh.result is None  # a template carries settings, not a mesh


def test_instantiate_preserves_settings(tmp_path) -> None:
    session = projects.create_project("src", tmp_path / "p", "Lid-driven cavity")
    session.model.run.max_iterations = 1234
    session.model.mesh.block.cells = (33, 33, 1)
    user_templates.save_as_template(session.model, session.case_dir, "Tuned")

    t = user_templates.get_user_template("Tuned")
    model = user_templates.instantiate(t, "fresh", tmp_path / "out")
    assert model.meta.name == "fresh"
    assert model.run.max_iterations == 1234
    assert model.mesh.block.cells == (33, 33, 1)


def test_template_copies_geometry(tmp_path) -> None:
    session = projects.create_project("breach", tmp_path / "p", "Dam break (3D breach)")
    assert session.model.geometry.surfaces  # has the generated dam
    t = user_templates.save_as_template(session.model, session.case_dir, "DamT")
    assert t.has_geometry
    assert (t.path / "geometry" / "dam.stl").exists()

    out = tmp_path / "out"
    out.mkdir()
    user_templates.instantiate(t, "dam2", out)
    assert (out / "constant" / "triSurface" / "dam.stl").exists()


def test_create_project_from_user_template(tmp_path) -> None:
    session = projects.create_project("src", tmp_path / "p", "Open channel")
    user_templates.save_as_template(session.model, session.case_dir, "Channel preset")

    # create_project must accept a user-template name and build a runnable case
    new = projects.create_project("chan2", tmp_path / "n", "Channel preset")
    assert new.model.meta.name == "chan2"
    assert new.model.physics.solver == session.model.physics.solver
    assert (new.case_dir / "system" / "controlDict").exists()


def test_delete_template(tmp_path) -> None:
    session = projects.create_project("src", tmp_path / "p", "Lid-driven cavity")
    user_templates.save_as_template(session.model, session.case_dir, "Gone")
    assert user_templates.get_user_template("Gone") is not None
    assert user_templates.delete_template("Gone")
    assert user_templates.get_user_template("Gone") is None
    assert not user_templates.delete_template("Gone")  # already gone


def test_empty_name_rejected(tmp_path) -> None:
    session = projects.create_project("src", tmp_path / "p", "Lid-driven cavity")
    with pytest.raises(ValueError, match="empty"):
        user_templates.save_as_template(session.model, session.case_dir, "  ")
