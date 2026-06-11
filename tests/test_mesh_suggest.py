"""Mesh auto-suggestions: bounds/cell-size defaults, locationInMesh candidates."""

from __future__ import annotations

import math
from pathlib import Path

import pytest
import pyvista as pv

from flowdesk.app import mesh_suggest
from flowdesk.model.case import CaseModel
from flowdesk.model.geometry import Surface, SurfaceDiagnostics


def _model_with_box_surface(case_dir: Path | None = None) -> CaseModel:
    """A watertight 0.2 x 0.7 x 0.35 box 'weir' surface, optionally on disk."""
    model = CaseModel()
    bounds_min, bounds_max = (0.9, -0.05, -0.05), (1.1, 0.65, 0.3)
    model.geometry.surfaces = [Surface(
        name="weir", stl_path="weir.stl",
        diagnostics=SurfaceDiagnostics(
            triangle_count=12, bounds_min=bounds_min, bounds_max=bounds_max,
            watertight=True),
    )]
    if case_dir is not None:
        stl = case_dir / "constant" / "triSurface" / "weir.stl"
        stl.parent.mkdir(parents=True, exist_ok=True)
        box = pv.Box(bounds=(bounds_min[0], bounds_max[0], bounds_min[1],
                             bounds_max[1], bounds_min[2], bounds_max[2]))
        box.extract_surface().triangulate().save(str(stl))
    return model


def test_suggest_bounds_external_padding() -> None:
    model = _model_with_box_surface()
    lo, hi = mesh_suggest.suggest_bounds(model, external=True)
    diag = math.dist((0.9, -0.05, -0.05), (1.1, 0.65, 0.3))
    assert lo[0] == pytest.approx(0.9 - diag)
    assert hi[1] == pytest.approx(0.65 + diag)


def test_suggest_cell_size_is_diag_over_40() -> None:
    size = mesh_suggest.suggest_cell_size((0, 0, 0), (4, 0, 3))
    assert size == pytest.approx(5.0 / 40.0)
    assert mesh_suggest.cells_from_size((0, 0, 0), (1, 1, 1), 0.05) == (20, 20, 20)


def test_suggest_location_avoids_solid(tmp_path: Path) -> None:
    model = _model_with_box_surface(tmp_path)
    model.mesh.block.bounds_min = (0.0, 0.0, 0.0)
    model.mesh.block.bounds_max = (2.0, 0.6, 0.5)
    model.mesh.block.cells = (40, 12, 10)

    point = mesh_suggest.suggest_location_in_mesh(model, tmp_path)
    assert point is not None
    # inside domain
    assert all(lo < c < hi for c, lo, hi in
               zip(point, (0, 0, 0), (2, 0.6, 0.5), strict=True))
    # not inside the weir box
    inside_weir = (0.9 < point[0] < 1.1 and point[1] < 0.6 and point[2] < 0.3)
    assert not inside_weir
    assert mesh_suggest.location_diagnosis(model, tmp_path, point) is None


def test_location_diagnosis_flags_bad_points(tmp_path: Path) -> None:
    model = _model_with_box_surface(tmp_path)
    model.mesh.block.bounds_min = (0.0, 0.0, 0.0)
    model.mesh.block.bounds_max = (2.0, 0.6, 0.5)
    model.mesh.block.cells = (40, 12, 10)

    assert "outside the background-mesh box" in \
        mesh_suggest.location_diagnosis(model, tmp_path, (5.0, 0.3, 0.25))
    assert "inside the solid" in \
        mesh_suggest.location_diagnosis(model, tmp_path, (1.0, 0.3, 0.1))


def test_no_geometry_means_no_suggestions() -> None:
    model = CaseModel()
    assert mesh_suggest.suggest_bounds(model) is None
    assert mesh_suggest.geometry_bbox(model) is None
