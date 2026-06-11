"""The transient user test case: vortex shedding behind a square cylinder.

Verifies the template end to end: generated STL, snappy mesh, pimpleFoam with
adaptive time stepping, multiple output times, and a live slice with flow.
(The test shortens the simulated time; users run the full 6 s.)
"""

from __future__ import annotations

import subprocess

import pytest

from flowdesk.app import projects, results_io
from flowdesk.exec.residuals import SolverLogParser
from flowdesk.platform.commands import openfoam_argv, probe_environment

_ENV = probe_environment()

requires_openfoam = pytest.mark.skipif(
    not _ENV.available, reason=f"OpenFOAM not reachable: {_ENV.detail}")


def test_template_validates_and_generates_geometry(tmp_path) -> None:
    session = projects.create_project("vortex", tmp_path, "Vortex shedding (transient)")
    model = session.model
    model.validated()  # complete, runnable shape
    assert model.physics.solver == "pimpleFoam"
    assert model.physics.turbulence.value == "laminar"
    # the preparer generated the cylinder into the case
    stl = session.case_dir / "constant" / "triSurface" / "cylinder.stl"
    assert stl.exists()
    assert model.geometry.surfaces[0].diagnostics.watertight
    # Re = U D / nu = 100
    re = 1.0 * 0.1 / model.physics.fluid.nu
    assert re == pytest.approx(100)
    # transient artifacts in the generated dictionaries
    control = (session.case_dir / "system" / "controlDict").read_text()
    assert "pimpleFoam" in control
    assert "adjustTimeStep  true;" in control
    assert "maxCo           0.9;" in control
    schemes = (session.case_dir / "system" / "fvSchemes").read_text()
    assert "Gauss linearUpwind grad(U)" in schemes  # shedding needs low diffusion
    assert "bounded" not in schemes.split("div(phi,U)")[1].split(";")[0]


@requires_openfoam
def test_vortex_case_meshes_and_runs_transient(tmp_path) -> None:
    session = projects.create_project("vortex-run", tmp_path,
                                      "Vortex shedding (transient)")
    # shortened for CI walltime; users run the full 6 s
    session.model.physics.time.end_time = 0.6
    session.model.physics.time.output_interval = 0.1
    session.model.run.cores = 2  # portable across test machines

    from flowdesk.foam import writer

    writer.write_case(session.model.validated(), session.case_dir)

    mesh_chain = "surfaceFeatureExtract && blockMesh && snappyHexMesh -overwrite"
    result = subprocess.run(openfoam_argv(mesh_chain, session.case_dir, _ENV),
                            capture_output=True, text=True, timeout=900)
    assert result.returncode == 0, f"meshing failed:\n{result.stdout[-2000:]}"

    solve = "decomposePar -force && mpirun -np 2 pimpleFoam -parallel && " \
            "reconstructPar"
    result = subprocess.run(openfoam_argv(solve, session.case_dir, _ENV),
                            capture_output=True, text=True, timeout=900)
    assert result.returncode == 0, f"solve failed:\n{result.stdout[-2500:]}"
    assert "FOAM FATAL" not in result.stdout + result.stderr

    # §4.7 transient monitoring signals are present in the log
    parser = SolverLogParser()
    for line in result.stdout.splitlines():
        parser.feed(line)
    assert parser.courant_max, "no Courant lines parsed (transient must report Co)"
    assert max(peak for _m, peak in parser.courant_max) < 2.0  # adaptive dt held
    assert parser.ended

    # multiple output times + a live slice with flow
    loaded = results_io.load(session.case_dir)
    written_times = [t for t in loaded.time_values if t > 0]
    assert len(written_times) >= 4, f"expected >=4 output times, got {written_times}"
    sliced = results_io.slice_plane(loaded, (1.0, 0.0, 0.025), "z")
    _key, values = results_io.scalar_array(sliced, "U magnitude")
    assert values.max() > 1.0  # flow accelerates around the cylinder
