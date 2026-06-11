"""Case writer: Validated model -> case directory on disk, honoring ownership.

The write API takes a Validated token (PRD §7.4: no silently invalid case can
ever be written). Sequence per file: reconcile -> skip detached -> write
generated text -> re-apply user-owned keys -> record hash.
"""

from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from flowdesk.foam import generators
from flowdesk.foam import ownership as own
from flowdesk.model.case import Validated
from flowdesk.model.ownership import FileOwnership


@dataclass
class WriteReport:
    written: list[str] = field(default_factory=list)
    skipped_detached: list[str] = field(default_factory=list)
    preserved_keys: dict[str, list[str]] = field(default_factory=dict)


def write_case(validated: Validated, case_dir: Path) -> WriteReport:
    """Write all managed files. Returns what happened, honestly."""
    model = validated.model
    generated = generators.generate_case(model)
    report = WriteReport()

    results = own.reconcile_all(case_dir, generated, model.ownership)
    own.apply_reconciliation(model.ownership, results)

    for rel_path, text in sorted(generated.items()):
        record = model.ownership.files.setdefault(rel_path, FileOwnership())
        if record.detached:
            report.skipped_detached.append(rel_path)
            continue

        path = case_dir / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)

        user_edit_backup: Path | None = None
        if record.user_keys and path.exists():
            # The on-disk file holds the user-owned values (whether the edit was
            # made just now or in a past session) - stash it so they survive.
            tmp = Path(tempfile.mkdtemp()) / path.name
            shutil.copy2(path, tmp)
            user_edit_backup = tmp

        path.write_text(text, encoding="utf-8", newline="\n")

        if user_edit_backup is not None:
            own.preserve_user_keys(path, record.user_keys, user_edit_backup)
            report.preserved_keys[rel_path] = list(record.user_keys)
            shutil.rmtree(user_edit_backup.parent, ignore_errors=True)

        # Never write a file FlowDesk couldn't re-read (§4.9 rule 5)
        if own.parse_top_level(path) is None:
            raise RuntimeError(f"FlowDesk wrote an unparseable file: {rel_path}")

        record.sha256 = own.sha256_of(path)
        report.written.append(rel_path)

    model.save(case_dir)
    return report


def take_back_control(validated: Validated, case_dir: Path, rel_path: str,
                      keys: list[str] | None = None) -> WriteReport:
    """'Take back control' (§4.9): drop user ownership (all keys, or some) and rewrite.

    The user's values for the reclaimed keys are discarded - that is the point
    of the button - so the on-disk file must stop looking like an edit before
    reconciliation runs again.
    """
    model = validated.model
    record = model.ownership.files.get(rel_path)
    path = case_dir / rel_path
    if record is not None:
        if keys is None:
            # Full revert to managed: a fresh write replaces the file entirely.
            record.user_keys = []
            record.detached = False
            path.unlink(missing_ok=True)
        else:
            # Partial reclaim: reset just those keys to generated values on disk,
            # keeping the user's remaining owned keys intact.
            generated_text = generators.generate_case(model)[rel_path]
            with tempfile.TemporaryDirectory() as tmp:
                ref = Path(tmp) / path.name
                ref.write_text(generated_text, encoding="utf-8", newline="\n")
                own.preserve_user_keys(path, keys, ref)
            record.user_keys = [k for k in record.user_keys if k not in keys]
        record.sha256 = ""  # force the regeneration path
    return write_case(validated, case_dir)
