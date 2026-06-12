"""Solver-aware boundary-condition catalog (SimFlow-style).

Headless. Tells the BC stage which physical characters, inlet/outlet sub-types,
field groups, and per-field override types to offer for the current solver and
physics - the 'available characters depend on the selected solver' idea.
"""

from __future__ import annotations

from flowdesk.foam import bc_matrix
from flowdesk.model.case import CaseModel
from flowdesk.model.physics import Turbulence

# Physical BC characters, with the kinds available per solver family.
_BASE_KINDS = [
    ("velocityInlet", "Velocity inlet"),
    ("pressureOutlet", "Pressure outlet"),
    ("wall", "Wall (no-slip)"),
    ("slip", "Slip wall"),
    ("symmetry", "Symmetry"),
    ("outflow", "Outflow (zero-gradient)"),
    ("empty", "Empty (2D)"),
]
_FREE_SURFACE_KINDS = [("atmosphere", "Atmosphere (open)")]

INLET_SPECS = [
    ("normal", "Normal speed"),
    ("vector", "Velocity vector"),
    ("volumetricFlowRate", "Volumetric flow rate"),
    ("massFlowRate", "Mass flow rate"),
    ("pressure", "Pressure-driven"),
]

OUTLET_TYPES = [
    ("fixedValue", "Fixed (gauge) pressure"),
    ("totalPressure", "Total pressure"),
    ("fixedFlux", "Fixed-flux pressure"),
]


def available_kinds(model: CaseModel) -> list[tuple[str, str]]:
    """Physical BC characters offered for the active solver."""
    kinds = list(_BASE_KINDS)
    if model.physics.free_surface is not None:
        kinds += _FREE_SURFACE_KINDS
    return kinds


def field_groups(model: CaseModel) -> list[tuple[str, list[str]]]:
    """Fields grouped into SimFlow-style tabs, filtered to what this case has.

    Flow (U + pressure), Turbulence (k/omega/epsilon/nut), Phase (alpha.water)."""
    free_surface = model.physics.free_surface is not None
    present = bc_matrix.fields_for(model.physics.turbulence, free_surface)
    groups: list[tuple[str, list[str]]] = []

    flow = [f for f in ("U", "p", "p_rgh") if f in present]
    groups.append(("Flow", flow))

    turb = [f for f in ("k", "omega", "epsilon", "nut") if f in present]
    if turb:
        groups.append(("Turbulence", turb))

    phase = [f for f in ("alpha.water",) if f in present]
    if phase:
        groups.append(("Phase", phase))
    return groups


# Per-field override types (curated OpenFOAM patch-field types appropriate to
# each field). Vector vs scalar matters; pressure and phase have their own sets.
_VECTOR_TYPES = [
    ("fixedValue", "Fixed value"),
    ("zeroGradient", "Zero gradient"),
    ("noSlip", "No-slip"),
    ("slip", "Slip"),
    ("inletOutlet", "Inlet-outlet"),
    ("pressureInletOutletVelocity", "Pressure inlet-outlet velocity"),
    ("flowRateInletVelocity", "Flow-rate inlet velocity"),
    ("surfaceNormalFixedValue", "Surface-normal fixed value"),
    ("calculated", "Calculated"),
]
_PRESSURE_TYPES = [
    ("fixedValue", "Fixed value"),
    ("zeroGradient", "Zero gradient"),
    ("totalPressure", "Total pressure"),
    ("fixedFluxPressure", "Fixed-flux pressure"),
    ("prghTotalHydrostaticPressure", "Hydrostatic total pressure"),
]
_PHASE_TYPES = [
    ("fixedValue", "Fixed value"),
    ("zeroGradient", "Zero gradient"),
    ("inletOutlet", "Inlet-outlet"),
    ("variableHeightFlowRate", "Variable-height flow rate"),
]
_SCALAR_TYPES = [
    ("fixedValue", "Fixed value"),
    ("zeroGradient", "Zero gradient"),
    ("inletOutlet", "Inlet-outlet"),
    ("calculated", "Calculated"),
    ("kqRWallFunction", "k wall function"),
    ("omegaWallFunction", "omega wall function"),
    ("epsilonWallFunction", "epsilon wall function"),
    ("nutkWallFunction", "nut wall function"),
]


def override_types_for_field(field: str) -> list[tuple[str, str]]:
    """OpenFOAM patch-field types offered when overriding `field`."""
    if field == "U":
        return _VECTOR_TYPES
    if field in ("p", "p_rgh"):
        return _PRESSURE_TYPES
    if field == "alpha.water":
        return _PHASE_TYPES
    return _SCALAR_TYPES


def field_is_vector(field: str) -> bool:
    return field == "U"


def turbulence_label(model: CaseModel) -> str:
    t = model.physics.turbulence
    return {Turbulence.LAMINAR: "laminar",
            Turbulence.K_EPSILON: "k-ε",
            Turbulence.K_OMEGA_SST: "k-ω SST"}[t]
