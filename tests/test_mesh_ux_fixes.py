"""Two user-reported mesh UX bugs:
1. Suggest ignored un-applied Background bounds -> 'material point outside the
   background-mesh box' even after suggesting.
2. The drawer never attached to a mesh run -> no live progress or log output.
"""

from __future__ import annotations

import pytest

from flowdesk.app import projects
from flowdesk.platform.commands import probe_environment
from flowdesk.ui.drawer import RunDrawer
from flowdesk.ui.stages.mesh import MeshStage

_ENV = probe_environment()

requires_openfoam = pytest.mark.skipif(
    not _ENV.available, reason=f"OpenFOAM not reachable: {_ENV.detail}")


def _empty_project_with_dam(tmp_path):
    """The user's exact path: Empty case, import the dam, type domain bounds
    in the form WITHOUT pressing Apply."""
    import pyvista as pv

    from flowdesk.app import geometry_io

    session = projects.create_project("scratch", tmp_path, "Empty case")
    stl = tmp_path / "dam.stl"
    pv.Box(bounds=(0.0, 2.0, -0.5, 12.0, -0.5, 12.0)).extract_surface() \
        .triangulate().save(str(stl))
    surface = geometry_io.import_surface(stl, session.case_dir, name="dam")
    session.model.geometry.surfaces = [surface]
    session.model.geometry.blockmesh_only = False
    return session


def test_suggest_sees_unapplied_background_bounds(qtbot, tmp_path) -> None:
    session = _empty_project_with_dam(tmp_path)
    stage = MeshStage(session, _ENV)
    qtbot.addWidget(stage)
    stage.refresh()

    # type the domain into the form - do NOT press Apply
    stage.background.bounds_min.set_values((-20.0, 0.0, 0.0))
    stage.background.bounds_max.set_values((30.0, 30.0, 20.0))
    for spin, n in zip(stage.background.cells, (35, 22, 15), strict=True):
        spin.setValue(n)

    stage.snappy.suggest_location()
    point = stage.snappy.location_input.value()
    lo, hi = (-20.0, 0.0, 0.0), (30.0, 30.0, 20.0)
    assert all(low < c < high for c, low, high in zip(point, lo, hi, strict=True)), \
        f"suggested point {point} not inside the typed domain"
    # and not inside the dam (x 0..2 spans the full dam height/width there)
    inside_dam = 0.0 < point[0] < 2.0 and point[1] < 12.0 and point[2] < 12.0
    assert not inside_dam


def test_region_defaults_follow_unapplied_bounds(qtbot, tmp_path) -> None:
    session = _empty_project_with_dam(tmp_path)
    stage = MeshStage(session, _ENV)
    qtbot.addWidget(stage)
    stage.refresh()
    stage.background.bounds_min.set_values((-20.0, 0.0, 0.0))
    stage.background.bounds_max.set_values((30.0, 30.0, 20.0))

    stage.snappy._add_region("box")
    region = session.model.mesh.snappy.regions[0]
    # default box derives from the typed 50 m domain, not the stale 1 m one
    assert region.geometry.max[0] - region.geometry.min[0] > 1.0


@requires_openfoam
def test_drawer_attaches_and_streams_mesh_output(qtbot, tmp_path) -> None:
    """The drawer must receive pipeline lines DURING the run, via mesh_started."""
    session = projects.create_project("cavity-log", tmp_path, "Lid-driven cavity")
    stage = MeshStage(session, _ENV)
    qtbot.addWidget(stage)
    drawer = RunDrawer()
    qtbot.addWidget(drawer)
    stage.mesh_started.connect(drawer.attach)  # exactly what the shell wires

    stage.generate()
    assert stage.runner is not None
    with qtbot.waitSignal(stage.mesh_completed, timeout=180_000) as blocker:
        pass
    assert blocker.args == [True]

    log_text = drawer.log.toPlainText()
    assert "running blockMesh" in log_text
    assert "running checkMesh" in log_text
    assert "Mesh OK" in log_text  # actual checkMesh output reached the log
    # no duplicate-attach double logging
    assert log_text.count("FlowDesk: running blockMesh") == 1
    assert drawer.progress.maximum() == 2  # blockMesh + checkMesh steps
