"""Dictionary generation: PRD §4 'Generates' blocks, determinism, foamlib re-readability."""

from __future__ import annotations

from pathlib import Path

from foamlib import FoamFile

from flowdesk.foam import generators
from flowdesk.model.case import CaseModel
from flowdesk.model.geometry import Surface, SurfaceDiagnostics
from flowdesk.model.mesh import BoxRegion, LayerSpec, RefineRegion, SurfaceRefinement
from flowdesk.model.numerics import Preset, make_preset
from flowdesk.model.physics import Turbulence


def test_block_mesh_dict_matches_prd_example(box_model: CaseModel) -> None:
    """§4.3.1: bounds (-1 -1 0)..(3 1 1), cells (80 40 20)."""
    text = generators.block_mesh_dict(box_model)
    assert "hex (0 1 2 3 4 5 6 7) (80 40 20) simpleGrading (1 1 1)" in text
    assert "(-1 -1 0) (3 -1 0) (3 1 0) (-1 1 0)" in text
    assert "(-1 -1 1) (3 -1 1) (3 1 1) (-1 1 1)" in text
    assert "inlet { type patch; faces ((0 4 7 3)); }" in text
    assert "ground { type wall; faces ((0 3 2 1)); }" in text
    # two faces merged into one patch
    assert "sides { type patch; faces ((0 1 5 4) (3 7 6 2)); }" in text


def test_u_field_matches_prd_example(box_model: CaseModel) -> None:
    """§4.5 'Generates 0/U': inlet 2 m/s +x, backflow-safe outlet, noSlip walls."""
    text = generators.field_file(box_model, "U")
    assert "dimensions      [0 1 -1 0 0 0 0];" in text
    assert "internalField   uniform (2 0 0);" in text  # init_from_inlet default on
    assert "type            fixedValue;" in text
    assert "value           uniform (2 0 0);" in text
    assert "type            inletOutlet;" in text
    assert "type            noSlip;" in text
    assert "type            slip;" in text


def test_turbulence_fields_consistent(box_model: CaseModel) -> None:
    """§4.5 matrix: wall functions follow the turbulence model atomically."""
    k = generators.field_file(box_model, "k")
    omega = generators.field_file(box_model, "omega")
    nut = generators.field_file(box_model, "nut")
    assert "kqRWallFunction" in k
    assert "omegaWallFunction" in omega
    assert "nutkWallFunction" in nut

    box_model.physics.turbulence = Turbulence.K_EPSILON
    epsilon = generators.field_file(box_model, "epsilon")
    assert "epsilonWallFunction" in epsilon


def test_laminar_drops_turbulence_files(box_model: CaseModel) -> None:
    box_model.physics.turbulence = Turbulence.LAMINAR
    files = generators.generate_case(box_model)
    assert "0/k" not in files
    assert "0/omega" not in files
    assert "0/nut" not in files
    assert "simulationType  laminar;" in files["constant/turbulenceProperties"]


def test_fv_solution_robust_matches_prd(box_model: CaseModel) -> None:
    """§4.6 Robust preset: GAMG p solver, relaxation 0.3/0.5/0.5, residual targets."""
    text = generators.fv_solution(box_model)
    assert "solver          GAMG;" in text
    assert "tolerance       1e-07;" in text
    assert "relTol          0.01;" in text
    assert '"(U|k|omega)"' in text
    assert "p               0.3;" in text
    assert "residualControl" in text


def test_enclosed_domain_gets_pref(cavity_model: CaseModel) -> None:
    text = generators.fv_solution(cavity_model)
    assert "pRefCell        0;" in text
    assert "pRefValue       0;" in text


def test_control_dict_steady(box_model: CaseModel) -> None:
    """§4.7 example: simpleFoam, latestTime, purgeWrite 2, runTimeModifiable."""
    text = generators.control_dict(box_model)
    assert "application     simpleFoam;" in text
    assert "startFrom       latestTime;" in text
    assert "endTime         2000;" in text
    assert "writeInterval   200;" in text
    assert "purgeWrite      2;" in text
    assert "runTimeModifiable true;" in text


def test_control_dict_transient(box_model: CaseModel) -> None:
    from flowdesk.model.physics import TransientTime

    box_model.physics.time = TransientTime(end_time=5.0, output_interval=0.5)
    text = generators.control_dict(box_model)
    assert "application     pimpleFoam;" in text
    assert "adjustTimeStep  true;" in text
    assert "maxCo           1;" in text
    assert "writeControl    adjustableRunTime;" in text


def test_snappy_dict_matches_prd_example(box_model: CaseModel) -> None:
    """§4.3.2 abridged example: one surface 'weir' level (2 3), box region, layers."""
    box_model.geometry.blockmesh_only = False
    box_model.geometry.surfaces = [
        Surface(name="weir", stl_path="weir.stl",
                diagnostics=SurfaceDiagnostics(watertight=True))
    ]
    box_model.mesh.snappy.surfaces = [
        SurfaceRefinement(surface="weir", level_min=2, level_max=3, layers=LayerSpec())
    ]
    box_model.mesh.snappy.regions = [
        RefineRegion(name="refineBox",
                     geometry=BoxRegion(min=(0, -0.5, 0), max=(1.5, 0.5, 0.6)), level=2)
    ]
    box_model.mesh.snappy.location_in_mesh = (2.0, 0.0, 0.5)

    text = generators.snappy_hex_mesh_dict(box_model)
    assert "castellatedMesh true;" in text
    assert "addLayers       true;" in text
    assert "weir.stl { type triSurfaceMesh; name weir; }" in text
    assert "refineBox { type searchableBox; min (0 -0.5 0); max (1.5 0.5 0.6); }" in text
    assert 'features ( { file "weir.eMesh"; level 3; } );' in text
    assert "weir { level (2 3); }" in text
    assert "refineBox { mode inside; levels ((1E15 2)); }" in text
    assert "locationInMesh  (2 0 0.5);" in text
    assert "weir { nSurfaceLayers 3; }" in text
    assert "maxNonOrtho     65;" in text
    # v2506 keyword (PRD example shows the legacy 'minMedianAxisAngle' spelling)
    assert "minMedialAxisAngle 90;" in text


def test_numerics_presets_differ() -> None:
    robust = make_preset(Preset.ROBUST)
    accurate = make_preset(Preset.ACCURATE)
    assert robust.div_u == "bounded Gauss upwind"
    assert accurate.div_u == "bounded Gauss linearUpwind grad(U)"
    assert accurate.residual_targets.u == 1e-6
    assert accurate.simple_consistent


def test_generation_is_deterministic(box_model: CaseModel) -> None:
    """NFR §9: identical model => byte-identical generated dictionaries."""
    first = generators.generate_case(box_model)
    second = generators.generate_case(box_model.model_copy(deep=True))
    assert first == second


def test_every_generated_file_is_foamlib_readable(
    box_model: CaseModel, cavity_model: CaseModel, tmp_path: Path
) -> None:
    """§4.9 rule 5 at the source: FlowDesk never emits a file foamlib can't re-read."""
    for model in (box_model, cavity_model):
        for rel_path, text in generators.generate_case(model).items():
            target = tmp_path / model.meta.name / rel_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8", newline="\n")
            parsed = FoamFile(target).as_dict()
            assert parsed, f"{rel_path} parsed to empty dict"


def test_parallel_case_gets_decompose_dict(box_model: CaseModel) -> None:
    files = generators.generate_case(box_model)
    assert "numberOfSubdomains 4;" in files["system/decomposeParDict"]
    assert "method          scotch;" in files["system/decomposeParDict"]
