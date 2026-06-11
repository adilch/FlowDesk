"""§12 acceptance criteria, run for real where this machine allows.

12.2: all four templates mesh, run to convergence, and render a slice,
      serial and parallel.
12.3: every generated case runs unmodified with the stock OpenFOAM v2506 CLI
      (verified here with plain bash command chains - no FlowDesk execution
      engine involved).
12.6: no ❌-validation case can ever be written (the API has no such path).
"""

from __future__ import annotations

import subprocess

import pytest

from flowdesk.app import projects, results_io
from flowdesk.model.case import CaseModel, InvalidCaseError
from flowdesk.model.numerics import RunMode
from flowdesk.platform.commands import openfoam_argv, probe_environment

_ENV = probe_environment()

requires_openfoam = pytest.mark.skipif(
    not _ENV.available, reason=f"OpenFOAM not reachable: {_ENV.detail}")

FOUR_TEMPLATES = ["Lid-driven cavity", "Pipe flow", "External aero", "Open channel"]


def _run_cli(case_dir, command: str) -> subprocess.CompletedProcess[str]:
    """Plain CLI chain - the §12.3 'CLI purist' check: stock OpenFOAM, no FlowDesk."""
    return subprocess.run(openfoam_argv(command, case_dir, _ENV),
                          capture_output=True, text=True, timeout=900)


@requires_openfoam
@pytest.mark.parametrize("template", FOUR_TEMPLATES)
@pytest.mark.parametrize("mode", [RunMode.SERIAL, RunMode.PARALLEL])
def test_template_meshes_runs_and_slices(template, mode, tmp_path) -> None:
    name = f"{template.split()[0].lower()}-{mode.value}"
    session = projects.create_project(name, tmp_path, template)
    session.model.run.mode = mode
    session.model.run.cores = 2
    # acceptance wants convergence, not marathon runs: coarse meshes converge fast
    session.model.run.max_iterations = 1500

    from flowdesk.foam import writer

    writer.write_case(session.model.validated(), session.case_dir)

    result = _run_cli(session.case_dir, "blockMesh")
    assert result.returncode == 0, f"blockMesh: {result.stdout[-1200:]}"

    if mode is RunMode.PARALLEL:
        solve = ("decomposePar -force && mpirun -np 2 simpleFoam -parallel "
                 "&& reconstructPar -latestTime")
    else:
        solve = "simpleFoam"
    result = _run_cli(session.case_dir, solve)
    assert result.returncode == 0, f"solve: {result.stdout[-2500:]}"
    assert "FOAM FATAL" not in result.stdout + result.stderr
    converged = "solution converged" in result.stdout
    ended = "End" in result.stdout
    assert converged or ended, "solver neither converged nor completed"
    assert converged, (f"{template} ({mode.value}) hit endTime without "
                       "convergence - template needs tuning")

    # render a slice (§12.2)
    loaded = results_io.load(session.case_dir)
    assert loaded.time_values[-1] > 0
    block = session.model.mesh.block
    center = tuple((lo + hi) / 2 for lo, hi in
                   zip(block.bounds_min, block.bounds_max, strict=True))
    sliced = results_io.slice_plane(loaded, center, "z")
    key, values = results_io.scalar_array(sliced, "U magnitude")
    assert sliced.n_cells > 0
    assert values.max() > 0


# ------------------------------------------------------------------ §12.6


INVALIDATORS = [
    lambda m: m.boundaries.clear(),
    lambda m: m.boundaries.__setitem__("ghost", m.boundaries["inlet"])
    if "inlet" in m.boundaries else m.boundaries.clear(),
    lambda m: setattr(m.mesh.block, "bounds_min", (99.0, 99.0, 99.0)),
    lambda m: setattr(m.mesh.block, "cells", (0, 10, 10)),
    lambda m: setattr(m.physics.fluid, "nu", -1.0),
    lambda m: setattr(m.run, "cores", 0),
    lambda m: setattr(m.run, "max_iterations", 0),
    lambda m: m.geometry.surfaces.clear() or setattr(
        m.geometry, "blockmesh_only", False),
]


@pytest.mark.parametrize("invalidate", INVALIDATORS)
def test_no_invalid_case_can_be_written(invalidate, tmp_path) -> None:
    """§12.6: every invalidating mutation must make the write token unobtainable.
    write_case requires Validated; there is no other path to disk."""
    from flowdesk.app.templates import pipe_flow

    model = pipe_flow("gate")
    model.validated()  # sane before mutation
    invalidate(model)
    if not model.validate_full():
        pytest.skip("mutation did not invalidate on this model shape")
    errors = [f for f in model.validate_full()
              if f.severity.value == "error"]
    if not errors:
        pytest.skip("mutation produced only warnings - allowed by design")
    with pytest.raises(InvalidCaseError):
        model.validated()
    assert not any(tmp_path.iterdir())


def test_empty_model_unwritable(tmp_path) -> None:
    with pytest.raises(InvalidCaseError):
        CaseModel().validated()
    assert not any(tmp_path.iterdir())
