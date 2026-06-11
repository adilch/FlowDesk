"""App services: settings, templates, staleness, project lifecycle."""

from __future__ import annotations

import pytest

from flowdesk.app import projects
from flowdesk.app.settings import AppSettings, RecentProject
from flowdesk.app.staleness import StalenessTracker, downstream, patch_diff_summary
from flowdesk.app.templates import TEMPLATES, cavity
from flowdesk.model.findings import Stage

# ---------------------------------------------------------------------- settings


def test_recent_projects_capped_and_deduped(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(AppSettings, "_path", classmethod(lambda cls: tmp_path / "s.json"))
    s = AppSettings()
    for i in range(15):
        s.touch_recent(RecentProject(name=f"p{i}", path=f"/x/{i}"))
    assert len(s.recent) == 12
    s.touch_recent(RecentProject(name="p14", path="/x/14"))
    assert s.recent[0].path == "/x/14"
    assert sum(1 for r in s.recent if r.path == "/x/14") == 1

    s.save()
    loaded = AppSettings.load()
    assert loaded.recent[0].name == "p14"


def test_corrupt_settings_not_fatal(tmp_path, monkeypatch) -> None:
    path = tmp_path / "s.json"
    path.write_text("{not json")
    monkeypatch.setattr(AppSettings, "_path", classmethod(lambda cls: path))
    assert AppSettings.load().recent == []


# ---------------------------------------------------------------------- templates


def test_cavity_template_is_valid_and_runnable_shape() -> None:
    model = cavity("test")
    model.validated()  # §4.1: template must be a complete case
    assert model.enclosed_domain
    assert model.physics.solver == "simpleFoam"


def test_all_templates_construct() -> None:
    for factory in TEMPLATES.values():
        factory("x")  # Empty case is intentionally not valid; just constructible


# ---------------------------------------------------------------------- staleness


def test_downstream_graph() -> None:
    assert Stage.MESH in downstream(Stage.GEOMETRY)
    assert Stage.BOUNDARIES in downstream(Stage.GEOMETRY)  # transitive via mesh
    assert Stage.NUMERICS in downstream(Stage.PHYSICS)
    assert Stage.GEOMETRY not in downstream(Stage.MESH)


def test_staleness_mark_and_clear() -> None:
    t = StalenessTracker()
    affected = t.mark_applied(Stage.MESH, "patch list changed: + spillway")
    assert Stage.BOUNDARIES in affected
    assert t.is_stale(Stage.BOUNDARIES)
    assert "spillway" in t.reason(Stage.BOUNDARIES)
    t.clear(Stage.BOUNDARIES)
    assert not t.is_stale(Stage.BOUNDARIES)


def test_patch_diff_summary() -> None:
    assert patch_diff_summary(["a", "xMax"], ["a", "spillway"]) == \
        "patch list changed: + spillway, − xMax"
    assert patch_diff_summary(["a"], ["a"]) == ""


# ---------------------------------------------------------------------- projects


def test_create_cavity_project_writes_case(tmp_path) -> None:
    session = projects.create_project("cav", tmp_path, "Lid-driven cavity")
    assert (session.case_dir / "flowdesk.json").exists()
    assert (session.case_dir / "system" / "blockMeshDict").exists()
    assert (session.case_dir / "0" / "U").exists()


def test_create_empty_project_writes_sidecar_only(tmp_path) -> None:
    session = projects.create_project("empty", tmp_path, "Empty case")
    assert (session.case_dir / "flowdesk.json").exists()
    assert not (session.case_dir / "system").exists()


def test_create_rejects_bad_names(tmp_path) -> None:
    with pytest.raises(ValueError, match="empty"):
        projects.create_project("  ", tmp_path, "Empty case")
    with pytest.raises(ValueError, match="invalid"):
        projects.create_project("a<b", tmp_path, "Empty case")


def test_open_roundtrip(tmp_path) -> None:
    created = projects.create_project("cav", tmp_path, "Lid-driven cavity")
    opened = projects.open_project(created.case_dir)
    assert opened.model.meta.name == "cav"
    assert opened.model.enclosed_domain


def test_open_bare_case_imports(tmp_path) -> None:
    case = tmp_path / "bare"
    (case / "system").mkdir(parents=True)
    (case / "system" / "controlDict").write_text("FoamFile {}\n")
    session = projects.open_project(case)
    assert (case / "flowdesk.json").exists()
    assert "unmanaged" in session.unmanaged_note


def test_open_garbage_dir_refused(tmp_path) -> None:
    with pytest.raises(FileNotFoundError):
        projects.open_project(tmp_path)


def test_stage_statuses_for_fresh_cavity(tmp_path) -> None:
    session = projects.create_project("cav", tmp_path, "Lid-driven cavity")
    statuses = session.stage_statuses()
    assert statuses[Stage.GEOMETRY] == "complete"
    assert statuses[Stage.BOUNDARIES] == "complete"
    # §4.0: Run stays gated until a mesh actually exists
    assert statuses[Stage.MESH] == "in_progress"
    assert not session.run_enabled()

    from flowdesk.model.mesh import MeshResult, QualityReport

    session.model.mesh.result = MeshResult(cell_count=400,
                                           quality=QualityReport(mesh_ok=True))
    assert session.stage_statuses()[Stage.MESH] == "complete"
    assert session.run_enabled()


def test_stage_statuses_for_empty_project(tmp_path) -> None:
    session = projects.create_project("empty", tmp_path, "Empty case")
    statuses = session.stage_statuses()
    assert statuses[Stage.GEOMETRY] == "invalid"  # no geometry, not blockmesh-only
    assert not session.run_enabled()
