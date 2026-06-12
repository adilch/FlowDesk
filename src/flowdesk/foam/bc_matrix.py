"""The physical-BC -> per-field-entries matrix (PRD §4.5).

One physical intent ("velocity inlet, 2 m/s") expands into mutually consistent
entries for every field file the turbulence model requires. Wall treatment
follows the turbulence model atomically (§4.5 consistency rule).
"""

from __future__ import annotations

from flowdesk.foam.emitter import entry, fmt
from flowdesk.model.boundaries import (
    Atmosphere,
    Empty,
    FieldOverride,
    Outflow,
    PhysicalBC,
    PressureOutlet,
    SlipWall,
    Symmetry,
    VelocityInlet,
    Wall,
)
from flowdesk.model.case import CaseModel
from flowdesk.model.geometry import Vec3
from flowdesk.model.mesh import BlockFace
from flowdesk.model.physics import Turbulence

# Inward unit normals of the background box faces, for "normal speed" inlets.
_INWARD = {
    BlockFace.X_MIN: (1.0, 0.0, 0.0),
    BlockFace.X_MAX: (-1.0, 0.0, 0.0),
    BlockFace.Y_MIN: (0.0, 1.0, 0.0),
    BlockFace.Y_MAX: (0.0, -1.0, 0.0),
    BlockFace.Z_MIN: (0.0, 0.0, 1.0),
    BlockFace.Z_MAX: (0.0, 0.0, -1.0),
}


def fields_for(turbulence: Turbulence, free_surface: bool = False) -> list[str]:
    """Field files the case needs (§4.5: laminar drops k/omega/nut entirely).

    interFoam replaces kinematic p with p_rgh (Pa - it is a rho-based solver)
    and adds the alpha.water phase fraction."""
    pressure = ["p_rgh", "alpha.water"] if free_surface else ["p"]
    if turbulence is Turbulence.LAMINAR:
        return ["U", *pressure]
    if turbulence is Turbulence.K_EPSILON:
        return ["U", *pressure, "k", "epsilon", "nut"]
    return ["U", *pressure, "k", "omega", "nut"]


def resolve_inlet_vector(model: CaseModel, patch: str, bc: VelocityInlet) -> Vec3:
    """Resolve a velocity-inlet spec to a vector. Normal mode uses the inward
    normal of the background-box face the patch covers (M1 scope: normal mode
    on snappy surface patches is rejected in validation until the viewer can
    supply true patch normals)."""
    if bc.mode == "vector":
        return bc.vector
    for p in model.mesh.block.patches:
        if p.name == patch and len(p.faces) == 1:
            n = _INWARD[p.faces[0]]
            return (n[0] * bc.speed, n[1] * bc.speed, n[2] * bc.speed)
    raise ValueError(
        f"Cannot resolve normal-speed inlet on patch '{patch}' - not a single "
        "background-box face. Use vector mode."
    )


def inlet_reference_speed(model: CaseModel, patch: str, bc: VelocityInlet) -> float:
    """A representative inflow speed for turbulence estimation. Velocity specs
    use the actual speed; flow-rate/pressure specs fall back to the Physics
    reference velocity (true speed depends on the patch area, unknown here)."""
    if bc.mode == "normal":
        return abs(bc.speed)
    if bc.mode == "vector":
        return sum(c * c for c in bc.vector) ** 0.5
    return model.physics.turb_ref.velocity_scale


def inlet_velocity_entries(model: CaseModel, patch: str, bc: VelocityInlet) -> list[str]:
    """The U entry for each inlet spec (SimFlow-style sub-types)."""
    match bc.mode:
        case "normal" | "vector":
            vec = resolve_inlet_vector(model, patch, bc)
            return [entry("type", "fixedValue"), entry("value", f"uniform {fmt(vec)}")]
        case "volumetricFlowRate":
            return [entry("type", "flowRateInletVelocity"),
                    entry("volumetricFlowRate", fmt(bc.volumetric_flow_rate)),
                    entry("value", "uniform (0 0 0)")]
        case "massFlowRate":
            # incompressible: flowRateInletVelocity needs a reference density
            return [entry("type", "flowRateInletVelocity"),
                    entry("massFlowRate", fmt(bc.mass_flow_rate)),
                    entry("rho", "rho"),
                    entry("rhoInlet", fmt(model.physics.fluid.rho)),
                    entry("value", "uniform (0 0 0)")]
        case "pressure":
            return [entry("type", "pressureInletOutletVelocity"),
                    entry("value", "uniform (0 0 0)")]
    raise ValueError(f"unknown inlet spec: {bc.mode}")


