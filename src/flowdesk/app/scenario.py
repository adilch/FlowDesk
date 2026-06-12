"""Step-by-step simulation-type selection (the 'model select' wizard).

A decision tree of physical scenarios that resolves to one of FlowDesk's
supported solvers and maps the choice onto PhysicsModel. Unsupported branches
are present but flagged `supported=False` so the UI can show the roadmap
(greyed cards) without letting a user reach a solver FlowDesk cannot run.

Headless: no Qt. ui/stages/model_selector.py renders this.
"""

from __future__ import annotations

from dataclasses import dataclass

from flowdesk.model.case import CaseModel
from flowdesk.model.physics import (
    FreeSurfaceModel,
    SteadyTime,
    TransientTime,
    Turbulence,
)

PHASE2_NOTE = "Planned for a future release — not in this version."


@dataclass(frozen=True)
class Resolution:
    """What a leaf scenario means for the physics model."""

    free_surface: bool
    force_transient: bool = False  # interFoam is transient-only


@dataclass(frozen=True)
class ScenarioNode:
    key: str
    label: str
    icon: str = ""
    children: tuple[ScenarioNode, ...] = ()
    resolution: Resolution | None = None
    supported: bool = True
    note: str = ""

    @property
    def is_leaf(self) -> bool:
        return self.resolution is not None


# The tree (SimScale-style). Only branches reaching simpleFoam/pimpleFoam/
# interFoam are supported in the MVP; the rest are visible-but-disabled.
TREE = ScenarioNode(
    key="root", label="Simulation Type", children=(
        ScenarioNode("singlePhase", "Single Phase", "≈", children=(
            ScenarioNode("incompressible", "Incompressible", "≈",
                         resolution=Resolution(free_surface=False)),
            ScenarioNode("compressible", "Compressible", "≋",
                         supported=False, note=PHASE2_NOTE),
        )),
        ScenarioNode("heatTransfer", "Heat Transfer", "♨",
                     supported=False, note=PHASE2_NOTE),
        ScenarioNode("multiphase", "Multiphase", "∿", children=(
            ScenarioNode("freeSurface", "Free Surface", "≋", children=(
                ScenarioNode("immiscible", "Immiscible", "≈", children=(
                    ScenarioNode("twoFluids", "2 Fluids", "⊓",
                                 resolution=Resolution(free_surface=True,
                                                       force_transient=True)),
                    ScenarioNode("multipleFluids", "Multiple Fluids", "≣",
                                 supported=False, note=PHASE2_NOTE),
                )),
                ScenarioNode("miscible", "Miscible", "⊜",
                             supported=False, note=PHASE2_NOTE),
            )),
            ScenarioNode("dispersed", "Dispersed", "∴",
                         supported=False, note=PHASE2_NOTE),
            ScenarioNode("phaseChange", "Phase Change", "↑",
                         supported=False, note=PHASE2_NOTE),
        )),
        ScenarioNode("multicomponent", "Multicomponent", "⋮",
                     supported=False, note=PHASE2_NOTE),
    ),
)

MANUAL_SOLVERS = ("simpleFoam", "pimpleFoam", "interFoam")


def node_at(path: list[str]) -> ScenarioNode:
    """The node reached by following child keys from the root."""
    node = TREE
    for key in path:
        node = next(c for c in node.children if c.key == key)
    return node


def breadcrumb_labels(path: list[str]) -> list[str]:
    labels, node = [], TREE
    for key in path:
        node = next(c for c in node.children if c.key == key)
        labels.append(node.label)
    return labels


def current_path(model: CaseModel) -> list[str]:
    """The tree path matching the model's current physics (for the breadcrumb)."""
    if model.physics.free_surface is not None:
        return ["multiphase", "freeSurface", "immiscible", "twoFluids"]
    return ["singlePhase", "incompressible"]


# --- applying a choice to the model ---------------------------------------------


def apply_resolution(model: CaseModel, res: Resolution) -> None:
    """Map a resolved leaf onto the physics model. Surgical: preserves an
    existing free-surface setup and only flips time treatment when required."""
    p = model.physics
    if res.free_surface:
        if p.free_surface is None:
            p.free_surface = FreeSurfaceModel()
        if isinstance(p.time, SteadyTime):
            p.time = TransientTime()
    else:
        p.free_surface = None
        if res.force_transient and isinstance(p.time, SteadyTime):
            p.time = TransientTime()


def apply_manual_solver(model: CaseModel, solver: str) -> None:
    """The 'Choose Solver Manually' bypass."""
    p = model.physics
    if solver == "interFoam":
        apply_resolution(model, Resolution(free_surface=True, force_transient=True))
    elif solver == "pimpleFoam":
        p.free_surface = None
        if isinstance(p.time, SteadyTime):
            p.time = TransientTime()
    elif solver == "simpleFoam":
        p.free_surface = None
        p.time = SteadyTime()
    else:
        raise ValueError(f"unknown solver: {solver}")


# --- resolved feature badges (PRD step-6 panel) ---------------------------------


@dataclass(frozen=True)
class Feature:
    label: str
    interactive: bool
    on: bool
    key: str = ""  # for interactive: "transient" | "turbulence"


def feature_badges(model: CaseModel) -> list[Feature]:
    p = model.physics
    turb_on = p.turbulence is not Turbulence.LAMINAR
    if p.free_surface is not None:
        return [
            Feature("Free Surface", False, True),
            Feature("Immiscible", False, True),
            Feature("VOF / MULES", False, True),
            Feature("PIMPLE", False, True),
            Feature("Incompressible", False, True),
            Feature("Gravity", False, True),
            Feature("Transient", False, True),  # interFoam: locked on
            Feature("Turbulence", True, turb_on, "turbulence"),
        ]
    transient = not p.is_steady
    return [
        Feature("Incompressible", False, True),
        Feature("Pressure Based", False, True),
        Feature("PIMPLE" if transient else "SIMPLE", False, True),
        Feature("Transient", True, transient, "transient"),
        Feature("Turbulence", True, turb_on, "turbulence"),
    ]


def set_feature(model: CaseModel, key: str, on: bool) -> None:
    p = model.physics
    if key == "transient" and p.free_surface is None:
        p.time = TransientTime() if on else SteadyTime()
    elif key == "turbulence":
        if on and p.turbulence is Turbulence.LAMINAR:
            p.turbulence = Turbulence.K_OMEGA_SST
        elif not on:
            p.turbulence = Turbulence.LAMINAR


def solver_for(model: CaseModel) -> str:
    return model.physics.solver
