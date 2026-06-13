"""Optional mesh refinement: snappy still snaps the geometry but adds no
refinement when disabled."""

from __future__ import annotations

from flowdesk.app import projects
from flowdesk.foam import generators
from flowdesk.platform.commands import Environment

_ENV = Environment(False, True, None, "test")


def _breach(tmp_path):
    return projects.create_project("r", tmp_path, "Dam break (3D breach)")


def test_refinement_on_by_default(tmp_path) -> None:
    session = _breach(tmp_path)
    snappy = generators.snappy_hex_mesh_dict(session.model)
    # the dam surface refines to its levels (1 2)
    assert "dam { level (1 2); }" in snappy


def test_refinement_off_zeroes_levels(tmp_path) -> None:
    session = _breach(tmp_path)
    session.model.mesh.snappy.globals.refinement_enabled = False
    snappy = generators.snappy_hex_mesh_dict(session.model)
    # snap still applies (geometry captured) but no refinement
    assert "snap            true;" in snappy
    assert "dam { level (0 0); }" in snappy
    assert "dam { level (1 2); }" not in snappy
    # feature edges not refined either
    assert "level 0; }" in snappy


def test_refinement_off_skips_regions(tmp_path) -> None:
    from flowdesk.model.mesh import BoxRegion, RefineRegion

    session = _breach(tmp_path)
    session.model.mesh.snappy.regions = [
        RefineRegion(name="box1", geometry=BoxRegion(min=(0, 0, 0), max=(1, 1, 1)),
                     level=2)]
    on = generators.snappy_hex_mesh_dict(session.model)
    assert "box1 { mode inside" in on

    session.model.mesh.snappy.globals.refinement_enabled = False
    off = generators.snappy_hex_mesh_dict(session.model)
    assert "box1" not in off  # refinement regions skipped


def test_toggle_survives_save_load(tmp_path) -> None:
    session = _breach(tmp_path)
    session.model.mesh.snappy.globals.refinement_enabled = False
    session.save_model()
    reopened = projects.open_project(session.case_dir)
    assert reopened.model.mesh.snappy.globals.refinement_enabled is False


def test_ui_toggle_disables_tables(qtbot, tmp_path) -> None:
    from flowdesk.ui.stages.mesh import MeshStage

    session = _breach(tmp_path)
    stage = MeshStage(session, _ENV)
    qtbot.addWidget(stage)
    snappy = stage.snappy
    assert snappy.refine_chk.isChecked()
    assert snappy.surface_table.isEnabled()

    snappy.refine_chk.setChecked(False)
    assert not snappy.surface_table.isEnabled()
    assert not snappy.region_table.isEnabled()
    snappy.collect_into_model()
    assert session.model.mesh.snappy.globals.refinement_enabled is False
