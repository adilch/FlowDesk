"""M3 gate: weir STL -> quality-green mesh entirely in-GUI;
15-minute-journey steps 1-5 (PRD §3.4) driven through the real widgets."""

from __future__ import annotations

from pathlib import Path

import pytest
import pyvista as pv

from flowdesk.app import projects
from flowdesk.model.findings import Stage
from flowdesk.model.mesh import LayerSpec, SurfaceRefinement
from flowdesk.platform.commands import probe_environment
from flowdesk.ui.stages.geometry import GeometryStage
from flowdesk.ui.stages.mesh import MeshStage
from flowdesk.ui.stages.snappy_panel import (
    format_region_dims,
    parse_region_dims,
)

_ENV = probe_environment()

requires_openfoam = pytest.mark.skipif(
    not _ENV.available, reason=f"OpenFOAM not reachable: {_ENV.detail}")


def make_weir_stl(path: Path) -> Path:
    """A watertight box weir, proud of the channel floor/walls (no coplanar faces)."""
    box = pv.Box(bounds=(0.9, 1.1, -0.05, 0.65, -0.05, 0.3))
    box.extract_surface().triangulate().save(str(path))
    return path


# ----------------------------------------------------------- region dims helpers


def test_region_dims_roundtrip() -> None:
    from flowdesk.model.mesh import BoxRegion, CylinderRegion, RefineRegion, SphereRegion

    cases = [
        RefineRegion(name="b", geometry=BoxRegion(min=(0, -0.5, 0), max=(1.5, 0.5, 0.6))),
        RefineRegion(name="s", geometry=SphereRegion(centre=(1, 0, 0.3), radius=0.4)),
        RefineRegion(name="c", geometry=CylinderRegion(
            point1=(0, 0, 0), point2=(0, 0, 1), radius=0.2)),
    ]
    for region in cases:
        text = format_region_dims(region)
        parsed = parse_region_dims(region.geometry.shape, text)
        assert parsed == region.geometry


def test_parse_region_dims_rejects_garbage() -> None:
    assert parse_region_dims("box", "nonsense") is None
    assert parse_region_dims("sphere", "(1 2 3)") is None  # missing radius


# ----------------------------------------------------------------- the M3 gate


@requires_openfoam
def test_weir_journey_steps_1_to_5(qtbot, tmp_path) -> None:
    """§3.4 steps 1-5: new project -> import STL -> auto background mesh ->
    refinement defaults + auto locationInMesh -> pipeline -> quality report."""
    # Step 1: New Project
    session = projects.create_project("weir-gate", tmp_path, "Empty case")

    # Step 3: import weir.stl; diagnostics
    weir = make_weir_stl(tmp_path / "weir_structure.stl")
    geo_stage = GeometryStage(session)
    qtbot.addWidget(geo_stage)
    geo_stage.import_stl(weir)  # extent 0.7 m: no units prompt
    surface = session.model.geometry.surfaces[0]
    assert surface.name == "weir_structure"
    assert surface.diagnostics.watertight

    # Step 4: accept auto background mesh; refinement defaults; auto locationInMesh
    mesh_stage = MeshStage(session, _ENV)
    qtbot.addWidget(mesh_stage)
    assert mesh_stage.tabs.isTabEnabled(1)  # Refinement tab unlocked by geometry
    mesh_stage.background.fit_to_geometry()

    # speedier-than-default levels for CI walltime; layers on to exercise reporting
    session.model.mesh.snappy.surfaces = [SurfaceRefinement(
        surface="weir_structure", level_min=1, level_max=2,
        layers=LayerSpec(n_layers=2),
    )]
    mesh_stage.snappy.refresh_from_model()

    mesh_stage.snappy.suggest_location()
    assert session.model.mesh.snappy.location_in_mesh is not None
    assert mesh_stage.snappy.diagnose_location() is None

    # Step 5: run mesh pipeline; checkMesh traffic-light report
    log: list[str] = []
    mesh_stage.generate()
    assert mesh_stage.runner is not None, "pipeline did not start (validation failed?)"
    mesh_stage.runner.line.connect(lambda t, s: log.append(f"[{s}] {t}"))
    with qtbot.waitSignal(mesh_stage.mesh_completed, timeout=600_000) as blocker:
        pass
    tail = "\n".join(log[-40:])
    assert blocker.args == [True], f"mesh pipeline failed; log tail:\n{tail}"

    result = session.model.mesh.result
    assert result is not None
    assert result.quality.mesh_ok, "checkMesh did not report Mesh OK"
    assert result.quality.negative_volume_cells == 0
    assert result.cell_count > 5000  # snapped + refined well beyond background
    patch_names = {p.name for p in result.patches}
    assert "weir_structure" in patch_names  # snappy created the surface patch

    # Layer coverage parsed and reported (§4.3.3)
    assert result.layer_coverage, "snappy layer summary was not parsed"
    weir_cov = next(c for c in result.layer_coverage if c.surface == "weir_structure")
    assert weir_cov.n_faces > 0

    # Quality-green gate: no fail verdicts
    from flowdesk.exec.parsers import verdict

    assert verdict("max_non_ortho", result.quality.max_non_ortho) != "fail"
    assert verdict("max_skewness", result.quality.max_skewness) != "fail"

    # Staleness: BC stage flagged with the new patch in the diff
    assert session.staleness.is_stale(Stage.BOUNDARIES)
    assert "weir_structure" in session.staleness.reason(Stage.BOUNDARIES)

    # Persisted: a reload sees the meshed state (and the case dir is vanilla OF)
    reloaded = projects.open_project(session.case_dir)
    assert reloaded.model.mesh.result.cell_count == result.cell_count
    assert (session.case_dir / "system" / "snappyHexMeshDict").exists()
    # BCs not yet assigned -> the scoped write produced no BC field files
    # (0/ may hold snappy's cellLevel debug fields from writeFlags; that's fine)
    assert not (session.case_dir / "0" / "U").exists()
    assert not (session.case_dir / "0" / "p").exists()
