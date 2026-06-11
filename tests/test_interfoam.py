"""interFoam free surface (Phase 2): generators, validation, dam-break template,
and the end-to-end dam break with physics checks."""

from __future__ import annotations

import subprocess

import numpy as np
import pytest

from flowdesk.app import projects, results_io
from flowdesk.app.templates import dam_break
from flowdesk.foam import generators
from flowdesk.model.boundaries import Atmosphere
from flowdesk.model.case import InvalidCaseError
from flowdesk.model.findings import Severity
from flowdesk.model.physics import SteadyTime
from flowdesk.platform.commands import openfoam_argv, probe_environment

_ENV = probe_environment()

requires_openfoam = pytest.mark.skipif(
    not _ENV.available, reason=f"OpenFOAM not reachable: {_ENV.detail}")


# ------------------------------------------------------------------ generators


def test_generated_files_for_free_surface() -> None:
    model = dam_break("db")
    files = generators.generate_case(model)
    assert model.physics.solver == "interFoam"
    # the interFoam file set
    assert "constant/g" in files
    assert "system/setFieldsDict" in files
    assert "0/alpha.water" in files
    assert "0/p_rgh" in files
    assert "0/p" not in files  # p_rgh replaces kinematic p
    assert "0/k" not in files  # laminar


def test_two_phase_transport_properties() -> None:
    text = generators.transport_properties(dam_break("db"))
    assert "phases          (water air);" in text
    assert "rho             [1 -3 0 0 0 0 0] 1000;" in text
    assert "rho             [1 -3 0 0 0 0 0] 1;" in text
    assert "sigma           [1 0 -2 0 0 0 0] 0.07;" in text


def test_gravity_and_set_fields() -> None:
    model = dam_break("db")
    g = generators.gravity_file(model)
    assert "uniformDimensionedVectorField" in g
    assert "value           (0 0 -9.81);" in g
    sf = generators.set_fields_dict(model)
    assert "volScalarFieldValue alpha.water 0" in sf
    assert "box (0 0 0) (0.1461 0.0146 0.292);" in sf
    assert "volScalarFieldValue alpha.water 1" in sf


def test_control_dict_interfoam() -> None:
    text = generators.control_dict(dam_break("db"))
    assert "application     interFoam;" in text
    assert "maxAlphaCo      1;" in text
    assert "adjustTimeStep  true;" in text


def test_fv_files_interfoam() -> None:
    model = dam_break("db")
    schemes = generators.fv_schemes(model)
    assert "div(rhoPhi,U)   Gauss linearUpwind grad(U);" in schemes
    assert "div(phi,alpha)  Gauss vanLeer;" in schemes
    assert "div(phirb,alpha) Gauss linear;" in schemes
    solution = generators.fv_solution(model)
    assert '"alpha.water.*"' in solution
    assert "MULESCorr       yes;" in solution
    assert "p_rghFinal" in solution
    assert "momentumPredictor no;" in solution


def test_alpha_and_prgh_bcs() -> None:
    model = dam_break("db")
    alpha = generators.field_file(model, "alpha.water")
    assert "inletOutlet" in alpha  # atmosphere lets air in, not water
    assert "zeroGradient" in alpha  # walls
    prgh = generators.field_file(model, "p_rgh")
    assert "totalPressure" in prgh
    assert "fixedFluxPressure" in prgh
    assert "[1 -1 -2 0 0 0 0]" in prgh  # Pa, not kinematic
    u = generators.field_file(model, "U")
    assert "pressureInletOutletVelocity" in u


# ------------------------------------------------------------------ validation


def test_free_surface_requires_transient() -> None:
    model = dam_break("db")
    model.physics.time = SteadyTime()
    errors = [f for f in model.validate_full() if f.severity is Severity.ERROR]
    assert any("transient" in f.message.lower() for f in errors)


def test_atmosphere_requires_free_surface() -> None:
    model = dam_break("db")
    model.physics.free_surface = None
    errors = [f for f in model.validate_full() if f.severity is Severity.ERROR]
    assert any("Atmosphere" in f.message for f in errors)


def test_water_column_must_be_inside_domain() -> None:
    model = dam_break("db")
    model.physics.free_surface.water_column_max = (9.0, 9.0, 9.0)
    with pytest.raises(InvalidCaseError):
        model.validated()


def test_dam_break_template_validates() -> None:
    model = dam_break("db")
    model.validated()
    assert isinstance(model.boundaries["atmosphere"], Atmosphere)


# ------------------------------------------------------------------- e2e


@requires_openfoam
def test_dam_break_runs_and_water_surges(qtbot, tmp_path) -> None:
    """The dam-break example, end to end: mesh, setFields, interFoam, physics."""
    session = projects.create_project("dambreak", tmp_path, "Dam break (free surface)")
    session.model.physics.time.end_time = 0.3  # shortened; users run 1 s
    session.model.physics.time.output_interval = 0.05

    from flowdesk.foam import writer

    writer.write_case(session.model.validated(), session.case_dir)
    result = subprocess.run(openfoam_argv("blockMesh", session.case_dir, _ENV),
                            capture_output=True, text=True, timeout=300)
    assert result.returncode == 0, result.stdout[-1200:]

    from flowdesk.exec.solver import RunState, SolverSupervisor

    supervisor = SolverSupervisor(session.case_dir, _ENV)
    lines: list[str] = []
    supervisor.line.connect(lines.append)
    supervisor.start(session.model)
    with qtbot.waitSignal(supervisor.finished, timeout=900_000) as blocker:
        pass
    assert blocker.args == [True], "dam break failed; tail:\n" + "\n".join(lines[-25:])
    assert supervisor.state is RunState.DONE

    times = [t for t in results_io.list_time_values(session.case_dir) if t > 0]
    assert len(times) >= 4

    # t=0: water occupies the left column (alpha=1 there, 0 at right)
    first = results_io.load(session.case_dir, 0.0)
    left = results_io.probe_point(first, (0.07, 0.007, 0.1))
    right = results_io.probe_point(first, (0.5, 0.007, 0.05))
    assert left["alpha.water"] > 0.9
    assert right["alpha.water"] < 0.1

    # by t=0.3 the surge front has crossed the tank floor to the right wall
    last = results_io.load(session.case_dir, times[-1])
    surge = results_io.probe_point(last, (0.5, 0.007, 0.03))
    assert surge["alpha.water"] > 0.2, "water never reached the right side"

    # mass conservation: mean alpha stays near the initial fill fraction (~0.125)
    key, values = results_io.scalar_array(last.mesh, "alpha.water")
    assert 0.09 < float(np.mean(values)) < 0.16
