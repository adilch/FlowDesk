"""User-created templates: save a finished case as a reusable starting point.

Stored under ~/.flowdesk/templates/<slug>/ as the serialized CaseModel plus a
copy of its geometry STLs, so a template is self-contained and portable. The
New Project gallery lists these alongside the built-in templates.
"""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from flowdesk.model.case import CaseModel
from flowdesk.model.ownership import OwnershipMap


def templates_dir() -> Path:
    return Path.home() / ".flowdesk" / "templates"


def _slug(name: str) -> str:
    s = re.sub(r"[^A-Za-z0-9_-]+", "-", name.strip()).strip("-")
    return s or "template"


@dataclass
class UserTemplate:
    slug: str
    name: str
    description: str
    created: str
    solver: str
    has_geometry: bool
    path: Path


def save_as_template(model: CaseModel, case_dir: Path, name: str,
                     description: str = "") -> UserTemplate:
    """Snapshot the current case as a reusable template (model + geometry STLs).
    Strips run-specific state so the template is a clean starting point."""
    if not name.strip():
        raise ValueError("Template name is empty.")
    slug = _slug(name)
    dest = templates_dir() / slug
    dest.mkdir(parents=True, exist_ok=True)

    snapshot = model.model_copy(deep=True)
    snapshot.mesh.result = None  # a template carries settings, not a stale mesh
    snapshot.ownership = OwnershipMap()  # fresh: the new case regenerates files

    meta = {
        "name": name,
        "description": description,
        "created": datetime.now(UTC).isoformat(timespec="seconds"),
        "solver": model.physics.solver,
        "has_geometry": bool(model.geometry.surfaces),
    }
    payload = {"meta": meta, "model": snapshot.model_dump(mode="json")}
    (dest / "template.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8", newline="\n")

    geo_dir = dest / "geometry"
    if geo_dir.exists():
        shutil.rmtree(geo_dir)
    src_tri = case_dir / "constant" / "triSurface"
    for surf in model.geometry.surfaces:
        stl = src_tri / f"{surf.name}.stl"
        if stl.exists():
            geo_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(stl, geo_dir / f"{surf.name}.stl")

    loaded = _load_meta(dest)
    assert loaded is not None  # we just wrote it
    return loaded


def _load_meta(slug_dir: Path) -> UserTemplate | None:
    f = slug_dir / "template.json"
    if not f.exists():
        return None
    try:
        meta = json.loads(f.read_text(encoding="utf-8"))["meta"]
    except (json.JSONDecodeError, KeyError, OSError):
        return None
    return UserTemplate(
        slug=slug_dir.name, name=meta.get("name", slug_dir.name),
        description=meta.get("description", ""), created=meta.get("created", ""),
        solver=meta.get("solver", ""), has_geometry=meta.get("has_geometry", False),
        path=slug_dir)


def list_user_templates() -> list[UserTemplate]:
    root = templates_dir()
    if not root.exists():
        return []
    out = []
    for d in sorted(root.iterdir()):
        if d.is_dir() and (t := _load_meta(d)) is not None:
            out.append(t)
    return out


def get_user_template(name: str) -> UserTemplate | None:
    for t in list_user_templates():
        if name in (t.name, t.slug):
            return t
    return None


def delete_template(name: str) -> bool:
    t = get_user_template(name)
    if t is None:
        return False
    shutil.rmtree(t.path, ignore_errors=True)
    return True


def instantiate(template: UserTemplate, project_name: str, case_dir: Path) -> CaseModel:
    """Materialize a user template into a new case directory."""
    payload = json.loads((template.path / "template.json").read_text(encoding="utf-8"))
    model = CaseModel.model_validate(payload["model"])
    model.meta.name = project_name
    model.meta.created = datetime.now(UTC).isoformat(timespec="seconds")
    geo_dir = template.path / "geometry"
    if geo_dir.exists():
        tri = case_dir / "constant" / "triSurface"
        tri.mkdir(parents=True, exist_ok=True)
        for stl in geo_dir.glob("*.stl"):
            shutil.copy2(stl, tri / stl.name)
    return model
