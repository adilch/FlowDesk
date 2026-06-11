"""Shared model fixtures: the two headless reference cases used across M1 tests."""

from __future__ import annotations

import pytest

from flowdesk.model.boundaries import Empty, PressureOutlet, SlipWall, VelocityInlet, Wall
from flowdesk.model.case import CaseModel, ProjectMeta
from flowdesk.model.mesh import BlockFace, BlockMeshModel, BlockPatch
from flowdesk.model.numerics import RunMode


@pytest.fixture
def box_model() -> CaseModel:
    """External-flow box: velocity inlet -> pressure outlet, walls and slip sides.

    blockMesh-only (no STL), steady simpleFoam, k-omega SST - §4.3.1/§4.5 example shape."""
    model = CaseModel(meta=ProjectMeta(name="box"))
    model.geometry.blockmesh_only = True
    model.mesh.block = BlockMeshModel(
        bounds_min=(-1.0, -1.0, 0.0),
        bounds_max=(3.0, 1.0, 1.0),
        cells=(80, 40, 20),
        patches=[
            BlockPatch(name="inlet", faces=[BlockFace.X_MIN]),
            BlockPatch(name="outlet", faces=[BlockFace.X_MAX]),
            BlockPatch(name="ground", type="wall", faces=[BlockFace.Z_MIN]),
            BlockPatch(name="top", faces=[BlockFace.Z_MAX]),
            BlockPatch(name="sides", faces=[BlockFace.Y_MIN, BlockFace.Y_MAX]),
        ],
    )
    model.boundaries = {
        "inlet": VelocityInlet(speed=2.0),
        "outlet": PressureOutlet(),
        "ground": Wall(),
        "top": SlipWall(),
        "sides": SlipWall(),
    }
    return model


@pytest.fixture
def cavity_model() -> CaseModel:
    """Lid-driven cavity: enclosed domain, moving wall, 2D (empty front/back).

    Steady simpleFoam + k-omega SST; serial. This is the M1 OpenFOAM gate case."""
    model = CaseModel(meta=ProjectMeta(name="cavity"), enclosed_domain=True)
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
    model.run.max_iterations = 100
    return model
