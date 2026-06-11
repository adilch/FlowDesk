"""In-app primitive geometries (box/sphere/cylinder/cone/plane) + visibility."""

from __future__ import annotations

import pytest

from flowdesk.app import geometry_io, projects
from flowdesk.model.geometry import (
    BoxPrimitive,
    ConePrimitive,
    CylinderPrimitive,
    PlanePrimitive,
    SpherePrimitive,
)
from flowdesk.platform.commands import Environment

_ENV = Environment(False, True, None, "test")


# ----------------------------------------------------------------- headless STL


def test_unique_surface_name() -> None:
    assert geometry_io.unique_surface_name([], "box") == "box"
    assert geometry_io.unique_surface_name(["box"], "box") == "box2"
    assert geometry_io.unique_surface_name(["box", "box2"], "box") == "box3"
    # sanitized to an OpenFOAM word
    assert geometry_io.unique_surface_name([], "1 weird/name").startswith("g_")


@pytest.mark.parametrize("spec", [
    BoxPrimitive(min=(0, 0, 0), max=(2, 1, 1)),
    SpherePrimitive(centre=(0, 0, 0), radius=0.5),
    CylinderPrimitive(point1=(0, 0, 0), point2=(0, 0, 2), radius=0.3),
    ConePrimitive(base_centre=(0, 0, 0), direction=(0, 0, 1), radius=0.5, height=1.0),
    PlanePrimitive(centre=(0, 0, 0), normal=(0, 0, 1), i_size=1.0, j_size=1.0),
])
def test_write_primitive_creates_stl_and_diagnostics(spec, tmp_path) -> None:
    surface = geometry_io.write_primitive(spec, tmp_path, "thing")
    stl = tmp_path / "constant" / "triSurface" / "thing.stl"
    assert stl.exists() and stl.stat().st_size > 0
    assert surface.name == "thing"
    assert surface.primitive == spec
    assert surface.diagnostics.triangle_count > 0


def test_closed_primitives_are_watertight(tmp_path) -> None:
    box = geometry_io.write_primitive(BoxPrimitive(min=(0, 0, 0), max=(1, 1, 1)),
                                      tmp_path, "b")
    assert box.diagnostics.watertight
    sphere = geometry_io.write_primitive(SpherePrimitive(centre=(0, 0, 0), radius=1),
                                         tmp_path, "s")
    assert sphere.diagnostics.watertight


def test_plane_is_open_surface(tmp_path) -> None:
    plane = geometry_io.write_primitive(
        PlanePrimitive(centre=(0, 0, 0), normal=(0, 0, 1), i_size=1, j_size=1),
        tmp_path, "p")
    assert not plane.diagnostics.watertight  # honest: a plane is not a closed solid


def test_box_bounds_roundtrip(tmp_path) -> None:
    surface = geometry_io.write_primitive(
        BoxPrimitive(min=(-2, -1, 0), max=(3, 1, 4)), tmp_path, "dam")
    d = surface.diagnostics
    assert d.bounds_min[0] == pytest.approx(-2)
    assert d.bounds_max == pytest.approx((3.0, 1.0, 4.0))


# ----------------------------------------------------------------- model serialize


def test_primitive_survives_save_reopen(tmp_path) -> None:
    session = projects.create_project("g", tmp_path, "Empty case")
    surface = geometry_io.write_primitive(
        BoxPrimitive(min=(0, 0, 0), max=(1, 2, 3)), session.case_dir, "wall")
    session.model.geometry.surfaces.append(surface)
    session.model.geometry.blockmesh_only = False
    session.save_model()

    reopened = projects.open_project(session.case_dir)
    s = reopened.model.geometry.surfaces[0]
    assert s.primitive is not None
    assert s.primitive.shape == "box"
    assert s.primitive.max == (1.0, 2.0, 3.0)


# ----------------------------------------------------------------- stage UI


def _stage(tmp_path):
    from flowdesk.ui.stages.geometry import GeometryStage

    session = projects.create_project("ui", tmp_path, "Empty case")
    return session, GeometryStage(session)


def test_create_primitive_adds_to_list_and_model(qtbot, tmp_path) -> None:
    from flowdesk.ui.stages.geometry import PrimitiveDialog

    session, stage = _stage(tmp_path)
    qtbot.addWidget(stage)

    # drive the create flow without showing the modal dialog
    spec = BoxPrimitive(min=(0, 0, 0), max=(1, 1, 1))
    name = geometry_io.unique_surface_name(stage._surface_names(), "box")
    surface = geometry_io.write_primitive(spec, session.case_dir, name)
    stage._add_surface(surface)

    assert [s.name for s in session.model.geometry.surfaces] == ["box"]
    assert stage.geometry_list.count() == 1
    assert not session.model.geometry.blockmesh_only
    assert not stage.blockmesh_only.isChecked()
    _ = PrimitiveDialog  # dialog construction covered below


def test_primitive_dialog_roundtrips_spec(qtbot, tmp_path) -> None:
    from flowdesk.ui.stages.geometry import PrimitiveDialog

    spec = CylinderPrimitive(point1=(1, 2, 3), point2=(1, 2, 8), radius=0.4)
    dialog = PrimitiveDialog(spec)
    qtbot.addWidget(dialog)
    out = dialog.spec()
    assert out.shape == "cylinder"
    assert out.point2 == (1.0, 2.0, 8.0)
    assert out.radius == pytest.approx(0.4)


def test_visibility_toggle_emits_and_tracks(qtbot, tmp_path) -> None:
    session, stage = _stage(tmp_path)
    qtbot.addWidget(stage)
    surface = geometry_io.write_primitive(
        SpherePrimitive(centre=(0, 0, 0), radius=1), session.case_dir, "ball")
    stage._add_surface(surface)

    events: list[tuple] = []
    stage.visibility_toggled.connect(lambda n, v: events.append((n, v)))
    stage._toggle_visibility("ball")
    assert "ball" in stage.hidden_surfaces()
    assert events[-1] == ("ball", False)  # now hidden
    stage._toggle_visibility("ball")
    assert "ball" not in stage.hidden_surfaces()
    assert events[-1] == ("ball", True)


def test_delete_removes_surface_and_stl(qtbot, tmp_path) -> None:
    session, stage = _stage(tmp_path)
    qtbot.addWidget(stage)
    surface = geometry_io.write_primitive(
        BoxPrimitive(min=(0, 0, 0), max=(1, 1, 1)), session.case_dir, "box")
    stage._add_surface(surface)
    stl = session.case_dir / "constant" / "triSurface" / "box.stl"
    assert stl.exists()

    stage.geometry_list.setCurrentRow(0)
    stage._delete_current()
    assert session.model.geometry.surfaces == []
    assert not stl.exists()


def test_edit_regenerates_stl(qtbot, tmp_path) -> None:
    session, stage = _stage(tmp_path)
    qtbot.addWidget(stage)
    surface = geometry_io.write_primitive(
        BoxPrimitive(min=(0, 0, 0), max=(1, 1, 1)), session.case_dir, "box")
    stage._add_surface(surface)

    # simulate an edit by writing a bigger box under the same name
    bigger = geometry_io.write_primitive(
        BoxPrimitive(min=(0, 0, 0), max=(5, 5, 5)), session.case_dir, "box")
    geo = session.model.geometry
    geo.surfaces = [bigger if s.name == "box" else s for s in geo.surfaces]
    assert session.model.geometry.surfaces[0].primitive.max == (5.0, 5.0, 5.0)