def inlet_turbulence_values(model: CaseModel, bc: VelocityInlet, speed: float) -> dict[str, float]:
    """k / omega / epsilon at an inlet, from intensity+length or direct values (§4.5)."""
    t = bc.turbulence
    if t.mode == "direct":
        return {
            "k": t.k if t.k is not None else model.physics.k_from(),
            "omega": t.omega if t.omega is not None else model.physics.omega_from(),
            "epsilon": t.epsilon if t.epsilon is not None else model.physics.epsilon_from(),
        }
    physics = model.physics.model_copy(deep=True)
    if t.intensity is not None:
        physics.turb_ref.intensity = t.intensity
    if t.length_scale is not None:
        physics.turb_ref.length_scale = t.length_scale
    return {
        "k": physics.k_from(speed),
        "omega": physics.omega_from(speed),
        "epsilon": physics.epsilon_from(speed),
    }


def emit_override(ov: FieldOverride) -> list[str]:
    """Render a per-field override (the SimFlow per-field layer)."""
    lines = [entry("type", ov.patch_type)]
    lines.extend(entry(k, v) for k, v in ov.extra.items())
    if ov.value:
        lines.append(entry("value", ov.value))
    return lines


def patch_entries(model: CaseModel, patch: str, bc: PhysicalBC, field: str) -> list[str]:
    """Inner lines of one patch block in one field file - the §4.5 matrix,
    extended for interFoam fields (p_rgh, alpha.water) in Phase 2.

    A per-field override (bc.overrides[field]) wins over the generated entry."""
    turb = model.physics.turbulence
    free_surface = model.physics.free_surface is not None

    if field in bc.overrides:
        return emit_override(bc.overrides[field])

    if isinstance(bc, Symmetry):
        return [entry("type", "symmetry")]
    if isinstance(bc, Empty):
        return [entry("type", "empty")]

    if isinstance(bc, Atmosphere):
        if not free_surface:
            raise ValueError(
                "Atmosphere BC requires free-surface physics (interFoam)")
        match field:
            case "U":
                return [entry("type", "pressureInletOutletVelocity"),
                        entry("value", "uniform (0 0 0)")]
            case "p_rgh":
                return [entry("type", "totalPressure"),
                        entry("p0", "uniform 0")]
            case "alpha.water":
                return [entry("type", "inletOutlet"),
                        entry("inletValue", "uniform 0"),
                        entry("value", "uniform 0")]
            case "k" | "omega" | "epsilon":
                v = fmt(_internal_turbulence(model)[field])
                return [entry("type", "inletOutlet"),
                        entry("inletValue", f"uniform {v}"),
                        entry("value", f"uniform {v}")]
            case "nut":
                return [entry("type", "calculated"), entry("value", "uniform 0")]

    if isinstance(bc, VelocityInlet):
        speed = inlet_reference_speed(model, patch, bc)
        tv = inlet_turbulence_values(model, bc, speed)
        match field:
            case "U":
                return inlet_velocity_entries(model, patch, bc)
            case "p":
                if bc.mode == "pressure":
                    return [entry("type", "fixedValue"),
                            entry("value", f"uniform {fmt(bc.inlet_pressure)}")]
                return [entry("type", "zeroGradient")]
            case "p_rgh":
                if bc.mode == "pressure":
                    return [entry("type", "fixedValue"),
                            entry("value", f"uniform {fmt(bc.inlet_pressure)}")]
                return [entry("type", "fixedFluxPressure"),
                        entry("value", "uniform 0")]
            case "alpha.water":
                if bc.alpha_water is None:  # face spans both phases
                    return [entry("type", "zeroGradient")]
                return [entry("type", "fixedValue"),
                        entry("value", f"uniform {fmt(bc.alpha_water)}")]
            case "k" | "omega" | "epsilon":
                return [entry("type", "fixedValue"),
                        entry("value", f"uniform {fmt(tv[field])}")]
            case "nut":
                return [entry("type", "calculated"), entry("value", "uniform 0")]

    if isinstance(bc, PressureOutlet):
        internal = _internal_turbulence(model)
        match field:
            case "U":
                if free_surface:
                    return [entry("type", "pressureInletOutletVelocity"),
                            entry("value", "uniform (0 0 0)")]
                return [entry("type", "inletOutlet"),
                        entry("inletValue", "uniform (0 0 0)"),
                        entry("value", "uniform (0 0 0)")]
            case "p":
                match bc.outlet_type:
                    case "totalPressure":
                        return [entry("type", "totalPressure"),
                                entry("p0", f"uniform {fmt(bc.total_pressure)}"),
                                entry("value", f"uniform {fmt(bc.total_pressure)}")]
                    case "fixedFlux":
                        return [entry("type", "fixedFluxPressure"),
                                entry("value", "uniform 0")]
                    case _:
                        return [entry("type", "fixedValue"),
                                entry("value", f"uniform {fmt(bc.gauge_pressure)}")]
            case "p_rgh":
                if bc.outlet_type == "fixedFlux":
                    return [entry("type", "fixedFluxPressure"),
                            entry("value", "uniform 0")]
                p0 = bc.total_pressure if bc.outlet_type == "totalPressure" \
                    else bc.gauge_pressure
                return [entry("type", "totalPressure"),
                        entry("p0", f"uniform {fmt(p0)}")]
            case "alpha.water":
                return [entry("type", "inletOutlet"),
                        entry("inletValue", "uniform 0"),
                        entry("value", "uniform 0")]
            case "k" | "omega" | "epsilon":
                v = fmt(internal[field])
                return [entry("type", "inletOutlet"),
                        entry("inletValue", f"uniform {v}"),
                        entry("value", f"uniform {v}")]
            case "nut":
                return [entry("type", "calculated"), entry("value", "uniform 0")]

    if isinstance(bc, Wall):
        internal = _internal_turbulence(model)
        match field:
            case "U":
                if bc.moving_velocity is not None:
                    return [entry("type", "fixedValue"),
                            entry("value", f"uniform {fmt(bc.moving_velocity)}")]
                return [entry("type", "noSlip")]
            case "p":
                return [entry("type", "zeroGradient")]
            case "p_rgh":
                # gravity-consistent wall pressure (damBreak convention)
                return [entry("type", "fixedFluxPressure"),
                        entry("value", "uniform 0")]
            case "alpha.water":
                return [entry("type", "zeroGradient")]
            case "k":
                return [entry("type", "kqRWallFunction"),
                        entry("value", f"uniform {fmt(internal['k'])}")]
            case "omega":
                return [entry("type", "omegaWallFunction"),
                        entry("value", f"uniform {fmt(internal['omega'])}")]
            case "epsilon":
                return [entry("type", "epsilonWallFunction"),
                        entry("value", f"uniform {fmt(internal['epsilon'])}")]
            case "nut":
                wall_fn = "nutkWallFunction"
                return [entry("type", wall_fn), entry("value", "uniform 0")]

    if isinstance(bc, SlipWall):
        match field:
            case "U":
                return [entry("type", "slip")]
            case "p_rgh":
                return [entry("type", "fixedFluxPressure"),
                        entry("value", "uniform 0")]
            case "nut":
                return [entry("type", "calculated"), entry("value", "uniform 0")]
            case _:
                return [entry("type", "zeroGradient")]

    if isinstance(bc, Outflow):
        match field:
            case "nut":
                return [entry("type", "calculated"), entry("value", "uniform 0")]
            case _:
                return [entry("type", "zeroGradient")]

    raise ValueError(f"No matrix entry for BC kind '{bc.kind}' field '{field}' (turb={turb})")


def _internal_turbulence(model: CaseModel) -> dict[str, float]:
    """internalField k/omega/epsilon from the Physics-derived reference values (§4.5)."""
    return {
        "k": model.physics.k_from(),
        "omega": model.physics.omega_from(),
        "epsilon": model.physics.epsilon_from(),
    }
