"""The case model (PRD §7.4): single source of truth, serialized to flowdesk.json.

Key behaviors: validate_full() is the only source of chip states and the pre-run
gate; no silently invalid case can be written (the write API takes a Validated
token obtainable only from a clean validation).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field

from flowdesk.model.boundaries import PhysicalBC, VelocityInlet
from flowdesk.model.findings import Finding, Severity, Stage, errors
from flowdesk.model.geometry import GeometryModel
from flowdesk.model.mesh import MeshModel
from flowdesk.model.numerics import NumericsModel, RunModel
from flowdesk.model.ownership import OwnershipMap
from flowdesk.model.physics import PhysicsModel

SCHEMA_VERSION = 1
SIDECAR_NAME = "flowdesk.json"

_OF_WORD = re.compile(r"^[A-Za-z][A-Za-z0-9_.:]*$")


class ProjectMeta(BaseModel):
    name: str = "Untitled"
    created: str = ""  # ISO 8601
    flowdesk_version: str = "0.1.0"
    of_profile: str = "com-v2506"


class CaseModel(BaseModel):
    schema_version: int = SCHEMA_VERSION
    meta: ProjectMeta = Field(default_factory=ProjectMeta)
    geometry: GeometryModel = Field(default_factory=GeometryModel)
    mesh: MeshModel = Field(default_factory=MeshModel)
    physics: PhysicsModel = Field(default_factory=PhysicsModel)
    boundaries: dict[str, PhysicalBC] = Field(default_factory=dict)  # patch name -> BC
    numerics: NumericsModel = Field(default_factory=NumericsModel)
    run: RunModel = Field(default_factory=RunModel)
    ownership: OwnershipMap = Field(default_factory=OwnershipMap)
    # Fully enclosed domain (cavity-style): allows no-inlet/no-outlet; adds pRef (§4.5)
    enclosed_domain: bool = False
    # Initialize U internalField with inlet velocity (§4.5, default on)
    init_from_inlet: bool = True

    # ------------------------------------------------------------------ patches

    def expected_patches(self) -> list[str]:
        """Patch names the meshed case will expose: blockMesh patches + snappy surfaces.

        After meshing, MeshResult.patches is authoritative; before meshing this
        is the best prediction (used by BC validation)."""
        if self.mesh.result is not None:
            return [p.name for p in self.mesh.result.patches]
        names = [p.name for p in self.mesh.block.patches]
        names += [s.name for s in self.geometry.surfaces]
        return names

    # ---------------------------------------------------------------- validation

    def validate_full(self) -> list[Finding]:
        findings: list[Finding] = []
        findings += self._validate_geometry()
        findings += self._validate_mesh()
        findings += self._validate_physics()
        findings += self._validate_boundaries()
        findings += self._validate_run()
        return findings

    def _validate_geometry(self) -> list[Finding]:
        out: list[Finding] = []
        if not self.geometry.surfaces and not self.geometry.blockmesh_only:
            out.append(Finding(
                Severity.ERROR, Stage.GEOMETRY,
                "No geometry imported. → Geometry → Import an STL, or check "
                "'blockMesh-only case' for a box-domain workflow.", "geometry.surfaces"))
        seen: set[str] = set()
        for s in self.geometry.surfaces:
            if not _OF_WORD.match(s.name):
                out.append(Finding(
                    Severity.ERROR, Stage.GEOMETRY,
                    f"Surface name '{s.name}' is not a valid OpenFOAM word. → Geometry → "
                    "Rename without spaces or special characters.", f"surface.{s.name}"))
            if s.name in seen:
                out.append(Finding(
                    Severity.ERROR, Stage.GEOMETRY,
                    f"Duplicate surface name '{s.name}'. → Geometry → Rename one of them.",
                    f"surface.{s.name}"))
            seen.add(s.name)
            if not s.diagnostics.watertight:
                out.append(Finding(
                    Severity.WARNING, Stage.GEOMETRY,
                    f"Surface '{s.name}' is not watertight — usable for snapping but not "
                    "as a closed-region boundary.", f"surface.{s.name}"))
        return out

    def _validate_mesh(self) -> list[Finding]:
        out: list[Finding] = []
        b = self.mesh.block
        for axis, (lo, hi) in enumerate(zip(b.bounds_min, b.bounds_max, strict=True)):
            if lo >= hi:
                out.append(Finding(
                    Severity.ERROR, Stage.MESH,
                    f"Domain min ≥ max on the {'xyz'[axis]} axis. → Mesh → Fix the bounds.",
                    "mesh.block.bounds"))
        if any(n < 1 for n in b.cells):
            out.append(Finding(
                Severity.ERROR, Stage.MESH,
                "Cell count must be ≥ 1 on every axis. → Mesh → Fix cell counts.",
                "mesh.block.cells"))
        if any(g <= 0 for g in b.grading):
            out.append(Finding(
                Severity.ERROR, Stage.MESH,
                "Grading must be > 0. → Mesh → Fix grading.", "mesh.block.grading"))
        names = [p.name for p in b.patches]
        if len(names) != len(set(names)):
            out.append(Finding(
                Severity.ERROR, Stage.MESH,
                "Patch names must be unique. → Mesh → Rename duplicates.", "mesh.block.patches"))
        for p in b.patches:
            if not _OF_WORD.match(p.name):
                out.append(Finding(
                    Severity.ERROR, Stage.MESH,
                    f"Patch name '{p.name}' is not a valid OpenFOAM word. → Mesh → Rename.",
                    f"mesh.block.patch.{p.name}"))
        projected = b.cells[0] * b.cells[1] * b.cells[2]
        if projected > 5_000_000:
            out.append(Finding(
                Severity.WARNING, Stage.MESH,
                f"Background mesh alone is {projected:,} cells (> 5 M). → Mesh → "
                "Increase target cell size.", "mesh.block.cells"))

        if self.geometry.surfaces:  # snappy applies
            s = self.mesh.snappy
            if s.location_in_mesh is None:
                out.append(Finding(
                    Severity.ERROR, Stage.MESH,
                    "Material point (locationInMesh) is not set. → Mesh → Pick or "
                    "suggest a point inside the fluid region.", "mesh.snappy.location_in_mesh"))
            elif not all(
                lo < c < hi for c, lo, hi in
                zip(s.location_in_mesh, b.bounds_min, b.bounds_max, strict=True)
            ):
                out.append(Finding(
                    Severity.ERROR, Stage.MESH,
                    "Material point is outside the background-mesh box. → Mesh → "
                    "Move it inside the domain.", "mesh.snappy.location_in_mesh"))
            refined = {r.surface for r in s.surfaces}
            for surf in self.geometry.surfaces:
                if surf.name not in refined:
                    out.append(Finding(
                        Severity.ERROR, Stage.MESH,
                        f"Surface '{surf.name}' has no refinement settings. → Mesh → "
                        "Add a refinement row.", f"mesh.snappy.{surf.name}"))
            for r in s.surfaces:
                if r.level_min > r.level_max:
                    out.append(Finding(
                        Severity.ERROR, Stage.MESH,
                        f"Refinement min > max on '{r.surface}'. → Mesh → Fix levels.",
                        f"mesh.snappy.{r.surface}"))
                if r.level_max >= 7:
                    out.append(Finding(
                        Severity.WARNING, Stage.MESH,
                        f"Refinement level {r.level_max} on '{r.surface}' — cell count "
                        "may explode.", f"mesh.snappy.{r.surface}"))
                if r.layers and r.layers.min_thickness >= r.layers.final_layer_thickness:
                    out.append(Finding(
                        Severity.ERROR, Stage.MESH,
                        f"Layer min thickness ≥ final thickness on '{r.surface}'. → Mesh → "
                        "Reduce min thickness.", f"mesh.snappy.{r.surface}.layers"))
                if r.layers and r.layers.expansion_ratio > 1.5:
                    out.append(Finding(
                        Severity.WARNING, Stage.MESH,
                        f"Layer expansion ratio {r.layers.expansion_ratio:g} > 1.5 on "
                        f"'{r.surface}' — layers may collapse.", f"mesh.snappy.{r.surface}.layers"))
        return out

    def _validate_physics(self) -> list[Finding]:
        out: list[Finding] = []
        if self.physics.fluid.nu <= 0:
            out.append(Finding(
                Severity.ERROR, Stage.PHYSICS,
                "Kinematic viscosity must be > 0. → Physics → Fix ν.", "physics.fluid.nu"))
        if not self.physics.is_steady:
            t = self.physics.time
            if t.end_time <= 0:
                out.append(Finding(
                    Severity.ERROR, Stage.PHYSICS,
                    "End time must be > 0. → Physics → Fix end time.", "physics.time.end_time"))
        i = self.physics.turb_ref.intensity
        if not 0.1 <= i <= 20:
            out.append(Finding(
                Severity.WARNING, Stage.PHYSICS,
                f"Turbulence intensity {i:g}% is outside the typical 0.1–20% range.",
                "physics.turb_ref.intensity"))
        return out

    def _validate_boundaries(self) -> list[Finding]:
        out: list[Finding] = []
        patches = self.expected_patches()
        for patch in patches:
            if patch not in self.boundaries:
                out.append(Finding(
                    Severity.ERROR, Stage.BOUNDARIES,
                    f"Patch '{patch}' has no boundary condition. → Boundary Conditions → "
                    "Assign a BC type. [Go to patch]", f"bc.{patch}"))
        for name in self.boundaries:
            if name not in patches:
                out.append(Finding(
                    Severity.WARNING, Stage.BOUNDARIES,
                    f"BC assigned to unknown patch '{name}' (patch list changed?). → "
                    "Boundary Conditions → Remove or reassign.", f"bc.{name}"))

        kinds = [bc.kind for bc in self.boundaries.values()]
        inlets = [n for n, bc in self.boundaries.items() if bc.kind == "velocityInlet"]
        has_outlet = any(k in ("pressureOutlet", "outflow") for k in kinds)
        if not self.enclosed_domain:
            if not inlets:
                out.append(Finding(
                    Severity.ERROR, Stage.BOUNDARIES,
                    "No inlet-type patch. → Boundary Conditions → Assign a Velocity inlet "
                    "(or check 'fully enclosed domain' for cavity-style cases).", "bc"))
            if not has_outlet:
                out.append(Finding(
                    Severity.ERROR, Stage.BOUNDARIES,
                    "No outlet-type patch. → Boundary Conditions → Assign a Pressure outlet "
                    "(or check 'fully enclosed domain').", "bc"))
        if len(inlets) == 1:
            bc = self.boundaries[inlets[0]]
            if isinstance(bc, VelocityInlet):
                magnitude = (
                    bc.speed if bc.mode == "normal"
                    else sum(c * c for c in bc.vector) ** 0.5
                )
                if magnitude == 0:
                    out.append(Finding(
                        Severity.ERROR, Stage.BOUNDARIES,
                        f"Velocity is 0 on the only inlet '{inlets[0]}'. → Boundary "
                        "Conditions → Set a non-zero velocity.", f"bc.{inlets[0]}"))
        return out

    def _validate_run(self) -> list[Finding]:
        out: list[Finding] = []
        if self.run.cores < 1:
            out.append(Finding(
                Severity.ERROR, Stage.RUN, "Core count must be ≥ 1. → Run → Fix cores.",
                "run.cores"))
        if self.run.decomposition == "hierarchical":
            nx, ny, nz = self.run.hierarchical_n
            if nx * ny * nz != self.run.cores:
                out.append(Finding(
                    Severity.ERROR, Stage.RUN,
                    f"Hierarchical decomposition {nx}×{ny}×{nz} ≠ {self.run.cores} cores. "
                    "→ Run → Fix the subdivision.", "run.hierarchical_n"))
        if self.run.max_iterations <= 0:
            out.append(Finding(
                Severity.ERROR, Stage.RUN,
                "Max iterations must be > 0. → Run → Fix.", "run.max_iterations"))
        return out

    # ----------------------------------------------------------------- gating

    def validated(self, scope: frozenset[Stage] | None = None) -> Validated:
        """Return a write token, or raise InvalidCaseError listing the blocking findings.

        scope=None means the full case (pre-run gate). A scoped token (e.g.
        {GEOMETRY, MESH} for mesh generation, which legally precedes BC
        assignment in the §3.4 journey) only requires those stages to be clean,
        and the writer correspondingly writes only the files those stages own."""
        found = self.validate_full()
        blocking = [f for f in errors(found) if scope is None or f.stage in scope]
        if blocking:
            raise InvalidCaseError(blocking)
        return Validated(model=self, findings=found, scope=scope)

    # ------------------------------------------------------------ persistence

    def save(self, case_dir: Path) -> Path:
        """Crash-safe write to <case>/flowdesk.json (temp + atomic rename, NFR §9)."""
        path = case_dir / SIDECAR_NAME
        if not self.meta.created:
            self.meta.created = datetime.now(UTC).isoformat(timespec="seconds")
        data = json.dumps(self.model_dump(mode="json"), indent=2, sort_keys=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(data + "\n", encoding="utf-8", newline="\n")
        tmp.replace(path)
        return path

    @classmethod
    def load(cls, case_dir: Path) -> CaseModel:
        raw = json.loads((case_dir / SIDECAR_NAME).read_text(encoding="utf-8"))
        version = raw.get("schema_version", 0)
        if version > SCHEMA_VERSION:
            raise ValueError(
                f"flowdesk.json schema {version} is newer than this FlowDesk "
                f"(supports ≤ {SCHEMA_VERSION}). Update FlowDesk.")
        raw = _migrate(raw, version)
        return cls.model_validate(raw)


@dataclass(frozen=True)
class Validated:
    """Proof of a clean validation; the only accepted input to the case writer."""

    model: CaseModel
    findings: list[Finding]
    scope: frozenset[Stage] | None = None  # None = full case

MESH_SCOPE = frozenset({Stage.GEOMETRY, Stage.MESH})


class InvalidCaseError(Exception):
    def __init__(self, blocking: list[Finding]):
        self.findings = blocking
        lines = "\n".join(f"  [{f.stage.value}] {f.message}" for f in blocking)
        super().__init__(f"Case has blocking validation errors:\n{lines}")


def _migrate(raw: dict, from_version: int) -> dict:
    """Schema migrations, supported from day 1 (§7.4). No-op while schema is v1."""
    return raw
