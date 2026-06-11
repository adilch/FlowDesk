"""M0 gate: cavity case parsed -> modified -> rewritten byte-stably (PRD §11 M0).

This is the spike that proves foamlib can carry the round-trip contract (§4.9):
FlowDesk must never write a file it couldn't re-read, and editing one key must
not mangle the rest of the file.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from foamlib import FoamFile

FIXTURE = Path(__file__).parent / "fixtures" / "cavity"


@pytest.fixture
def cavity(tmp_path: Path) -> Path:
    case = tmp_path / "cavity"
    shutil.copytree(FIXTURE, case)
    return case


def test_parse_control_dict(cavity: Path) -> None:
    control = FoamFile(cavity / "system" / "controlDict")
    assert control["application"] == "icoFoam"
    assert control["endTime"] == 0.5
    assert control["runTimeModifiable"] is True


def test_parse_field_file(cavity: Path) -> None:
    u_file = FoamFile(cavity / "0" / "U")
    assert u_file["boundaryField", "movingWall", "type"] == "fixedValue"
    assert u_file["boundaryField", "fixedWalls", "type"] == "noSlip"


def test_modify_then_revert_is_semantically_stable(cavity: Path) -> None:
    """Modify endTime, write, revert, write - the parsed content matches the original.

    (foamlib normalizes whitespace on the line it rewrites, so byte-equality with a
    hand-formatted original is not guaranteed; semantic equality is the contract here.
    Byte-stability of FlowDesk-written files is tested below.)
    """
    path = cavity / "system" / "controlDict"
    original = FoamFile(path).as_dict()

    control = FoamFile(path)
    control["endTime"] = 2.0
    assert FoamFile(path)["endTime"] == 2.0

    control["endTime"] = 0.5
    assert FoamFile(path).as_dict() == original


def test_foamlib_written_file_is_byte_stable(cavity: Path) -> None:
    """The determinism gate (NFR §9): once foamlib has formatted a line, further
    modify-and-revert cycles through foamlib reproduce it byte-identically."""
    path = cavity / "system" / "controlDict"

    control = FoamFile(path)
    control["endTime"] = 0.5  # rewrite in foamlib's own formatting
    normalized = path.read_bytes()

    control["endTime"] = 2.0
    control["endTime"] = 0.5
    assert path.read_bytes() == normalized


def test_modification_preserves_rest_of_file(cavity: Path) -> None:
    """Editing one key must leave every other line (incl. comments/banner) untouched."""
    path = cavity / "system" / "controlDict"
    before = path.read_text().splitlines()

    FoamFile(path)["endTime"] = 10.0
    after = path.read_text().splitlines()

    changed = [
        (b, a) for b, a in zip(before, after, strict=True) if b != a
    ]
    assert len(changed) == 1
    assert "endTime" in changed[0][0]


def test_nested_dict_roundtrip(cavity: Path) -> None:
    path = cavity / "system" / "fvSolution"
    fv = FoamFile(path)
    assert fv["solvers", "p", "solver"] == "PCG"

    fv["solvers", "p", "relTol"] = 0.01
    assert FoamFile(path)["solvers", "p", "relTol"] == 0.01
    # untouched sibling survives
    assert FoamFile(path)["solvers", "U", "solver"] == "smoothSolver"


def test_every_fixture_file_is_parseable(cavity: Path) -> None:
    """FlowDesk rule: never write a file we couldn't re-read. Baseline check on fixtures."""
    for rel in ("system/controlDict", "system/fvSchemes", "system/fvSolution",
                "system/blockMeshDict", "constant/transportProperties", "0/p", "0/U"):
        f = FoamFile(cavity / rel)
        assert len(f.as_dict()) > 0, f"{rel} parsed to empty dict"
