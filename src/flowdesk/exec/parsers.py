"""Stdout parsers (PRD §4.3.3): checkMesh -> QualityReport traffic lights."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from flowdesk.model.mesh import LayerCoverage, PatchInfo, QualityReport

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


class SnappyLayerParser:
    """Parses snappy's layer summary table (§4.3.3 layer coverage). Observed
    v2506 format (thicknesses in metres):

        patch faces    layers avg thickness[m]
                             near-wall overall
        ----- -----    ------ --------- -------
        weir 1864     2      0.00545   0.012
    """

    _ROW = re.compile(
        r"^\s*(\w+)\s+(\d+)\s+([\d.eE+-]+)\s+([\d.eE+-]+)\s+([\d.eE+-]+)\s*$")

    def __init__(self) -> None:
        # Upsert keyed by surface: snappy prints the table more than once
        # (specification pass, then the post-addition summary) - last wins.
        self._by_surface: dict[str, LayerCoverage] = {}
        self._in_table = False

    @property
    def coverage(self) -> list[LayerCoverage]:
        return list(self._by_surface.values())

    def feed(self, line: str) -> None:
        if re.match(r"^\s*patch\s+faces\s+layers", line):
            self._in_table = True
            return
        if not self._in_table:
            return
        if re.match(r"^\s*-+\s", line) or "near-wall" in line or "[m]" in line:
            return
        m = self._ROW.match(line)
        if m:
            self._by_surface[m.group(1)] = LayerCoverage(
                surface=m.group(1),
                n_faces=int(m.group(2)),
                layers_achieved=float(m.group(3)),
                thickness_near_wall=float(m.group(4)),
                thickness_overall=float(m.group(5)),
            )
        elif line.strip():  # first non-matching, non-blank line ends the table
            self._in_table = False


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
