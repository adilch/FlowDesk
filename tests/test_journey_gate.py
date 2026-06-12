"""M5 gate: the full 15-minute journey (PRD §3.4) end to end through the real
widgets on this machine (Windows 11 + WSL-provisioned OpenFOAM v2506).

Steps: new project -> import weir STL -> auto background mesh + refinement +
auto material point -> mesh pipeline + quality report -> physics -> BCs ->
numerics (Robust untouched) -> parallel run with live residuals -> results
slice + screenshot.
"""

from __future__ import annotations

import pytest
import pyvista as pv
from PyQt6.QtCore import Qt

from flowdesk.app import projects, results_io
from flowdesk.model.findings import Stage
from flowdesk.model.mesh import SurfaceRefinement
from flowdesk.platform.commands import probe_environment
from flowdesk.ui.stages.boundaries import BoundariesStage
from flowdesk.ui.stages.geometry import GeometryStage
from flowdesk.ui.stages.mesh import MeshStage
from flowdesk.ui.stages.numerics import NumericsStage
from flowdesk.ui.stages.physics import PhysicsStage
from flowdesk.ui.stages.results import ResultsStage
from flowdesk.ui.stages.run import RunStage
from flowdesk.ui.viewer import ViewerWidget

_ENV = probe_environment()

requires_openfoam = pytest.mark.skipif(
    not _ENV.available, reason=f"OpenFOAM not reachable: {_ENV.detail}")


def _select_patches(stage: BoundariesStage, names: set[str]) -> None:
    for i in range(stage.patch_list.count()):
        item = stage.patch_list.item(i)
        item.setSelected(item.data(Qt.ItemDataRole.UserRole) in names)


@requires_openfoam
def test_full_fifteen_minute_journey(qtbot, tmp_path) -> None:
    # --- Step 1: New Project ---
    session = projects.create_project("weir-journey", tmp_path, "Empty case")

    # --- Step 3: import weir STL; diagnostics green ---
    weir_stl = tmp_path / "weir_structure.stl"
    box = pv.Box(bounds=(0.9, 1.1, -0.05, 0.65, -0.05, 0.3))
    box.extract_surface().triangulate().save(str(weir_stl))
    geo = GeometryStage(session)
    qtbot.addWidget(geo)
    geo.import_stl(weir_stl)
    assert session.model.geometry.surfaces[0].diagnostics.watertight

    # --- Step 4-5: auto background mesh, refinement, auto point, pipeline ---
    mesh = MeshStage(session, _ENV)
    qtbot.addWidget(mesh)
    mesh.background.fit_to_geometry()
    session.model.mesh.snappy.surfaces = [
        SurfaceRefinement(surface="weir_structure", level_min=1, level_max=2)]
    mesh.snappy.refresh_from_model()
    mesh.snappy.suggest_location()
    mesh.generate()
    assert mesh.runner is not None
    with qtbot.waitSignal(mesh.mesh_completed, timeout=600_000) as blocker:
        pass
    assert blocker.args == [True], "mesh pipeline failed"
    assert session.model.mesh.result.quality.mesh_ok

    # --- Step 6: Physics - defaults (simpleFoam, k-omega SST, water) ---
    physics = PhysicsStage(session)
    qtbot.addWidget(physics)
    physics.u_ref.set_value(2.0)
    physics.apply()
    assert session.model.physics.solver == "simpleFoam"

    # --- Step 7: BCs via the patch list + forms ---
    bcs = BoundariesStage(session)
    qtbot.addWidget(bcs)
    _select_patches(bcs, {"xMin"})
    bcs.type_combo.setCurrentText("Velocity inlet")
    bcs.inlet_spec.setCurrentIndex(bcs.inlet_spec.findData("normal"))
    bcs.inlet_speed.set_value(2.0)
    bcs.assign()
    _select_patches(bcs, {"xMax"})
    bcs.type_combo.setCurrentText("Pressure outlet")
    bcs.assign()
    _select_patches(bcs, {"zMin", "weir_structure"})
    bcs.type_combo.setCurrentText("Wall (no-slip)")
    bcs.wall_moving.setChecked(False)
    bcs.assign()
    _select_patches(bcs, {"yMin", "yMax", "zMax"})
    bcs.type_combo.setCurrentText("Slip wall")
    bcs.assign()
    assert bcs.apply(), "BC apply (field-file write) failed"
    assert (session.case_dir / "0" / "U").exists()

    # --- Step 8: Numerics - Robust preset untouched ---
    numerics = NumericsStage(session)
    qtbot.addWidget(numerics)
    numerics.apply()

    # --- Step 9: Run, parallel, live residuals ---
    run = RunStage(session, _ENV)
    qtbot.addWidget(run)
    run.mode_seg._group.button(1).setChecked(True)  # parallel
    run.cores.setValue(2)
    run.max_iter.setValue(250)
    log: list[str] = []
    run.start_run()
    assert run.supervisor is not None, "run did not start"
    run.supervisor.line.connect(log.append)
    with qtbot.waitSignal(run.run_finished, timeout=600_000) as blocker:
        pass
    assert blocker.args == [True], "run failed; tail:\n" + "\n".join(log[-30:])
    assert run.supervisor.parser.residuals, "no live residuals were parsed"
    assert run._curves, "no residual curves were plotted"

    # --- Step 10: Results - slice + screenshot ---
    viewer = ViewerWidget()
    qtbot.addWidget(viewer)
    results = ResultsStage(session, viewer)
    qtbot.addWidget(results)
    results.viewer_slot.addWidget(viewer)
    results.refresh()
    assert results.results is not None, "results did not load"
    assert "U magnitude" in [results.field_combo.itemText(i)
                             for i in range(results.field_combo.count())]
    results.field_combo.setCurrentText("U magnitude")
    results.render()

    shot = results.screenshot_to(tmp_path / "journey.png", scale=1)
    assert shot.exists() and shot.stat().st_size > 4_000  # a real (non-blank) PNG

    probe_values = results_io.probe_point(results.results, (0.3, 0.3, 0.2))
    assert "U" in probe_values

    # Rail statuses: everything green enough; results enabled
    statuses = session.stage_statuses()
    assert statuses[Stage.RUN] in ("complete", "warnings")
    assert session._started(Stage.RESULTS)
