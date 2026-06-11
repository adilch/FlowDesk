"""Case model: validation rules (§4), gating token, save/load round-trip."""

from __future__ import annotations

from pathlib import Path

import pytest

from flowdesk.model.boundaries import VelocityInlet
from flowdesk.model.case import CaseModel, InvalidCaseError
from flowdesk.model.findings import Severity, Stage


def _messages(findings, severity=None):
    return [f.message for f in findings if severity is None or f.severity is severity]


def test_default_model_is_invalid() -> None:
    """An empty model must not be writable: no geometry, unassigned patches."""
    model = CaseModel()
    with pytest.raises(InvalidCaseError):
        model.validated()


def test_box_model_validates_clean(box_model: CaseModel) -> None:
    assert not [f for f in box_model.validate_full() if f.severity is Severity.ERROR]
    box_model.validated()  # does not raise


def test_cavity_model_validates_clean(cavity_model: CaseModel) -> None:
    cavity_model.validated()


def test_unassigned_patch_is_error(box_model: CaseModel) -> None:
    del box_model.boundaries["outlet"]
    errors = [f for f in box_model.validate_full() if f.severity is Severity.ERROR]
    assert any("outlet" in f.message and f.stage is Stage.BOUNDARIES for f in errors)


def test_no_outlet_is_error_unless_enclosed(box_model: CaseModel) -> None:
    from flowdesk.model.boundaries import Wall

    box_model.boundaries["outlet"] = Wall()
    errors = [f for f in box_model.validate_full() if f.severity is Severity.ERROR]
    assert any("No outlet-type patch" in f.message for f in errors)

    box_model.enclosed_domain = True
    errors = [f for f in box_model.validate_full() if f.severity is Severity.ERROR]
    assert not any("No outlet-type patch" in f.message for f in errors)


def test_zero_velocity_on_only_inlet_is_error(box_model: CaseModel) -> None:
    box_model.boundaries["inlet"] = VelocityInlet(speed=0.0)
    errors = [f for f in box_model.validate_full() if f.severity is Severity.ERROR]
    assert any("Velocity is 0" in f.message for f in errors)


def test_bounds_min_ge_max_is_error(box_model: CaseModel) -> None:
    box_model.mesh.block.bounds_min = (5.0, -1.0, 0.0)
    errors = [f for f in box_model.validate_full() if f.severity is Severity.ERROR]
    assert any("min ≥ max" in f.message for f in errors)


def test_hierarchical_core_mismatch_is_error(box_model: CaseModel) -> None:
    box_model.run.decomposition = "hierarchical"
    box_model.run.cores = 6
    box_model.run.hierarchical_n = (2, 2, 1)
    errors = [f for f in box_model.validate_full() if f.severity is Severity.ERROR]
    assert any("Hierarchical" in f.message for f in errors)


def test_save_load_roundtrip(box_model: CaseModel, tmp_path: Path) -> None:
    box_model.save(tmp_path)
    loaded = CaseModel.load(tmp_path)
    assert loaded == box_model


def test_save_is_deterministic(box_model: CaseModel, tmp_path: Path) -> None:
    box_model.meta.created = "2026-06-11T00:00:00+00:00"
    p1 = box_model.save(tmp_path)
    first = p1.read_bytes()
    p2 = box_model.save(tmp_path)
    assert p2.read_bytes() == first


def test_newer_schema_refused(box_model: CaseModel, tmp_path: Path) -> None:
    box_model.save(tmp_path)
    import json

    sidecar = tmp_path / "flowdesk.json"
    raw = json.loads(sidecar.read_text())
    raw["schema_version"] = 999
    sidecar.write_text(json.dumps(raw))
    with pytest.raises(ValueError, match="newer"):
        CaseModel.load(tmp_path)
