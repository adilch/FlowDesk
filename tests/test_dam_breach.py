"""Dam break (3D breach) - the SimFlow dam-break tutorial workflow:
domain meshed, dam.stl carved out as an obstacle, water_init volume behind it."""

from __future__ import annotations

import subprocess

import pytest

from flowdesk.app import projects, results_io
from flowdesk.foam import generators
from flowdesk.platform.commands import openfoam_argv, probe_environment

_ENV = probe_environment()

requires_openfoam = pytest.mark.skipif(
    not _ENV.available, reason=f"OpenFOAM not reachable: {_ENV.detail}")


def test_template_matches_tutorial_setup(tmp_path) -> None:
    session = projects.create_project("breach", tmp_path, "Dam break (3D breach)")
    model = session.model
    model.validated()

    # the DOMAIN is the tutorial's base mesh, the dam is an obstacle inside it
    assert model.mesh.block.bounds_min == (-20.0, 0.0, 0.0)
    assert model.mesh.block.bounds_max == (30.0, 30.0, 20.0)
    assert model.mesh.block.cells == (70, 45, 30)
    assert (session.case_dir / "constant" / "triSurface" / "dam.stl").exists()
    assert model.mesh.snappy.surfaces[0].surface == "dam"
    # material point downstream in the fluid - NOT inside the dam
    assert model.mesh.snappy.location_in_mesh == (10.0, 15.0, 5.0)

    # water_init: initialization volume, not meshed geometry
    fs = model.physics.free_surface
    assert fs.water_column_min == (-20.0, 0.0, 0.0)
    assert fs.water_column_max == (0.0, 30.0, 9.0)
    sf = generators.set_fields_dict(model)
    assert "box (-20 0 0) (0 30 9);" in sf

    # inlet: face spans water and air -> zero-gradient phase (tutorial BC)
    alpha = generators.field_file(model, "alpha.water")
    inlet_block = alpha.split("inlet")[1].split("}")[0]
    assert "zeroGradient" in inlet_block
    assert model.boundaries["inlet"].alpha_water is None
    assert model.boundaries["top"].kind == "atmosphere"
    assert model.boundaries["dam"].kind == "wall"


def test_material_point_not_inside_dam(tmp_path) -> None:
    """The user-reported failure mode: meshing the dam instead of the domain."""
    from flowdesk.app import mesh_suggest

    session = projects.create_project("breach2", tmp_path, "Dam break (3D breach)")
    diagnosis = mesh_suggest.location_diagnosis(
        session.model, session.case_dir, session.model.mesh.snappy.location_in_mesh)
    assert diagnosis is None  # inside domain, outside dam, clear of surfaces

    inside_dam = mesh_suggest.location_diagnosis(
        session.model, session.case_dir, (1.0, 5.0, 5.0))  # inside the left dam block
    assert inside_dam is not None and "inside the solid" in inside_dam


def test_default_slice_orientation(qtbot, tmp_path) -> None:
    """'Why don't I see the velocities' - the default slice must cut through
    the flow, not the air above it."""
    from flowdesk.ui.stages.results import ResultsStage
    from flowdesk.ui.viewer import ViewerWidget

    viewer = ViewerWidget()
    qtbot.addWidget(viewer)

    # free surface, no thin axis: vertical cut (Y) through the breach
    breach = projects.create_project("b", tmp_path, "Dam break (3D breach)")
    stage = ResultsStage(breach, viewer)
    qtbot.addWidget(stage)
    assert stage.normal_seg.current() == 1

    # quasi-2D column (1 cell in y): the 2D plane itself
    column = projects.create_project("c", tmp_path, "Dam break (2D column)")
    stage2 = ResultsStage(column, viewer)
    qtbot.addWidget(stage2)
    assert stage2.normal_seg.current() == 1

    # single-phase 3D (weir): unchanged mid-depth Z cut
    weir = projects.create_project("w", tmp_path, "Flow over a weir")
    stage3 = ResultsStage(weir, viewer)
    qtbot.addWidget(stage3)
    assert stage3.normal_seg.current() == 2


@requires_openfoam
def test_breach_flow_end_to_end(qtbot, tmp_path) -> None:
    """Shortened run: water must pour through the breach, not through the dam."""
    session = projects.create_project("breach-run", tmp_path, "Dam break (3D breach)")
    # coarse + short for test walltime; users run the shipped settings
    session.model.mesh.block.cells = (35, 22, 15)
    session.model.physics.time.end_time = 2.0
    session.model.physics.time.output_interval = 0.5
    session.model.run.cores = 2

    from flowdesk.foam import writer

    writer.write_case(session.model.validated(), session.case_dir)
    mesh_chain = "surfaceFeatureExtract && blockMesh && snappyHexMesh -overwrite"
    result = subprocess.run(openfoam_argv(mesh_chain, session.case_dir, _ENV),
                            capture_output=True, text=True, timeout=900)
    assert result.returncode == 0, f"meshing failed:\n{result.stdout[-1500:]}"
    # the dam was carved out of the domain: its patch exists in the mesh
    from flowdesk.exec.parsers import read_boundary_patches

    patch_names = {p.name for p in read_boundary_patches(session.case_dir)}
    assert "dam" in patch_names, "dam obstacle missing from the meshed boundary"

    from flowdesk.exec.solver import RunState, SolverSupervisor

    supervisor = SolverSupervisor(session.case_dir, _ENV)
    lines: list[str] = []
    supervisor.line.connect(lines.append)
    supervisor.start(session.model)
    with qtbot.waitSignal(supervisor.finished, timeout=1_200_000) as blocker:
        pass
    assert blocker.args == [True], "breach run failed; tail:\n" + "\n".join(lines[-25:])
    assert supervisor.state is RunState.DONE

    times = [t for t in results_io.list_time_values(session.case_dir) if t > 0]
    assert len(times) >= 3

    # t=0: reservoir full upstream, dry downstream
    first = results_io.load(session.case_dir, 0.0)
    reservoir = results_io.probe_point(first, (-10.0, 15.0, 4.0))
    downstream0 = results_io.probe_point(first, (10.0, 15.0, 1.0))
    assert reservoir["alpha.water"] > 0.9
    assert downstream0["alpha.water"] < 0.1

    # by t=2 s water has poured THROUGH the breach (y=15) onto the downstream bed
    last = results_io.load(session.case_dir, times[-1])
    through_breach = results_io.probe_point(last, (6.0, 15.0, 0.5))
    assert through_breach["alpha.water"] > 0.2, "no water came through the breach"
    # behind the intact dam segment (y=5), high ground stays dry at z=10
    above_dam = results_io.probe_point(last, (5.0, 5.0, 11.0))
    assert above_dam["alpha.water"] < 0.3, "water overtopped the intact dam?"
