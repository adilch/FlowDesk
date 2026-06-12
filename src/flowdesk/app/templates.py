"""Project templates (PRD §4.1): complete, runnable cases that double as
environment smoke tests.

Most templates are pure models; geometry-bearing ones also register a
*preparer* that generates their STL into the case at creation time
(TEMPLATE_PREPARERS, run by projects.create_project)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from flowdesk.model.boundaries import (
    Atmosphere,
    Empty,
    PressureOutlet,
    SlipWall,
    VelocityInlet,
    Wall,
)
from flowdesk.model.case import CaseModel, ProjectMeta
from flowdesk.model.mesh import BlockFace, BlockMeshModel, BlockPatch, SurfaceRefinement
from flowdesk.model.numerics import Preset, RunMode, make_preset
from flowdesk.model.physics import (
    FLUID_PRESETS,
    Fluid,
    FreeSurfaceModel,
    TransientTime,
    Turbulence,
)


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


def vortex_shedding(name: str) -> CaseModel:
    """Transient showcase: laminar vortex shedding behind a square cylinder
    (von Kármán street) at Re = 100. pimpleFoam, adaptive time step, 10 s of
    flow time with output every 0.2 s - watch the Courant readout live and
    animate the slices in ParaView afterwards.

    Quasi-2D: a thin slab with slip front/back (snappy cannot preserve true
    1-cell 2D meshes; stated honestly rather than hidden)."""
    model = CaseModel(meta=ProjectMeta(name=name))
    # Re = U·D/ν = 1.0 · 0.1 / 1e-3 = 100: cleanly periodic laminar shedding
    model.physics.fluid = Fluid(name="custom", nu=1e-3)
    model.physics.turbulence = Turbulence.LAMINAR
    # 10 s: the instability grows for ~5 s, then the street is fully developed
    # (verified: wake Uy amplitude reaches the limit cycle well before the end)
    model.physics.time = TransientTime(
        end_time=10.0, output_interval=0.2, max_courant=0.9, initial_dt=1e-3)
    model.physics.turb_ref.velocity_scale = 1.0

    model.mesh.block = BlockMeshModel(
        bounds_min=(-0.5, -0.5, 0.0),
        bounds_max=(2.5, 0.5, 0.05),
        cells=(120, 40, 2),
        patches=[
            BlockPatch(name="inlet", faces=[BlockFace.X_MIN]),
            BlockPatch(name="outlet", faces=[BlockFace.X_MAX]),
            BlockPatch(name="sides", faces=[BlockFace.Y_MIN, BlockFace.Y_MAX]),
            BlockPatch(name="frontAndBack",
                       faces=[BlockFace.Z_MIN, BlockFace.Z_MAX]),
        ],
    )
    model.mesh.snappy.surfaces = [
        SurfaceRefinement(surface="cylinder", level_min=1, level_max=2)]
    model.mesh.snappy.location_in_mesh = (-0.3, 0.3, 0.025)

    model.boundaries = {
        "inlet": VelocityInlet(speed=1.0),
        "outlet": PressureOutlet(),
        "sides": SlipWall(),
        "frontAndBack": SlipWall(),
        "cylinder": Wall(),
    }

    # Shedding needs low numerical diffusion: first-order upwind would damp it
    model.numerics = make_preset(Preset.BALANCED)
    model.numerics.preset = Preset.CUSTOM
    model.numerics.div_u = "Gauss linearUpwind grad(U)"  # unbounded: transient

    model.run.mode = RunMode.PARALLEL
    model.run.cores = 4
    return model


def _prepare_vortex_shedding(model: CaseModel, case_dir: Path) -> None:
    """Generate the square-cylinder STL into the case (0.1 x 0.1, proud of the
    slab in z so snappy cuts cleanly)."""
    import pyvista as pv

    from flowdesk.app import geometry_io

    source = case_dir / "_template_cylinder.stl"
    box = pv.Box(bounds=(-0.05, 0.05, -0.05, 0.05, -0.02, 0.07))
    box.extract_surface().triangulate().save(str(source))
    surface = geometry_io.import_surface(source, case_dir, name="cylinder")
    source.unlink()
    surface.stl_path = "(generated by the Vortex shedding template)"
    model.geometry.surfaces = [surface]
    model.geometry.blockmesh_only = False


def weir_flow(name: str) -> CaseModel:
    """Turbulent water flow over a submerged weir in a channel: acceleration
    over the crest, recirculation downstream. Steady k-omega SST.

    Single-phase with a rigid-lid (slip) surface - a true free-surface dam
    break needs interFoam, which is the Phase-2 hydraulics target (§1.3/§13).
    Write controls default to keeping every 100th iteration so the convergence
    history is browsable in Results."""
    model = CaseModel(meta=ProjectMeta(name=name))
    model.physics.turb_ref.velocity_scale = 0.5
    model.physics.turb_ref.length_scale = 0.035  # 0.07 x depth
    model.mesh.block = BlockMeshModel(
        bounds_min=(0.0, 0.0, 0.0),
        bounds_max=(3.0, 0.5, 0.5),
        cells=(60, 10, 10),
        patches=[
            BlockPatch(name="inlet", faces=[BlockFace.X_MIN]),
            BlockPatch(name="outlet", faces=[BlockFace.X_MAX]),
            BlockPatch(name="bed", type="wall", faces=[BlockFace.Z_MIN]),
            BlockPatch(name="banks", type="wall",
                       faces=[BlockFace.Y_MIN, BlockFace.Y_MAX]),
            BlockPatch(name="surface", faces=[BlockFace.Z_MAX]),
        ],
    )
    model.mesh.snappy.surfaces = [
        SurfaceRefinement(surface="weir", level_min=1, level_max=2)]
    model.mesh.snappy.location_in_mesh = (0.5, 0.25, 0.4)

    model.boundaries = {
        "inlet": VelocityInlet(speed=0.5),
        "outlet": PressureOutlet(),
        "bed": Wall(),
        "banks": Wall(),
        "weir": Wall(),
        "surface": SlipWall(),  # rigid lid
    }
    model.run.mode = RunMode.PARALLEL
    model.run.cores = 4
    model.run.max_iterations = 1500
    model.run.write_interval_steady = 100
    model.run.purge_write = 0  # keep the whole convergence history
    return model


def _prepare_weir_flow(model: CaseModel, case_dir: Path) -> None:
    """Generate the weir STL: half-depth, full channel width, proud of the
    bed and banks so snappy cuts cleanly."""
    import pyvista as pv

    from flowdesk.app import geometry_io

    source = case_dir / "_template_weir.stl"
    box = pv.Box(bounds=(1.0, 1.1, -0.05, 0.55, -0.05, 0.25))
    box.extract_surface().triangulate().save(str(source))
    surface = geometry_io.import_surface(source, case_dir, name="weir")
    source.unlink()
    surface.stl_path = "(generated by the Flow over a weir template)"
    model.geometry.surfaces = [surface]
    model.geometry.blockmesh_only = False


def dam_breach_3d(name: str) -> CaseModel:
    """Dam break over a breached dam (SimFlow dam-break tutorial workflow):
    a 50 x 30 x 20 m valley DOMAIN is meshed with the dam.stl OBSTACLE carved
    out by snappy (material point downstream at (10, 15, 5)); the water_init
    region [-20..0, 0..30, 0..9] is the un-meshed initialization volume - the
    reservoir behind the dam. Water pours through the breach when the run
    starts. Inlet feeds the reservoir with zero-gradient phase (the face spans
    water and air); ships at 10 s of flow time - extend toward the tutorial's
    60 s for the full draining."""
    model = CaseModel(meta=ProjectMeta(name=name))
    model.physics.turbulence = Turbulence.LAMINAR
    model.physics.fluid = Fluid(name="water", nu=1e-6, rho=1000.0)
    model.physics.time = TransientTime(
        end_time=10.0, output_interval=0.25, max_courant=1.0, initial_dt=0.01)
    model.physics.free_surface = FreeSurfaceModel(
        light_phase=Fluid(name="air", nu=1.48e-5, rho=1.0),
        sigma=0.07,
        gravity=(0.0, 0.0, -9.81),
        water_column_min=(-20.0, 0.0, 0.0),  # the tutorial's water_init box
        water_column_max=(0.0, 30.0, 9.0),
    )
    model.mesh.block = BlockMeshModel(
        bounds_min=(-20.0, 0.0, 0.0),
        bounds_max=(30.0, 30.0, 20.0),
        cells=(70, 45, 30),
        patches=[
            BlockPatch(name="inlet", faces=[BlockFace.X_MIN]),
            BlockPatch(name="outlet", faces=[BlockFace.X_MAX]),
            BlockPatch(name="sides", faces=[BlockFace.Y_MIN, BlockFace.Y_MAX]),
            BlockPatch(name="bottom", type="wall", faces=[BlockFace.Z_MIN]),
            BlockPatch(name="top", faces=[BlockFace.Z_MAX]),
        ],
    )
    model.mesh.snappy.surfaces = [
        SurfaceRefinement(surface="dam", level_min=1, level_max=2)]
    model.mesh.snappy.location_in_mesh = (10.0, 15.0, 5.0)  # downstream fluid

    # 250 m^3/s over the 30 x 20 m face (tutorial mass-flow inlet)
    model.boundaries = {
        "inlet": VelocityInlet(speed=250.0 / (30.0 * 20.0), alpha_water=None),
        "outlet": PressureOutlet(),
        "sides": SlipWall(),
        "bottom": Wall(),
        "top": Atmosphere(),
        "dam": Wall(),
    }
    model.run.mode = RunMode.PARALLEL
    model.run.cores = 4
    return model


def _prepare_dam_breach(model: CaseModel, case_dir: Path) -> None:
    """Generate dam.stl: a 12 m dam wall across the valley at x = 0..2 with a
    6 m wide central breach (y 12..18). Two disjoint closed boxes in one STL -
    snappy treats them as one obstacle surface named 'dam'."""
    import pyvista as pv

    from flowdesk.app import geometry_io

    left = pv.Box(bounds=(0.0, 2.0, -0.5, 12.0, -0.5, 12.0))
    right = pv.Box(bounds=(0.0, 2.0, 18.0, 30.5, -0.5, 12.0))
    dam = left.extract_surface().triangulate().merge(
        right.extract_surface().triangulate())
    source = case_dir / "_template_dam.stl"
    dam.save(str(source))
    surface = geometry_io.import_surface(source, case_dir, name="dam")
    source.unlink()
    surface.stl_path = "(generated by the Dam break (3D breach) template)"
    model.geometry.surfaces = [surface]
    model.geometry.blockmesh_only = False


def dam_break(name: str) -> CaseModel:
    """The classic dam break (free surface, interFoam): a 0.146 m x 0.292 m
    water column collapses across a 0.584 m tank. 2D (one cell thick,
    empty front/back - pure blockMesh, so true 2D works). Laminar, like the
    canonical OpenFOAM tutorial; ~1 s of flow time, output every 0.02 s."""
    model = CaseModel(meta=ProjectMeta(name=name))
    model.geometry.blockmesh_only = True
    model.physics.turbulence = Turbulence.LAMINAR
    model.physics.fluid = Fluid(name="water", nu=1e-6, rho=1000.0)
    model.physics.time = TransientTime(
        end_time=1.0, output_interval=0.02, max_courant=1.0, initial_dt=1e-4)
    model.physics.free_surface = FreeSurfaceModel(
        light_phase=Fluid(name="air", nu=1.48e-5, rho=1.0),
        sigma=0.07,
        gravity=(0.0, 0.0, -9.81),
        water_column_min=(0.0, 0.0, 0.0),
        water_column_max=(0.1461, 0.0146, 0.292),
    )
    model.mesh.block = BlockMeshModel(
        bounds_min=(0.0, 0.0, 0.0),
        bounds_max=(0.584, 0.0146, 0.584),
        cells=(64, 1, 64),
        patches=[
            BlockPatch(name="leftWall", type="wall", faces=[BlockFace.X_MIN]),
            BlockPatch(name="rightWall", type="wall", faces=[BlockFace.X_MAX]),
            BlockPatch(name="lowerWall", type="wall", faces=[BlockFace.Z_MIN]),
            BlockPatch(name="atmosphere", faces=[BlockFace.Z_MAX]),
            BlockPatch(name="frontAndBack", type="empty",
                       faces=[BlockFace.Y_MIN, BlockFace.Y_MAX]),
        ],
    )
    model.boundaries = {
        "leftWall": Wall(),
        "rightWall": Wall(),
        "lowerWall": Wall(),
        "atmosphere": Atmosphere(),
        "frontAndBack": Empty(),
    }
    model.run.mode = RunMode.SERIAL  # 4k cells: decomposition would cost more
    return model


TEMPLATES: dict[str, Callable[[str], CaseModel]] = {
    "Empty case": empty_case,
    "Lid-driven cavity": cavity,
    "Pipe flow": pipe_flow,
    "External aero": external_aero,
    "Open channel": open_channel,
    "Flow over a weir": weir_flow,
    "Dam break (2D column)": dam_break,
    "Dam break (3D breach)": dam_breach_3d,
    "Vortex shedding (transient)": vortex_shedding,
}

# One-line descriptions shown in the New Project gallery.
TEMPLATE_DESCRIPTIONS: dict[str, str] = {
    "Empty case": "A blank project — set up geometry, mesh and physics yourself.",
    "Lid-driven cavity": "The classic benchmark; doubles as an environment check. "
                         "Steady, laminar, meshes and runs in seconds.",
    "Pipe flow": "Turbulent flow in a rectangular duct (velocity inlet → pressure "
                 "outlet, no-slip walls). Steady k-ω SST.",
    "External aero": "Flow around a body in a farfield box (blockMesh-only). "
                     "Steady, parallel.",
    "Open channel": "Free-surface channel, rigid-lid approximation. Steady SST.",
    "Flow over a weir": "Water over a submerged weir in a channel; keeps the whole "
                        "convergence history. Steady SST, parallel.",
    "Dam break (2D column)": "The canonical interFoam benchmark: a water column "
                             "collapses across a tank. 2D, laminar, fast.",
    "Dam break (3D breach)": "SimFlow-style 3D dam breach: a valley domain with the "
                             "dam carved out, reservoir behind it. interFoam.",
    "Vortex shedding (transient)": "Laminar von Kármán street behind a square "
                                   "cylinder at Re 100. pimpleFoam, adaptive Δt.",
}

# Run after the case directory exists, before the first write (geometry-bearing
# templates generate their STL here)
TEMPLATE_PREPARERS: dict[str, Callable[[CaseModel, Path], None]] = {
    "Vortex shedding (transient)": _prepare_vortex_shedding,
    "Flow over a weir": _prepare_weir_flow,
    "Dam break (3D breach)": _prepare_dam_breach,
}
