"""Project templates (PRD §4.1): complete, runnable cases that double as
environment smoke tests. M2 ships Empty + Lid-driven cavity; the remaining
templates (Pipe flow, External aero, Open channel) land with their stages."""

from __future__ import annotations

from collections.abc import Callable

from flowdesk.model.boundaries import Empty, PressureOutlet, SlipWall, VelocityInlet, Wall
from flowdesk.model.case import CaseModel, ProjectMeta
from flowdesk.model.mesh import BlockFace, BlockMeshModel, BlockPatch
from flowdesk.model.numerics import RunMode
from flowdesk.model.physics import FLUID_PRESETS


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


def external_aero(name: str) -> CaseModel:
    """External aero check: farfield box, no STL required (§4.2 blockMesh-only
    exception) - import a body STL and re-fit the domain to study a shape."""
    model = CaseModel(meta=ProjectMeta(name=name))
    model.geometry.blockmesh_only = True
    model.physics.fluid = FLUID_PRESETS["air"].model_copy()
    model.physics.turb_ref.velocity_scale = 10.0
    model.mesh.block = BlockMeshModel(
        bounds_min=(-2.0, -1.0, 0.0),
        bounds_max=(6.0, 1.0, 2.0),
        cells=(80, 20, 20),
        patches=[
            BlockPatch(name="inlet", faces=[BlockFace.X_MIN]),
            BlockPatch(name="outlet", faces=[BlockFace.X_MAX]),
            BlockPatch(name="ground", type="wall", faces=[BlockFace.Z_MIN]),
            BlockPatch(name="top", faces=[BlockFace.Z_MAX]),
            BlockPatch(name="sides", faces=[BlockFace.Y_MIN, BlockFace.Y_MAX]),
        ],
    )
    model.boundaries = {
        "inlet": VelocityInlet(speed=10.0),
        "outlet": PressureOutlet(),
        "ground": Wall(),
        "top": SlipWall(),
        "sides": SlipWall(),
    }
    model.run.mode = RunMode.PARALLEL
    model.run.cores = 4
    model.run.max_iterations = 400
    return model


def pipe_flow(name: str) -> CaseModel:
    """Internal duct flow: rectangular duct, velocity inlet -> pressure outlet,
    no-slip walls. (True circular pipes need an O-grid - Phase 2; the duct is
    the §4.1 'Pipe flow' starting point for internal-flow setups.)"""
    model = CaseModel(meta=ProjectMeta(name=name))
    model.geometry.blockmesh_only = True
    model.physics.turb_ref.velocity_scale = 1.0
    model.physics.turb_ref.length_scale = 0.007  # 0.07 x hydraulic diameter (0.1 m)
    model.mesh.block = BlockMeshModel(
        bounds_min=(0.0, 0.0, 0.0),
        bounds_max=(2.0, 0.1, 0.1),
        cells=(60, 8, 8),
        patches=[
            BlockPatch(name="inlet", faces=[BlockFace.X_MIN]),
            BlockPatch(name="outlet", faces=[BlockFace.X_MAX]),
            BlockPatch(
                name="walls", type="wall",
                faces=[BlockFace.Y_MIN, BlockFace.Y_MAX,
                       BlockFace.Z_MIN, BlockFace.Z_MAX],
            ),
        ],
    )
    model.boundaries = {
        "inlet": VelocityInlet(speed=1.0),
        "outlet": PressureOutlet(),
        "walls": Wall(),
    }
    model.run.max_iterations = 1000
    return model


def open_channel(name: str) -> CaseModel:
    """Open-channel flow, rigid-lid approximation: slip top stands in for the
    free surface (honest single-phase MVP; true free-surface interFoam is the
    Phase-2 hydraulics target, §1.3)."""
    model = CaseModel(meta=ProjectMeta(name=name))
    model.geometry.blockmesh_only = True
    model.physics.turb_ref.velocity_scale = 0.5
    model.physics.turb_ref.length_scale = 0.035  # 0.07 x depth
    model.mesh.block = BlockMeshModel(
        bounds_min=(0.0, 0.0, 0.0),
        bounds_max=(5.0, 1.0, 0.5),
        cells=(50, 10, 10),
        patches=[
            BlockPatch(name="inlet", faces=[BlockFace.X_MIN]),
            BlockPatch(name="outlet", faces=[BlockFace.X_MAX]),
            BlockPatch(name="bed", type="wall", faces=[BlockFace.Z_MIN]),
            BlockPatch(name="banks", type="wall",
                       faces=[BlockFace.Y_MIN, BlockFace.Y_MAX]),
            BlockPatch(name="surface", faces=[BlockFace.Z_MAX]),
        ],
    )
    model.boundaries = {
        "inlet": VelocityInlet(speed=0.5),
        "outlet": PressureOutlet(),
        "bed": Wall(),
        "banks": Wall(),
        "surface": SlipWall(),  # rigid lid
    }
    model.run.max_iterations = 1000
    return model


TEMPLATES: dict[str, Callable[[str], CaseModel]] = {
    "Empty case": empty_case,
    "Lid-driven cavity": cavity,
    "Pipe flow": pipe_flow,
    "External aero": external_aero,
    "Open channel": open_channel,
}
