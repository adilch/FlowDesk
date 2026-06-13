"""Mesh stage model (PRD §4.3): blockMesh background + snappyHexMesh refinement."""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from flowdesk.model.geometry import Vec3


class BlockFace(Enum):
    X_MIN = "xMin"
    X_MAX = "xMax"
    Y_MIN = "yMin"
    Y_MAX = "yMax"
    Z_MIN = "zMin"
    Z_MAX = "zMax"


class BlockPatch(BaseModel):
    """One named boundary patch covering one or more box faces (§4.3.1 patch table)."""

    name: str
    type: str = "patch"  # patch | wall | symmetry | empty (kept consistent with BC stage)
    faces: list[BlockFace]


def default_block_patches() -> list[BlockPatch]:
    return [BlockPatch(name=f.value, faces=[f]) for f in BlockFace]


class BlockMeshModel(BaseModel):
    bounds_min: Vec3 = (0.0, 0.0, 0.0)
    bounds_max: Vec3 = (1.0, 1.0, 1.0)
    cells: tuple[int, int, int] = (20, 20, 20)
    grading: Vec3 = (1.0, 1.0, 1.0)
    patches: list[BlockPatch] = Field(default_factory=default_block_patches)


class LayerSpec(BaseModel):
    """Boundary-layer columns of the per-surface table (§4.3.2)."""

    n_layers: int = 3
    expansion_ratio: float = 1.2
    final_layer_thickness: float = 0.3  # relative; relativeSizes fixed true for MVP
    min_thickness: float = 0.1


class SurfaceRefinement(BaseModel):
    """Per-surface snappy settings, one row per imported surface (§4.3.2)."""

    surface: str  # references Surface.name
    level_min: int = 2
    level_max: int = 3
    feature_level: int | None = None  # None -> defaults to level_max
    included_angle: float = 150.0
    layers: LayerSpec | None = None


class BoxRegion(BaseModel):
    shape: Literal["box"] = "box"
    min: Vec3
    max: Vec3


class SphereRegion(BaseModel):
    shape: Literal["sphere"] = "sphere"
    centre: Vec3
    radius: float


class CylinderRegion(BaseModel):
    shape: Literal["cylinder"] = "cylinder"
    point1: Vec3
    point2: Vec3
    radius: float


RegionShape = Annotated[BoxRegion | SphereRegion | CylinderRegion, Field(discriminator="shape")]


class RefineRegion(BaseModel):
    name: str
    geometry: RegionShape
    mode: Literal["inside", "outside"] = "inside"
    level: int = 2


class SnappyGlobals(BaseModel):
    """Global settings (§4.3.2). Values not exposed as controls are fixed in the generator."""

    castellated: bool = True
    snap: bool = True
    # When False, snappy still snaps the geometry into the background mesh but
    # adds NO refinement (surface levels forced to 0, refinement regions skipped)
    # - a fast, coarse, geometry-conforming mesh.
    refinement_enabled: bool = True
    max_global_cells: int = 20_000_000
    max_local_cells: int = 1_000_000
    cells_between_levels: int = 3
    resolve_feature_angle: float = 30.0
    n_smooth_patch: int = 3  # advanced
    snap_tolerance: float = 2.0  # advanced


class SnappyModel(BaseModel):
    surfaces: list[SurfaceRefinement] = Field(default_factory=list)
    regions: list[RefineRegion] = Field(default_factory=list)
    location_in_mesh: Vec3 | None = None
    globals: SnappyGlobals = Field(default_factory=SnappyGlobals)


class PatchInfo(BaseModel):
    name: str
    n_faces: int = 0


class LayerCoverage(BaseModel):
    """One row of snappy's layer summary table (§4.3.3: warn < 70% of requested).

    v2506 reports thickness in metres (near-wall / overall columns); coverage
    is judged as layers_achieved / layers_requested."""

    surface: str
    n_faces: int = 0
    layers_achieved: float = 0.0
    thickness_near_wall: float = 0.0  # m
    thickness_overall: float = 0.0  # m


class QualityReport(BaseModel):
    """Parsed checkMesh output (§4.3.3)."""

    max_non_ortho: float | None = None
    max_skewness: float | None = None
    max_aspect_ratio: float | None = None
    negative_volume_cells: int = 0
    mesh_ok: bool = False


class MeshResult(BaseModel):
    """Outcome of the last mesh pipeline run; None until meshed."""

    cell_count: int = 0
    patches: list[PatchInfo] = Field(default_factory=list)
    quality: QualityReport = Field(default_factory=QualityReport)
    layer_coverage: list[LayerCoverage] = Field(default_factory=list)


class MeshModel(BaseModel):
    block: BlockMeshModel = Field(default_factory=BlockMeshModel)
    snappy: SnappyModel = Field(default_factory=SnappyModel)
    result: MeshResult | None = None
