"""Results loading & extraction (§4.8) against a real solved cavity case."""

from __future__ import annotations

import subprocess

import pytest

from flowdesk.app import projects, results_io
from flowdesk.platform.commands import openfoam_argv, probe_environment

_ENV = probe_environment()

requires_openfoam = pytest.mark.skipif(
    not _ENV.available, reason=f"OpenFOAM not reachable: {_ENV.detail}")


@pytest.fixture(scope="module")
def solved_cavity(tmp_path_factory):
    """One small solved cavity shared by all tests in this module."""
    tmp = tmp_path_factory.mktemp("solved")
    session = projects.create_project("cav-solved", tmp, "Lid-driven cavity")
    session.model.run.max_iterations = 150

    from flowdesk.foam import writer

    writer.write_case(session.model.validated(), session.case_dir)
    result = subprocess.run(
        openfoam_argv("blockMesh && simpleFoam", session.case_dir, _ENV),
        capture_output=True, text=True, timeout=600)
    assert result.returncode == 0, result.stdout[-2000:]
    return session


@requires_openfoam
def test_time_values_listed(solved_cavity) -> None:
    times = results_io.list_time_values(solved_cavity.case_dir)
    assert times, "no time values found"
    assert times[-1] > 0


@requires_openfoam
def test_load_latest_and_fields(solved_cavity) -> None:
    results = results_io.load(solved_cavity.case_dir)
    assert results.n_cells == 400
    fields = results.available_fields()
    assert "U magnitude" in fields
    assert "p" in fields
    assert "k" in fields


@requires_openfoam
def test_slice_and_scalar_extraction(solved_cavity) -> None:
    results = results_io.load(solved_cavity.case_dir)
    sliced = results_io.slice_plane(results, (0.05, 0.05, 0.005), "z")
    assert sliced.n_cells > 0
    key, values = results_io.scalar_array(sliced, "U magnitude")
    assert values.max() > 0.1  # moving lid drags fluid: nonzero speed somewhere
    key_p, _ = results_io.scalar_array(sliced, "p")
    assert key != key_p


@requires_openfoam
def test_glyphs_on_slice(solved_cavity) -> None:
    results = results_io.load(solved_cavity.case_dir)
    sliced = results_io.slice_plane(results, (0.05, 0.05, 0.005), "z")
    glyphs = results_io.glyphs_on_slice(sliced, every_nth=5, scale=0.01)
    assert glyphs is not None
    assert glyphs.n_points > 0


@requires_openfoam
def test_probe_inside_and_outside(solved_cavity) -> None:
    results = results_io.load(solved_cavity.case_dir)
    inside = results_io.probe_point(results, (0.05, 0.09, 0.005))
    assert "U" in inside
    assert isinstance(inside["U"], tuple)
    # near the moving lid the fluid moves
    assert abs(inside["U"][0]) > 1e-4


def test_preview_guard_thresholds() -> None:
    assert results_io.preview_guard(100_000) is None
    assert "moment" in results_io.preview_guard(6_000_000)
    assert "ParaView" in results_io.preview_guard(20_000_000)
