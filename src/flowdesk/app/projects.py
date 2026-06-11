"""Project lifecycle (PRD §4.1): create from template, open, import bare cases."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from flowdesk.app.settings import AppSettings, RecentProject
from flowdesk.app.staleness import StalenessTracker
from flowdesk.app.templates import TEMPLATE_PREPARERS, TEMPLATES
from flowdesk.model.case import SIDECAR_NAME, CaseModel, InvalidCaseError
from flowdesk.model.findings import Severity, Stage, stage_status

_INVALID_NAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

# OpenFOAM's fileName parser rejects whitespace, parentheses, quotes and a few
# shell/parser-special characters anywhere in a case path. It calls
# fileName::stripInvalid() and, at debug level >= 2 (the default in the ESI
# Ubuntu packages), treats this as fatal - so a project under e.g.
# "New folder (2)" dies in surfaceFeatureExtract/blockMesh with a cryptic error.
# We check each path component (never the separators).
_OPENFOAM_HOSTILE = re.compile(r"""[\s()\[\]{}"'#;&|<>$`]""")


def validate_project_name(name: str) -> str | None:
    """Returns an error message or None. Spaces are a warning handled in the UI."""
    if not name.strip():
        return "Project name is empty."
    if _INVALID_NAME_CHARS.search(name):
        return "Project name contains characters invalid on the target filesystem."
    return None


def openfoam_path_problem(path: Path) -> str | None:
    """Explanation if a case path contains characters OpenFOAM cannot handle
    (spaces, parentheses, quotes, ...), else None. Checked per directory
    component so path separators and the drive anchor are never flagged."""
    bad: set[str] = set()
    for part in Path(path).parts[1:]:  # skip the anchor (drive / root)
        bad.update(_OPENFOAM_HOSTILE.findall(part))
    if not bad:
        return None
    shown = ", ".join("space" if c.isspace() else f"'{c}'" for c in sorted(bad))
    return (
        f"The case path {path} contains characters OpenFOAM rejects: {shown}. "
        "OpenFOAM aborts on these (e.g. a 'New folder (2)' parent). → Move or "
        "rename the project and its parent folders to use only letters, "
        "numbers, '_' and '-'.")


@dataclass
class ProjectSession:
    """One open project: the model, where it lives, and per-session UI state."""

    model: CaseModel
    case_dir: Path
    staleness: StalenessTracker = field(default_factory=StalenessTracker)
    unmanaged_note: str = ""  # set by bare-case import

    def save_model(self) -> None:
        self.model.save(self.case_dir)

    def stage_statuses(self) -> dict[Stage, str]:
        """Chip state per stage (§4.0), combining findings + staleness."""
        findings = self.model.validate_full()
        out: dict[Stage, str] = {}
        for stage in Stage:
            if self.staleness.is_stale(stage):
                out[stage] = "stale"
                continue
            out[stage] = stage_status(findings, stage, self._started(stage))
        # Mesh settings can be valid without a mesh existing yet: the stage is
        # only ✔ once the pipeline has actually produced one (§4.0 Run gating)
        if out[Stage.MESH] == "complete" and self.model.mesh.result is None:
            out[Stage.MESH] = "in_progress"
        return out

    def _started(self, stage: Stage) -> bool:
        m = self.model
        match stage:
            case Stage.GEOMETRY:
                return bool(m.geometry.surfaces) or m.geometry.blockmesh_only
            case Stage.MESH:
                return m.mesh.result is not None or self._started(Stage.GEOMETRY)
            case Stage.BOUNDARIES:
                return bool(m.boundaries)
            case Stage.RESULTS:
                return any(
                    p.name.replace(".", "").isdigit() and p.name != "0"
                    for p in self.case_dir.iterdir() if p.is_dir()
                ) if self.case_dir.exists() else False
            case _:
                return True  # physics/numerics/run have valid defaults

    def run_enabled(self) -> bool:
        """§4.0: Run enabled only when Geometry..Numerics are ✔ or ⚠."""
        statuses = self.stage_statuses()
        gates = [Stage.GEOMETRY, Stage.MESH, Stage.PHYSICS, Stage.BOUNDARIES, Stage.NUMERICS]
        return all(statuses[s] in ("complete", "warnings") for s in gates)


def create_project(name: str, location: Path, template: str,
                   settings: AppSettings | None = None) -> ProjectSession:
    error = validate_project_name(name)
    if error:
        raise ValueError(error)
    if template not in TEMPLATES:
        raise ValueError(f"Unknown template: {template}")

    case_dir = location / name
    case_dir.mkdir(parents=True, exist_ok=False)
    model = TEMPLATES[template](name)
    model.meta.created = datetime.now(UTC).isoformat(timespec="seconds")

    preparer = TEMPLATE_PREPARERS.get(template)
    if preparer is not None:
        preparer(model, case_dir)  # geometry-bearing templates generate their STL

    # Templates are complete runnable cases: write the case files now when valid;
    # the Empty template has nothing valid to write yet - sidecar only.
    try:
        from flowdesk.foam import writer

        writer.write_case(model.validated(), case_dir)
    except InvalidCaseError:
        model.save(case_dir)

    session = ProjectSession(model=model, case_dir=case_dir)
    _touch_recent(session, settings)
    return session


def open_project(case_dir: Path, settings: AppSettings | None = None) -> ProjectSession:
    """Open a FlowDesk project, or import a bare OpenFOAM case (§4.1)."""
    case_dir = Path(case_dir)
    if (case_dir / SIDECAR_NAME).exists():
        session = ProjectSession(model=CaseModel.load(case_dir), case_dir=case_dir)
    elif (case_dir / "system" / "controlDict").exists():
        session = _import_bare_case(case_dir)
    else:
        raise FileNotFoundError(
            f"Not a FlowDesk project or OpenFOAM case: {case_dir} "
            "(no flowdesk.json or system/controlDict)")
    _touch_recent(session, settings)
    return session


def _import_bare_case(case_dir: Path) -> ProjectSession:
    """Bare-case import: create a sidecar, map what we can, flag the rest ℹ (§4.1).

    M2 maps nothing yet (stage mapping grows with each stage's UI); every
    existing file is unmanaged, which the file browser already explains."""
    model = CaseModel()
    model.meta.name = case_dir.name
    model.meta.created = datetime.now(UTC).isoformat(timespec="seconds")
    model.save(case_dir)
    session = ProjectSession(model=model, case_dir=case_dir)
    session.unmanaged_note = (
        "Imported a bare OpenFOAM case: existing files are unmanaged until the "
        "matching stage is configured in FlowDesk (they will never be overwritten "
        "silently).")
    return session


def _touch_recent(session: ProjectSession, settings: AppSettings | None) -> None:
    if settings is None:
        return
    findings = [f for f in session.model.validate_full() if f.severity is Severity.ERROR]
    settings.touch_recent(RecentProject(
        name=session.model.meta.name,
        path=str(session.case_dir),
        solver=session.model.physics.solver if not findings else "",
        cell_count=session.model.mesh.result.cell_count if session.model.mesh.result else 0,
        last_opened=datetime.now(UTC).isoformat(timespec="seconds"),
    ))
    settings.save()
