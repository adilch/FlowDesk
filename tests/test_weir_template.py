"""Flow over Weir (single-phase) template + the reconstruct-all-times fix.

The e2e test runs the template in parallel through the real SolverSupervisor
script and asserts MULTIPLE reconstructed time directories - the user-reported
bug was reconstructPar -latestTime discarding all earlier frames from Results.
"""

from __future__ import annotations

import subprocess

import pytest

from flowdesk.app import projects, results_io
from flowdesk.platform.commands import openfoam_argv, probe_environment

_ENV = probe_environment()

requires_openfoam = pytest.mark.skipif(
    not _ENV.available, reason=f"OpenFOAM not reachable: {_ENV.detail}")


def test_weir_template_validates(tmp_path) -> None:
    session = projects.create_project("weir", tmp_path, "Flow over Weir (single-phase)")
    model = session.model
    model.validated()
    assert model.physics.solver == "simpleFoam"
    # generated weir geometry in the case
    assert (session.case_dir / "constant" / "triSurface" / "weir.stl").exists()
    assert model.geometry.surfaces[0].diagnostics.watertight
    # convergence history is kept by default (the user's saving-frequency ask)
    control = (session.case_dir / "system" / "controlDict").read_text()
    assert "writeInterval   100;" in control
    assert "purgeWrite      0;" in control
    # rigid lid (slip surface), not a hidden free-surface claim
    assert model.boundaries["surface"].kind == "slip"
    assert model.boundaries["weir"].kind == "wall"


@requires_openfoam
def test_weir_runs_parallel_with_full_history(qtbot, tmp_path) -> None:
    session = projects.create_project("weir-run", tmp_path, "Flow over Weir (single-phase)")
    session.model.run.cores = 2
    session.model.run.max_iterations = 300  # 3 saved frames at interval 100

    from flowdesk.foam import writer

    writer.write_case(session.model.validated(), session.case_dir)
    mesh_chain = "surfaceFeatureExtract && blockMesh && snappyHexMesh -overwrite"
    result = subprocess.run(openfoam_argv(mesh_chain, session.case_dir, _ENV),
                            capture_output=True, text=True, timeout=900)
    assert result.returncode == 0, f"meshing failed:\n{result.stdout[-1500:]}"

    # the real run script (decompose -> mpirun -> reconstructPar -newTimes)
    from flowdesk.exec.solver import RunState, SolverSupervisor

    supervisor = SolverSupervisor(session.case_dir, _ENV)
    supervisor.start(session.model)
    with qtbot.waitSignal(supervisor.finished, timeout=900_000) as blocker:
        pass
    assert blocker.args == [True], "weir run failed"
    assert supervisor.state is RunState.DONE

    # THE fix: every saved frame is reconstructed into the case root
    times = results_io.list_time_values(session.case_dir)
    saved = [t for t in times if t > 0]
    assert len(saved) >= 3, f"expected >=3 reconstructed frames, got {times}"

    # results browsable at an intermediate frame, not just the last
    mid = results_io.load(session.case_dir, saved[0])
    sliced = results_io.slice_plane(mid, (1.5, 0.25, 0.25), "y")
    _key, values = results_io.scalar_array(sliced, "U magnitude")
    assert values.max() > 0.5  # accelerated flow over the crest
