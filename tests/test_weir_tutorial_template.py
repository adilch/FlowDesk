"""'Flow over Weir' = the SimFlow dam-break tutorial, replicated with the real
dam.stl and the exact tutorial settings."""

from __future__ import annotations

import subprocess

import pytest

from flowdesk.app import projects, results_io
from flowdesk.platform.commands import openfoam_argv, probe_environment

_ENV = probe_environment()

requires_openfoam = pytest.mark.skipif(
    not _ENV.available, reason=f"OpenFOAM not reachable: {_ENV.detail}")


def test_matches_tutorial_settings(tmp_path) -> None:
    session = projects.create_project("w", tmp_path, "Flow over Weir")
    m = session.model
    m.validated()
    # the real tutorial geometry (not a generated box): a 2 x 30 x 15 m dam
    stl = session.case_dir / "constant" / "triSurface" / "dam.stl"
    assert stl.exists()
    d = m.geometry.surfaces[0].diagnostics
    assert d.bounds_min == (0.0, 0.0, 0.0)
    assert d.bounds_max == (2.0, 30.0, 15.0)
    # exact tutorial numbers
    assert m.physics.solver == "interFoam"
    assert (m.physics.time.end_time, m.physics.time.output_interval,
            m.physics.time.initial_dt) == (60.0, 0.5, 0.01)
    assert m.mesh.block.bounds_min == (-20.0, 0.0, 0.0)
    assert m.mesh.block.bounds_max == (30.0, 30.0, 20.0)
    assert m.mesh.block.cells == (70, 45, 30)
    assert m.mesh.snappy.location_in_mesh == (10.0, 15.0, 5.0)
    assert m.physics.free_surface.water_column_max == (0.0, 30.0, 9.0)
    # 250 m^3/s volumetric inlet, fixed-flux-pressure outlet
    assert m.boundaries["inlet"].mode == "volumetricFlowRate"
    assert m.boundaries["inlet"].volumetric_flow_rate == 250.0
    assert m.boundaries["outlet"].outlet_type == "fixedFlux"
    assert m.boundaries["top"].kind == "atmosphere"


def test_bundled_stl_is_resource() -> None:
    from importlib import resources

    data = resources.files("flowdesk.data").joinpath("dam_simflow.stl").read_bytes()
    assert b"facet normal" in data  # a real ASCII STL


@requires_openfoam
def test_meshes_and_runs_short(qtbot, tmp_path) -> None:
    """Short run (the full 60 s is minutes): mesh the domain with the dam carved
    out, then a couple of interFoam steps that stay finite."""
    session = projects.create_project("wrun", tmp_path, "Flow over Weir")
    session.model.mesh.block.cells = (35, 22, 15)  # coarse for CI walltime
    session.model.physics.time.end_time = 1.0
    session.model.physics.time.output_interval = 0.5
    session.model.run.cores = 2

    from flowdesk.foam import writer

    writer.write_case(session.model.validated(), session.case_dir)
    mesh_chain = "surfaceFeatureExtract && blockMesh && snappyHexMesh -overwrite"
    r = subprocess.run(openfoam_argv(mesh_chain, session.case_dir, _ENV),
                       capture_output=True, text=True, timeout=900)
    assert r.returncode == 0, f"meshing failed:\n{r.stdout[-1500:]}"
    from flowdesk.exec.parsers import read_boundary_patches

    patches = {p.name for p in read_boundary_patches(session.case_dir)}
    assert "dam" in patches  # the spillway obstacle was carved out

    from flowdesk.exec.solver import RunState, SolverSupervisor

    sup = SolverSupervisor(session.case_dir, _ENV)
    lines: list[str] = []
    sup.line.connect(lines.append)
    sup.start(session.model)
    with qtbot.waitSignal(sup.finished, timeout=900_000) as blk:
        pass
    assert blk.args == [True], "run failed; tail:\n" + "\n".join(lines[-25:])
    assert sup.state is RunState.DONE

    loaded = results_io.load(session.case_dir)
    # reservoir behind the dam starts full
    first = results_io.load(session.case_dir, 0.0)
    assert results_io.probe_point(first, (-10.0, 15.0, 4.0))["alpha.water"] > 0.9
    assert loaded.time_values
