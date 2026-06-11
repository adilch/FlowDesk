"""M4 gate: external-aero template converges in parallel with live plots;
pull-the-plug-and-reattach passes (PRD §11 M4, §12.5)."""

from __future__ import annotations

import pytest

from flowdesk.app import projects
from flowdesk.exec.solver import RunState, SolverSupervisor
from flowdesk.platform.commands import probe_environment
from flowdesk.ui.stages.run import RunStage

_ENV = probe_environment()

requires_openfoam = pytest.mark.skipif(
    not _ENV.available, reason=f"OpenFOAM not reachable: {_ENV.detail}")


def _mesh(session) -> None:
    """blockMesh the case synchronously + record a MeshResult (Run-gate prereq)."""
    import subprocess

    from flowdesk.exec.parsers import read_boundary_patches
    from flowdesk.model.mesh import MeshResult, QualityReport
    from flowdesk.platform.commands import openfoam_argv

    argv = openfoam_argv("blockMesh", session.case_dir, _ENV)
    result = subprocess.run(argv, capture_output=True, text=True, timeout=300)
    assert result.returncode == 0, f"blockMesh failed:\n{result.stdout[-1500:]}"
    session.model.mesh.result = MeshResult(
        cell_count=1, patches=read_boundary_patches(session.case_dir),
        quality=QualityReport(mesh_ok=True))


@requires_openfoam
def test_external_aero_converges_in_parallel_with_live_plots(qtbot, tmp_path) -> None:
    """The gate: template -> Run -> parallel solve -> Done, residuals plotted,
    case reconstructed."""
    session = projects.create_project("aero-gate", tmp_path, "External aero")
    session.model.run.cores = 2  # portable across test machines
    _mesh(session)
    stage = RunStage(session, _ENV)
    qtbot.addWidget(stage)
    stage.cores.setValue(2)

    stage.start_run()
    assert stage.supervisor is not None, "run did not start (validation failed?)"
    log: list[str] = []
    stage.supervisor.line.connect(log.append)

    with qtbot.waitSignal(stage.run_finished, timeout=600_000) as blocker:
        pass
    tail = "\n".join(log[-40:])
    assert blocker.args == [True], f"run failed; log tail:\n{tail}"
    assert stage.supervisor.state is RunState.DONE

    # Live plots: residual series exist for the solved fields and were drawn
    parser = stage.supervisor.parser
    assert {"Ux", "p", "k", "omega"} <= set(parser.residuals)
    assert len(parser.times) > 10
    assert stage._curves, "no curves were added to the live plot"
    assert parser.ended or any("converged" in line for line in log)

    # Parallel artifacts: decomposed dirs + reconstructed latest time in case root
    assert (session.case_dir / "processor0").exists()
    time_dirs = [p.name for p in session.case_dir.iterdir()
                 if p.is_dir() and p.name.replace(".", "").isdigit() and p.name != "0"]
    assert time_dirs, "reconstructPar produced no time directory in the case root"
    assert (session.case_dir / "case.foam").exists()
    # pid file cleaned up after completion
    assert not (session.case_dir / "flowdesk.pid").exists()


@requires_openfoam
def test_pull_the_plug_and_reattach(qtbot, tmp_path) -> None:
    """§12.5: the GUI-side monitor dies mid-run; the detached solver survives;
    a fresh supervisor re-attaches by PID file and sees the run to completion."""
    session = projects.create_project("plug-gate", tmp_path, "Lid-driven cavity")
    # big enough to still be running when we pull the plug
    session.model.mesh.block.cells = (60, 60, 1)
    session.model.run.max_iterations = 3000

    from flowdesk.foam import writer

    writer.write_case(session.model.validated(), session.case_dir)
    _mesh(session)

    supervisor1 = SolverSupervisor(session.case_dir, _ENV)
    supervisor1.start(session.model)
    qtbot.waitUntil(lambda: supervisor1.state is RunState.RUNNING, timeout=60_000)
    qtbot.wait(1500)  # let some iterations accumulate
    assert supervisor1._pid_alive(), "solver should be running"

    # Pull the plug: the monitor dies, the solver must not
    supervisor1.detach()
    pid = supervisor1.pid

    supervisor2 = SolverSupervisor(session.case_dir, _ENV)
    assert supervisor2.attach(), "re-attach found no run to monitor"
    assert supervisor2.pid == pid

    with qtbot.waitSignal(supervisor2.finished, timeout=600_000) as blocker:
        pass
    assert blocker.args == [True], "re-attached run did not complete cleanly"
    assert supervisor2.parser.ended
    # The log was re-read from the start: early iterations are present
    assert supervisor2.parser.times[0] <= 2.0
    time_dirs = [p.name for p in session.case_dir.iterdir()
                 if p.is_dir() and p.name.isdigit() and p.name != "0"]
    assert time_dirs, "solver produced no results"


@requires_openfoam
def test_graceful_stop_mid_run(qtbot, tmp_path) -> None:
    """Stop = stopAt writeNow via runTimeModifiable: the solver halts early and
    cleanly (§4.7)."""
    session = projects.create_project("stop-gate", tmp_path, "Lid-driven cavity")
    session.model.mesh.block.cells = (60, 60, 1)
    session.model.run.max_iterations = 5000

    from flowdesk.foam import writer

    writer.write_case(session.model.validated(), session.case_dir)
    _mesh(session)
    supervisor = SolverSupervisor(session.case_dir, _ENV)
    supervisor.start(session.model)
    qtbot.waitUntil(lambda: supervisor.parser.current_time >= 5, timeout=120_000)

    supervisor.stop()
    with qtbot.waitSignal(supervisor.finished, timeout=120_000) as blocker:
        pass
    assert blocker.args == [True]  # writeNow exits 0: a clean, honest stop
    assert supervisor.parser.current_time < 5000, "solver did not stop early"
