"""Mesh pipeline assembly (PRD §4.3.3): the steps for 'Generate Mesh'.

M2 scope: serial blockMesh -> checkMesh (snappy chain arrives in M3).
"""

from __future__ import annotations

from pathlib import Path

from flowdesk.exec.parsers import CheckMeshParser, read_boundary_patches
from flowdesk.exec.pipeline import Step, file_exists_condition
from flowdesk.model.case import CaseModel
from flowdesk.model.mesh import MeshResult
from flowdesk.platform.commands import Environment, openfoam_argv


def mesh_pipeline(model: CaseModel, case_dir: Path, env: Environment,
                  parser: CheckMeshParser) -> list[Step]:
    steps = [
        Step(
            name="blockMesh",
            argv=openfoam_argv("blockMesh", case_dir, env),
            post_condition=file_exists_condition(
                case_dir / "constant" / "polyMesh" / "points",
                "polyMesh was not created",
            ),
        ),
        Step(
            name="checkMesh",
            argv=openfoam_argv("checkMesh", case_dir, env),
            on_line=parser.feed,
        ),
    ]
    return steps


def apply_mesh_result(model: CaseModel, case_dir: Path, parser: CheckMeshParser) -> MeshResult:
    """Fold pipeline output into the model; returns the new MeshResult."""
    result = MeshResult(
        cell_count=parser.cell_count,
        patches=read_boundary_patches(case_dir),
        quality=parser.report,
    )
    model.mesh.result = result
    return result
