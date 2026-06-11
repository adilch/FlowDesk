"""Round-trip contract engine (PRD §4.9) - the honesty mechanism.

1. Every managed file is recorded with a content hash after writing.
2. Before any write, hashes are re-checked; a mismatch = manual edit detected.
3. The edited file is re-parsed (foamlib). Per top-level key: equal to what
   FlowDesk would generate -> still managed; different -> user-owned (preserved).
4. Unparseable -> the whole file is detached: FlowDesk stops writing it.
5. Never write a file FlowDesk couldn't re-read.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

from foamlib import FoamFile

from flowdesk.model.ownership import FileOwnership, OwnershipMap


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass(frozen=True)
class Reconciliation:
    """Outcome of comparing one on-disk file against the ownership record."""

    rel_path: str
    state: str  # "clean" | "edited" | "detached" | "missing"
    user_keys: list[str] = field(default_factory=list)


def parse_top_level(path: Path) -> dict | None:
    """Parse a dictionary file to {top-level key: value}; None if foamlib can't read it."""
    try:
        return FoamFile(path).as_dict()
    except Exception:
        return None


def reconcile_file(
    case_dir: Path, rel_path: str, generated_text: str, record: FileOwnership
) -> Reconciliation:
    """Detect manual edits to one managed file (steps 2-4 of the contract)."""
    path = case_dir / rel_path
    if not path.exists():
        return Reconciliation(rel_path, "missing")
    if record.sha256 and sha256_of(path) == record.sha256:
        return Reconciliation(rel_path, "clean", user_keys=list(record.user_keys))

    on_disk = parse_top_level(path)
    if on_disk is None:
        return Reconciliation(rel_path, "detached")

    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        ref = Path(tmp) / Path(rel_path).name
        ref.write_text(generated_text, encoding="utf-8", newline="\n")
        expected = parse_top_level(ref)
    if expected is None:  # we generated something foamlib can't read - a FlowDesk bug
        raise RuntimeError(f"FlowDesk generated an unparseable file: {rel_path}")

    user_keys = sorted(
        set(record.user_keys)
        | {k for k in on_disk if k != "FoamFile" and on_disk.get(k) != expected.get(k)}
        | {k for k in expected if k != "FoamFile" and k not in on_disk}
    )
    return Reconciliation(rel_path, "edited", user_keys=user_keys)


def reconcile_all(
    case_dir: Path, generated: dict[str, str], ownership: OwnershipMap
) -> list[Reconciliation]:
    results = []
    for rel_path, text in sorted(generated.items()):
        record = ownership.files.get(rel_path, FileOwnership())
        results.append(reconcile_file(case_dir, rel_path, text, record))
    return results


def apply_reconciliation(ownership: OwnershipMap, results: list[Reconciliation]) -> None:
    """Fold detection results into the ownership map (before writing)."""
    for r in results:
        record = ownership.files.setdefault(r.rel_path, FileOwnership())
        if r.state == "detached":
            record.detached = True
        elif r.state == "edited":
            record.user_keys = r.user_keys


def preserve_user_keys(path: Path, user_keys: list[str], edited_path: Path) -> None:
    """Copy user-owned top-level key values from the user's edited file into a
    freshly generated file (FlowDesk preserves what it no longer manages)."""
    if not user_keys:
        return
    source = FoamFile(edited_path)
    target = FoamFile(path)
    for key in user_keys:
        try:
            target[key] = source[key]
        except KeyError:
            continue  # user deleted the key entirely; leave the generated value
