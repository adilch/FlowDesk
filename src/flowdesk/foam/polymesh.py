"""polyMesh/boundary maintenance (PRD §4.5): patch types must match the
assigned physical BCs - wall functions hard-require `type wall`, and symmetry
fields require `type symmetry`, in the *mesh*, not just the field files.

The journey meshes before BCs are assigned (§3.4), so FlowDesk syncs the
boundary file after assignment. wall/symmetry are safe in-place conversions;
`empty` changes 2D topology and must be set in the Mesh stage before meshing
(enforced by validation).
"""

from __future__ import annotations

import re
from pathlib import Path

from flowdesk.model.boundaries import BLOCK_PATCH_TYPE
from flowdesk.model.case import CaseModel

# Conversions that are safe on an existing mesh
_SYNCABLE = {"wall", "symmetry"}


def sync_boundary_types(model: CaseModel, case_dir: Path) -> list[tuple[str, str, str]]:
    """Rewrite patch types in constant/polyMesh/boundary to match assigned BCs.

    Returns (patch, old_type, new_type) for every change made. No-op when the
    mesh does not exist yet."""
    path = case_dir / "constant" / "polyMesh" / "boundary"
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    changes: list[tuple[str, str, str]] = []

    for patch, bc in model.boundaries.items():
        target = BLOCK_PATCH_TYPE[bc.kind]
        if target not in _SYNCABLE:
            continue

        # Match:  <patch>\n { ... type X; ... }   (first 'type' inside the block)
        block_re = re.compile(
            rf"(^\s*{re.escape(patch)}\s*\n\s*\{{[^}}]*?\btype\s+)(\w+)(;)",
            re.MULTILINE | re.DOTALL,
        )
        m = block_re.search(text)
        if m and m.group(2) != target:
            changes.append((patch, m.group(2), target))
            text = text[: m.start(2)] + target + text[m.end(2):]

    if changes:
        path.write_text(text, encoding="utf-8", newline="\n")
    return changes
