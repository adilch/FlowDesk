"""M1 gate: model -> case -> real OpenFOAM runs clean (PRD §11 M1).

Runs via the WSL bridge locally (and inside the OpenFOAM Docker image in CI,
where the bridge is bypassed and commands run natively).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path, PurePosixPath

import pytest

from flowdesk.foam import writer
from flowdesk.model.case import CaseModel
from flowdesk.platform import wsl


def _openfoam_native() -> bool:
    """True inside a Linux environment with OpenFOAM on PATH (CI Docker)."""
    return sys.platform != "win32" and shutil.which("simpleFoam") is not None


def _openfoam_via_wsl() -> bool:
    if sys.platform != "win32":
        return False
    status = wsl.probe()
    if not (status.installed and status.distros):
        return False
    result = wsl.run(f"test -f {wsl.OPENFOAM_BASHRC}", timeout=30)
    return result.returncode == 0


requires_openfoam = pytest.mark.skipif(
    not (_openfoam_native() or _openfoam_via_wsl()),
    reason="OpenFOAM v2506 not reachable (native or via WSL)",
)


def _run_in_case(case_dir: Path, command: str) -> subprocess.CompletedProcess[str]:
    if _openfoam_native():
        return subprocess.run(
            ["bash", "-lc", f"cd {case_dir} && {command}"],
            capture_output=True, text=True, timeout=600,
        )
    linux_case = PurePosixPath(f"/home/{_wsl_user()}/flowdesk-test") / case_dir.name
    wsl.run(f"mkdir -p {wsl.shell_quote(str(linux_case.parent))} && "
            f"rm -rf {wsl.shell_quote(str(linux_case))}", timeout=60)
    win_as_wsl = wsl.windows_to_wsl_path(case_dir, wsl.probe().default_distro or "")
    wsl.run(f"cp -r {wsl.shell_quote(str(win_as_wsl))} {wsl.shell_quote(str(linux_case))}",
            timeout=120)
    return wsl.run(command, cwd=linux_case, source_openfoam=True, timeout=600)


def _wsl_user() -> str:
    return wsl.run("whoami", timeout=30).stdout.strip()


@requires_openfoam
def test_cavity_case_runs_clean(cavity_model: CaseModel, tmp_path: Path) -> None:
    """The gate: blockMesh + simpleFoam -postProcess -func writeCellCentres, exit 0."""
    case_dir = tmp_path / "cavity"
    case_dir.mkdir()
    writer.write_case(cavity_model.validated(), case_dir)

    result = _run_in_case(case_dir, "blockMesh")
    assert result.returncode == 0, f"blockMesh failed:\n{result.stdout}\n{result.stderr}"

    result = _run_in_case(
        case_dir / ".", "blockMesh && simpleFoam -postProcess -func writeCellCentres"
    )
    assert result.returncode == 0, (
        f"simpleFoam -postProcess failed:\n{result.stdout[-3000:]}\n{result.stderr[-2000:]}"
    )
    assert "FOAM FATAL" not in result.stdout + result.stderr


@requires_openfoam
@pytest.mark.skipif(os.environ.get("FLOWDESK_SLOW_TESTS") != "1",
                    reason="set FLOWDESK_SLOW_TESTS=1 to run the full solve")
def test_cavity_case_solves(cavity_model: CaseModel, tmp_path: Path) -> None:
    """Beyond the gate: the generated cavity actually converges (100 iterations)."""
    case_dir = tmp_path / "cavity-solve"
    case_dir.mkdir()
    writer.write_case(cavity_model.validated(), case_dir)
    result = _run_in_case(case_dir, "blockMesh && simpleFoam")
    assert result.returncode == 0, result.stdout[-3000:]
    assert "End" in result.stdout
