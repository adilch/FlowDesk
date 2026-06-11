"""Live canvas previews (SimFlow-style): domain box, refinement regions,
material point, and water-init volume follow the forms as they are edited."""

from __future__ import annotations

import pytest

from flowdesk.app import projects
from flowdesk.platform.commands import Environment

_ENV = Environment(False, True, None, "test")


@pytest.fixture
def shell(qtbot, tmp_path):
    from flowdesk.ui.shell import ProjectShell

    session = projects.create_project("preview", tmp_path, "Dam break (3D breach)")
    s = ProjectShell(session, _ENV)
    qtbot.addWidget(s)
    return s


def _actor_names(shell) -> set[str]:
    return set(shell.viewer.plotter.renderer.actors.keys())


def test_physics_stage_hosts_viewer(shell) -> None:
    from flowdesk.model.findings import Stage

    shell.show_stage(Stage.PHYSICS)
    assert shell.physics_stage.viewer_slot.count() == 1
    assert shell.physics_stage.viewer_slot.itemAt(0).widget() is shell.viewer


def test_domain_box_follows_background_form(shell) -> None:
    background = shell.mesh_stage.background
    background.bounds_max.set_values((40.0, 30.0, 20.0))
    shell._preview_domain()
    assert "_domain_box" in _actor_names(shell)
    bounds = shell.viewer.plotter.renderer.actors["_domain_box"].GetBounds()
    assert bounds[1] == pytest.approx(40.0)


def test_water_column_follows_physics_form(shell) -> None:
    physics = shell.physics_stage
    assert physics.free_surface_chk.isChecked()  # breach template has it on
    physics.column_max.set_values((0.0, 30.0, 12.0))
    shell._preview_column()
    assert "_water_column" in _actor_names(shell)
    bounds = shell.viewer.plotter.renderer.actors["_water_column"].GetBounds()
    assert bounds[5] == pytest.approx(12.0)

    physics.free_surface_chk.setChecked(False)
    shell._preview_column()
    assert "_water_column" not in _actor_names(shell)


def test_region_overlay_appears_on_add(shell) -> None:
    snappy = shell.mesh_stage.snappy
    snappy._add_region("box")  # emits changed -> shell preview redraw
    names = _actor_names(shell)
    assert any(n.startswith("_region_refineBox") for n in names)


def test_location_marker_follows_edit(shell) -> None:
    snappy = shell.mesh_stage.snappy
    snappy.location_input.set_values((12.0, 10.0, 4.0))
    shell._preview_snappy()
    assert "_location_marker" in _actor_names(shell)
    assert shell.session.model.mesh.snappy.location_in_mesh == (12.0, 10.0, 4.0)


def test_table_edit_emits_changed(shell, qtbot) -> None:
    snappy = shell.mesh_stage.snappy
    snappy._add_region("box")
    fired: list[bool] = []
    snappy.changed.connect(lambda: fired.append(True))
    item = snappy.region_table.item(0, 4)  # level column
    item.setText("3")
    assert fired, "editing a region cell did not emit a live-preview signal"
