"""Stdout parsers (PRD §4.3.3): checkMesh -> QualityReport traffic lights."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from flowdesk.model.mesh import PatchInfo, QualityReport

# §4.3.3 thresholds: (pass below, warn below; above = fail)
THRESHOLDS = {
    "max_non_ortho": (65.0, 75.0),
    "max_skewness": (4.0, 8.0),
    "max_aspect_ratio": (100.0, 1000.0),
}

_PATTERNS = {
    "cells": re.compile(r"^\s*cells:\s+(\d+)"),
    "non_ortho": re.compile(r"Mesh non-orthogonality Max:\s*([\d.eE+-]+)"),
    "skewness": re.compile(r"Max skewness =\s*([\d.eE+-]+)"),
    "aspect": re.compile(r"Max aspect ratio =\s*([\d.eE+-]+)"),
    # checkMesh phrasing: "Number of negative volume cells: 3" (and variants)
    "neg_volume": re.compile(
        r"(?:Number of negative volume cells:\s*(\d+)"
        r"|(\d+)\s+cells? with (?:zero or )?negative volume)"),
    "ok": re.compile(r"^\s*Mesh OK\.\s*$"),
    "failed": re.compile(r"^\s*Failed\s+(\d+)\s+mesh checks"),
}


@dataclass
class CheckMeshParser:
    """Feed lines from a checkMesh run; read .report when done."""

    cell_count: int = 0
    report: QualityReport = field(default_factory=QualityReport)

    def feed(self, line: str) -> None:
        if m := _PATTERNS["cells"].search(line):
            self.cell_count = int(m.group(1))
        elif m := _PATTERNS["non_ortho"].search(line):
            self.report.max_non_ortho = float(m.group(1))
        elif m := _PATTERNS["skewness"].search(line):
            self.report.max_skewness = float(m.group(1))
        elif m := _PATTERNS["aspect"].search(line):
            self.report.max_aspect_ratio = float(m.group(1))
        elif m := _PATTERNS["neg_volume"].search(line):
            self.report.negative_volume_cells = int(m.group(1) or m.group(2))
        elif _PATTERNS["ok"].search(line):
            self.report.mesh_ok = True
        elif _PATTERNS["failed"].search(line):
            self.report.mesh_ok = False


def verdict(metric: str, value: float | None) -> str:
    """'pass' | 'warn' | 'fail' | 'unknown' per the §4.3.3 table."""
    if value is None:
        return "unknown"
    ok, warn = THRESHOLDS[metric]
    if value < ok:
        return "pass"
    if value <= warn:
        return "warn"
    return "fail"


def read_boundary_patches(case_dir: Path) -> list[PatchInfo]:
    """Patch names + face counts from constant/polyMesh/boundary (post-mesh truth)."""
    path = case_dir / "constant" / "polyMesh" / "boundary"
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8", errors="replace")
    patches = []
    # Entries look like:  name\n {\n type patch;\n ... nFaces 240;\n ... }
    for m in re.finditer(r"(\w+)\s*\{([^}]*)\}", text):
        name, body = m.group(1), m.group(2)
        if name == "FoamFile":
            continue
        faces = re.search(r"nFaces\s+(\d+)\s*;", body)
        if faces:
            patches.append(PatchInfo(name=name, n_faces=int(faces.group(1))))
    return patches
