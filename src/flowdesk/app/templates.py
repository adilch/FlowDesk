"""Project templates (PRD §4.1): complete, runnable cases that double as
environment smoke tests. M2 ships Empty + Lid-driven cavity; the remaining
templates (Pipe flow, External aero, Open channel) land with their stages."""

from __future__ import annotations

from collections.abc import Callable

from flowdesk.model.boundaries import Empty, Wall
from flowdesk.model.case import CaseModel, ProjectMeta
from flowdesk.model.mesh import BlockFace, BlockMeshModel, BlockPatch
from flowdesk.model.numerics import RunMode


def empty_case(name: str) -> CaseModel:
    return CaseModel(meta=ProjectMeta(name=name))


def cavity(name: str) -> CaseModel:
    """Lid-driven cavity: the §4.1 acceptance template - must mesh and run to
    convergence on a fresh install with zero edits."""
    model = CaseModel(meta=ProjectMeta(name=name), enclosed_domain=True)
    model.geometry.blockmesh_only = True
    model.mesh.block = BlockMeshModel(
        bounds_min=(0.0, 0.0, 0.0),
        bounds_max=(0.1, 0.1, 0.01),
        cells=(20, 20, 1),
        patches=[
            BlockPatch(name="movingWall", type="wall", faces=[BlockFace.Y_MAX]),
            BlockPatch(
                name="fixedWalls", type="wall",
                faces=[BlockFace.X_MIN, BlockFace.X_MAX, BlockFace.Y_MIN],
            ),
            BlockPatch(name="frontAndBack", type="empty",
                       faces=[BlockFace.Z_MIN, BlockFace.Z_MAX]),
        ],
    )
    model.boundaries = {
        "movingWall": Wall(moving_velocity=(1.0, 0.0, 0.0)),
        "fixedWalls": Wall(),
        "frontAndBack": Empty(),
    }
    model.run.mode = RunMode.SERIAL
    model.run.max_iterations = 500
    return model


TEMPLATES: dict[str, Callable[[str], CaseModel]] = {
    "Empty case": empty_case,
    "Lid-driven cavity": cavity,
}
