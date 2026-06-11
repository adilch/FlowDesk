"""Mesh pipeline assembly (PRD §4.3.3): the steps for 'Generate Mesh'.

With STL surfaces: surfaceFeatureExtract -> blockMesh -> snappyHexMesh
-overwrite -> checkMesh (serial snappy in MVP; parallel is Phase 2).
Without: blockMesh -> checkMesh.
"""

from __future__ import annotations

from pathlib import Path

from flowdesk.exec.parsers import CheckMeshParser, SnappyLayerParser, read_boundary_patches
from flowdesk.exec.pipeline import Step, file_exists_condition
from flowdesk.model.case import CaseModel
from flowdesk.model.mesh import MeshResult
from flowdesk.platform.commands import Environment, openfoam_argv


def mesh_pipeline(model: CaseModel, case_dir: Path, env: Environment,
                  parser: CheckMeshParser,
                  layer_parser: SnappyLayerParser | None = None) -> list[Step]:
    steps: list[Step] = []
    if model.geometry.surfaces:
        first_surface = model.geometry.surfaces[0].name
        steps.append(Step(
            name="surfaceFeatureExtract",
            argv=openfoam_argv("surfaceFeatureExtract", case_dir, env),
            post_condition=file_exists_condition(
                case_dir / "constant" / "triSurface" / f"{first_surface}.eMesh",
                "feature edges were not extracted",
            ),
        ))
    steps.append(Step(
        name="blockMesh",
        argv=openfoam_argv("blockMesh", case_dir, env),
        post_condition=file_exists_condition(
            case_dir / "constant" / "polyMesh" / "points",
            "polyMesh was not created",
        ),
    ))
    if model.geometry.surfaces:
        steps.append(Step(
            name="snappyHexMesh",
            argv=openfoam_argv("snappyHexMesh -overwrite", case_dir, env),
            on_line=layer_parser.feed if layer_parser else None,
        ))
    steps.append(Step(
        name="checkMesh",
        argv=openfoam_argv("checkMesh", case_dir, env),
        on_line=parser.feed,
    ))
    return steps


def projected_cell_note(model: CaseModel) -> str | None:
    """§4.3.3: serial snappy note when the projected count is large."""
    b = model.mesh.block
    background = b.cells[0] * b.cells[1] * b.cells[2]
    if model.geometry.surfaces and background > 3_000_000:
        return ("Projected cell count exceeds 3 M — snappyHexMesh runs serial in "
                "MVP; this may take a while (parallel snappy is planned).")
    return None


def apply_mesh_result(model: CaseModel, case_dir: Path, parser: CheckMeshParser,
                      layer_parser: SnappyLayerParser | None = None) -> MeshResult:
    """Fold pipeline output into the model; returns the new MeshResult."""
    result = MeshResult(
        cell_count=parser.cell_count,
        patches=read_boundary_patches(case_dir),
        quality=parser.report,
        layer_coverage=layer_parser.coverage if layer_parser else [],
    )
    model.mesh.result = result
    return result
