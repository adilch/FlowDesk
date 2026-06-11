"""polyMesh/boundary type sync (§4.5): wall functions need `type wall` in the mesh."""

from __future__ import annotations

from pathlib import Path

from flowdesk.foam import polymesh
from flowdesk.model.boundaries import Empty, SlipWall, Symmetry, Wall
from flowdesk.model.case import CaseModel
from flowdesk.model.findings import Severity

BOUNDARY_SAMPLE = """\
FoamFile { version 2.0; format ascii; class polyBoundaryMesh; object boundary; }
3
(
    zMin
    {
        type            patch;
        nFaces          240;
        startFace       760;
    }
    sides
    {
        type            patch;
        nFaces          480;
        startFace       1000;
    }
    weir
    {
        type            wall;
        nFaces          2880;
        startFace       1480;
    }
)
"""


def _case_with_boundary(tmp_path: Path) -> Path:
    path = tmp_path / "constant" / "polyMesh" / "boundary"
    path.parent.mkdir(parents=True)
    path.write_text(BOUNDARY_SAMPLE, encoding="utf-8", newline="\n")
    return tmp_path


def test_wall_and_symmetry_synced(tmp_path: Path) -> None:
    case = _case_with_boundary(tmp_path)
    model = CaseModel()
    model.boundaries = {"zMin": Wall(), "sides": Symmetry(), "weir": Wall()}

    changes = polymesh.sync_boundary_types(model, case)
    assert ("zMin", "patch", "wall") in changes
    assert ("sides", "patch", "symmetry") in changes
    assert all(c[0] != "weir" for c in changes)  # already wall: untouched

    text = (case / "constant" / "polyMesh" / "boundary").read_text()
    assert "zMin\n    {\n        type            wall;" in text.replace("\r", "")
    assert "nFaces          240;" in text  # rest of the block preserved


def test_slip_stays_patch(tmp_path: Path) -> None:
    case = _case_with_boundary(tmp_path)
    model = CaseModel()
    model.boundaries = {"sides": SlipWall()}
    assert polymesh.sync_boundary_types(model, case) == []


def test_no_mesh_is_noop(tmp_path: Path) -> None:
    model = CaseModel()
    model.boundaries = {"zMin": Wall()}
    assert polymesh.sync_boundary_types(model, tmp_path) == []


def test_empty_on_non_empty_patch_is_validation_error() -> None:
    from flowdesk.app.templates import cavity

    model = cavity("x")
    # sabotage: frontAndBack assigned Empty but mesh patch type changed to patch
    for p in model.mesh.block.patches:
        if p.name == "frontAndBack":
            p.type = "patch"
    errors = [f for f in model.validate_full() if f.severity is Severity.ERROR]
    assert any("Empty (2D)" in f.message and "re-mesh" in f.message for f in errors)


def test_cavity_template_unaffected() -> None:
    from flowdesk.app.templates import cavity

    model = cavity("x")
    model.validated()  # frontAndBack is correctly typed empty at mesh time


def test_empty_bc_assignment(tmp_path: Path) -> None:
    model = CaseModel()
    model.boundaries = {"zMin": Empty()}
    case = _case_with_boundary(tmp_path)
    # empty is not a syncable conversion - never rewritten post-mesh
    assert polymesh.sync_boundary_types(model, case) == []
