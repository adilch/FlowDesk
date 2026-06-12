"""Passive scalar transport: field + function object + schemes/solution generation."""

from __future__ import annotations

import subprocess

import pytest

from flowdesk.app import projects
from flowdesk.foam import generators
from flowdesk.model.physics import ScalarTransportModel
from flowdesk.platform.commands import openfoam_argv, probe_environment

_ENV = probe_environment()

requires_openfoam = pytest.mark.skipif(
    not _ENV.available, reason=f"OpenFOAM not reachable: {_ENV.detail}")


def _pipe_with_scalar(tmp_path):
    session = projects.create_project("sc", tmp_path, "Pipe flow")
    session.model.physics.scalar_transport = ScalarTransportModel(
        field="s", diffusivity=1e-5, inlet_value=1.0)
    return session


def test_scalar_field_generated_with_inlet_injection(tmp_path) -> None:
    session = _pipe_with_scalar(tmp_path)
    files = generators.generate_case(session.model)
    assert "0/s" in files
    s = files["0/s"]
    assert "volScalarField" in s
    assert "[0 0 0 0 0 0 0]" in s
    # injected at the velocity inlet, inletOutlet at outlet, zeroGradient walls
    assert "fixedValue" in s.split("inlet")[1].split("}")[0]
    assert "uniform 1" in s.split("inlet")[1].split("}")[0]
    assert "inletOutlet" in s.split("outlet")[1].split("}")[0]
    assert "zeroGradient" in s.split("walls")[1].split("}")[0]


def test_scalar_transport_function_object(tmp_path) -> None:
    session = _pipe_with_scalar(tmp_path)
    control = generators.control_dict(session.model)
    assert "type            scalarTransport;" in control
    assert "field           s;" in control
    assert "D               1e-05;" in control


def test_scalar_schemes_and_solver(tmp_path) -> None:
    session = _pipe_with_scalar(tmp_path)
    schemes = generators.fv_schemes(session.model)
    assert "div(phi,s)" in schemes
    solution = generators.fv_solution(session.model)
    assert '"s.*"' in solution
    assert "PBiCGStab" in solution


def test_off_by_default(tmp_path) -> None:
    session = projects.create_project("off", tmp_path, "Pipe flow")
    assert "0/s" not in generators.generate_case(session.model)
    assert "scalarTransport" not in generators.control_dict(session.model)


def test_survives_save_load(tmp_path) -> None:
    session = _pipe_with_scalar(tmp_path)
    session.save_model()
    reopened = projects.open_project(session.case_dir)
    st = reopened.model.physics.scalar_transport
    assert st is not None and st.field == "s" and st.inlet_value == 1.0


def test_physics_stage_scalar_controls(qtbot, tmp_path) -> None:
    from flowdesk.ui.stages.physics import PhysicsStage

    session = projects.create_project("ui", tmp_path, "Pipe flow")
    stage = PhysicsStage(session)
    qtbot.addWidget(stage)
    assert not stage.scalar_box.isVisibleTo(stage)

    stage.scalar_chk.setChecked(True)
    assert stage.scalar_box.isVisibleTo(stage)
    stage.scalar_field.setText("dye")
    stage.scalar_d.set_value(2e-5)
    stage.scalar_inlet.set_value(0.8)
    stage.apply()

    st = session.model.physics.scalar_transport
    assert st is not None
    assert st.field == "dye" and st.diffusivity == 2e-5 and st.inlet_value == 0.8

    stage.scalar_chk.setChecked(False)
    stage.apply()
    assert session.model.physics.scalar_transport is None


@requires_openfoam
def test_scalar_transports_through_pipe(qtbot, tmp_path) -> None:
    """End-to-end: tracer injected at the inlet must reach the outlet."""
    session = _pipe_with_scalar(tmp_path)
    session.model.run.max_iterations = 400

    from flowdesk.app import results_io
    from flowdesk.foam import writer

    writer.write_case(session.model.validated(), session.case_dir)
    result = subprocess.run(
        openfoam_argv("blockMesh && simpleFoam", session.case_dir, _ENV),
        capture_output=True, text=True, timeout=600)
    assert result.returncode == 0, result.stdout[-2000:]
    assert "FOAM FATAL" not in result.stdout

    loaded = results_io.load(session.case_dir)
    assert "s" in loaded.available_fields()
    # tracer present in the domain, advected downstream toward the outlet
    sliced = results_io.slice_plane(loaded, (1.8, 0.05, 0.05), "x")
    _key, values = results_io.scalar_array(sliced, "s")
    assert values.max() > 0.1, "tracer did not reach the downstream plane"
