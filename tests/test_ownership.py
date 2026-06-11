"""Round-trip contract (§4.9): manual-edit detection, preservation, detach, take-back.

Includes the M1 gate demo: hand-editing fvSolution relaxation factors is detected,
preserved across subsequent writes, and surfaced.
"""

from __future__ import annotations

import re
from pathlib import Path

from foamlib import FoamFile

from flowdesk.foam import writer
from flowdesk.model.case import CaseModel


def _write(model: CaseModel, case_dir: Path) -> writer.WriteReport:
    return writer.write_case(model.validated(), case_dir)


def test_clean_write_records_hashes(box_model: CaseModel, tmp_path: Path) -> None:
    report = _write(box_model, tmp_path)
    assert "system/fvSolution" in report.written
    assert not report.skipped_detached
    for rel in report.written:
        assert box_model.ownership.files[rel].sha256


def test_rewrite_without_edits_is_byte_stable(box_model: CaseModel, tmp_path: Path) -> None:
    _write(box_model, tmp_path)
    before = {p: (tmp_path / p).read_bytes() for p in box_model.ownership.files}
    _write(box_model, tmp_path)
    after = {p: (tmp_path / p).read_bytes() for p in box_model.ownership.files}
    assert before == after


def test_manual_edit_detected_and_preserved(box_model: CaseModel, tmp_path: Path) -> None:
    """The M1 gate demo (PRD §3.5, §12.4): hand-tuned relaxation factors survive."""
    _write(box_model, tmp_path)
    fv_solution = tmp_path / "system" / "fvSolution"

    # Marcus hand-edits the relaxation factors
    text = fv_solution.read_text()
    text = re.sub(r"U\s+0\.5;", "U               0.85;", text, count=1)
    assert "0.85" in text
    fv_solution.write_text(text, encoding="utf-8", newline="\n")

    # Next write: edit detected, key marked user-owned, value preserved
    report = _write(box_model, tmp_path)
    assert "relaxationFactors" in box_model.ownership.files["system/fvSolution"].user_keys
    assert report.preserved_keys.get("system/fvSolution") == ["relaxationFactors"]
    parsed = FoamFile(fv_solution)
    assert parsed["relaxationFactors", "equations", "U"] == 0.85

    # ...and across a second subsequent write (acceptance criterion: two runs)
    _write(box_model, tmp_path)
    assert FoamFile(fv_solution)["relaxationFactors", "equations", "U"] == 0.85
    # untouched keys still managed
    assert FoamFile(fv_solution)["solvers", "p", "solver"] == "GAMG"


def test_unparseable_edit_detaches_file(box_model: CaseModel, tmp_path: Path) -> None:
    """§4.9 rule 4: a file foamlib can't round-trip is detached - never overwritten."""
    _write(box_model, tmp_path)
    control = tmp_path / "system" / "controlDict"
    mangled = "this { is not ( valid OpenFOAM %%%"
    control.write_text(mangled, encoding="utf-8")

    report = _write(box_model, tmp_path)
    assert "system/controlDict" in report.skipped_detached
    assert box_model.ownership.files["system/controlDict"].detached
    assert control.read_text() == mangled  # user's file untouched


def test_take_back_control(box_model: CaseModel, tmp_path: Path) -> None:
    _write(box_model, tmp_path)
    fv_solution = tmp_path / "system" / "fvSolution"
    text = fv_solution.read_text().replace("U               0.5;", "U               0.9;")
    fv_solution.write_text(text, encoding="utf-8", newline="\n")
    _write(box_model, tmp_path)
    assert box_model.ownership.files["system/fvSolution"].user_keys

    writer.take_back_control(box_model.validated(), tmp_path, "system/fvSolution")
    assert not box_model.ownership.files["system/fvSolution"].user_keys
    assert FoamFile(fv_solution)["relaxationFactors", "equations", "U"] == 0.5


def test_invalid_model_cannot_reach_writer(tmp_path: Path) -> None:
    """§12.6: zero ❌-validation case can ever be written (the API makes it impossible)."""
    import pytest

    from flowdesk.model.case import InvalidCaseError

    with pytest.raises(InvalidCaseError):
        CaseModel().validated()
    # write_case requires the Validated token; there is no path around it.
    assert not list(tmp_path.iterdir())


def test_sidecar_written_alongside(box_model: CaseModel, tmp_path: Path) -> None:
    _write(box_model, tmp_path)
    assert (tmp_path / "flowdesk.json").exists()
    loaded = CaseModel.load(tmp_path)
    assert loaded.ownership.files.keys() == box_model.ownership.files.keys()
