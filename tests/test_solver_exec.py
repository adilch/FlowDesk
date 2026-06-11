"""Solver execution units: log parser (§4.7 table), error explanations, run script."""

from __future__ import annotations

from flowdesk.app.templates import cavity, external_aero
from flowdesk.exec.errors import HONEST_DEFAULT, explain, load_rules
from flowdesk.exec.residuals import SolverLogParser
from flowdesk.exec.solver import build_run_script
from flowdesk.model.numerics import RunMode

SIMPLE_FOAM_SAMPLE = """\
FLOWDESK_STATE: decomposing
Decomposing mesh
FLOWDESK_STATE: running
Time = 1

smoothSolver:  Solving for Ux, Initial residual = 1, Final residual = 0.05, No Iterations 4
smoothSolver:  Solving for Uy, Initial residual = 0.9, Final residual = 0.04, No Iterations 4
GAMG:  Solving for p, Initial residual = 1, Final residual = 0.009, No Iterations 12
time step continuity errors : sum local = 0.0003, global = 1.2e-05, cumulative = 1.2e-05
smoothSolver:  Solving for omega, Initial residual = 0.1, Final residual = 0.002, No Iterations 3
smoothSolver:  Solving for k, Initial residual = 1, Final residual = 0.03, No Iterations 4
bounding k, min: 0 max: 1.2 average: 0.05

Time = 2

smoothSolver:  Solving for Ux, Initial residual = 0.3, Final residual = 0.01, No Iterations 4
GAMG:  Solving for p, Initial residual = 0.5, Final residual = 0.004, No Iterations 10
time step continuity errors : sum local = 0.0001, global = 8e-06, cumulative = 2e-05

End
"""


def test_solver_log_parser_full() -> None:
    parser = SolverLogParser()
    for line in SIMPLE_FOAM_SAMPLE.splitlines():
        parser.feed(line)
    assert parser.times == [1.0, 2.0]
    assert [v for _, v in parser.residuals["Ux"]] == [1.0, 0.3]
    assert parser.residuals["p"][0] == (1.0, 1.0)
    assert parser.residuals["omega"][-1][1] == 0.1
    assert parser.continuity == 0.0001
    assert "k" in parser.bounding_fields
    assert parser.state_marker == "running"
    assert parser.ended
    assert not parser.fatal_seen
    assert parser.latest_residuals()["p"] == 0.5


def test_parser_captures_fatal_block() -> None:
    parser = SolverLogParser()
    parser.feed("--> FOAM FATAL ERROR: (openfoam-2506)")
    parser.feed("Maximum number of iterations exceeded: GAMG")
    parser.feed("    From Foam::GAMGSolver")
    assert parser.fatal_seen
    assert any("GAMG" in line for line in parser.fatal_context)


def test_transient_courant_parsing() -> None:
    parser = SolverLogParser()
    parser.feed("Courant Number mean: 0.22 max: 0.85")
    assert parser.courant_max == [(0.22, 0.85)]


# ------------------------------------------------------------------ explanations


def test_error_rules_load_and_match() -> None:
    rules = load_rules()
    assert len(rules) >= 5
    text = ("--> FOAM FATAL ERROR\nMaximum number of iterations exceeded "
            "when solving with GAMG")
    assert "pressure solver" in explain(text)


def test_unknown_error_gets_honest_default() -> None:
    assert explain("some never-seen-before failure xyz") == HONEST_DEFAULT


# ------------------------------------------------------------------ run script


def test_parallel_script_sequence() -> None:
    model = external_aero("aero")
    script = build_run_script(model, first_order_switch=None)
    assert "decomposePar -force" in script
    assert "mpirun -np 4 simpleFoam -parallel" in script
    # all saved times must reach the case root, not just the last frame
    assert "reconstructPar -newTimes" in script
    assert "touch case.foam" in script
    # state markers in order
    assert script.index("decomposing") < script.index("running")
    assert script.index("running") < script.index("reconstructing")


def test_serial_script_has_no_mpi() -> None:
    model = cavity("cav")
    script = build_run_script(model, None)
    assert "decomposePar" not in script
    assert "mpirun" not in script
    assert "simpleFoam || fail" in script


def test_first_order_start_legs() -> None:
    model = external_aero("aero")
    model.run.mode = RunMode.SERIAL
    script = build_run_script(model, first_order_switch=200)
    assert "endTime -set 200" in script
    assert "fvSchemes.flowdesk-target" in script
    assert "endTime -set 400" in script  # back to max_iterations
    assert "switching to second-order" in script
    assert script.count("simpleFoam || fail") == 2
