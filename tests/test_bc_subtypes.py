"""SimFlow-style BC system: inlet/outlet sub-types, per-field overrides,
solver-aware catalog."""

from __future__ import annotations

from flowdesk.app import bc_catalog, projects
from flowdesk.foam import bc_matrix, generators
from flowdesk.model.boundaries import (
    FieldOverride,
    PressureOutlet,
    VelocityInlet,
    Wall,
)


def _u_entries(model, patch, bc):
    return bc_matrix.patch_entries(model, patch, bc, "U")


def _joined(entries):
    return " ".join(entries)


# ---------------------------------------------------------------- inlet sub-types


def test_volumetric_flow_rate_inlet(tmp_path) -> None:
    s = projects.create_project("v", tmp_path, "Pipe flow")
    bc = VelocityInlet(mode="volumetricFlowRate", volumetric_flow_rate=0.05)
    out = _joined(_u_entries(s.model, "inlet", bc))
    assert "flowRateInletVelocity" in out
    assert "volumetricFlowRate" in out and "0.05" in out


def test_mass_flow_rate_inlet_uses_density(tmp_path) -> None:
    s = projects.create_project("m", tmp_path, "Pipe flow")
    s.model.physics.fluid.rho = 998.0
    bc = VelocityInlet(mode="massFlowRate", mass_flow_rate=250.0)
    out = _joined(_u_entries(s.model, "inlet", bc))
    assert "flowRateInletVelocity" in out
    assert "massFlowRate" in out and "250" in out
    assert "rhoInlet" in out and "998" in out


def test_pressure_driven_inlet_sets_u_and_p(tmp_path) -> None:
    s = projects.create_project("p", tmp_path, "Pipe flow")
    bc = VelocityInlet(mode="pressure", inlet_pressure=5.0)
    assert "pressureInletOutletVelocity" in _joined(_u_entries(s.model, "inlet", bc))
    p = _joined(bc_matrix.patch_entries(s.model, "inlet", bc, "p"))
    assert "fixedValue" in p and "5" in p


def test_normal_inlet_still_works(tmp_path) -> None:
    s = projects.create_project("n", tmp_path, "Pipe flow")
    bc = VelocityInlet(mode="normal", speed=2.0)
    out = _joined(_u_entries(s.model, "inlet", bc))
    assert "fixedValue" in out and "2" in out


# ---------------------------------------------------------------- outlet sub-types


def test_total_pressure_outlet(tmp_path) -> None:
    s = projects.create_project("t", tmp_path, "Pipe flow")
    bc = PressureOutlet(outlet_type="totalPressure", total_pressure=3.0)
    p = _joined(bc_matrix.patch_entries(s.model, "outlet", bc, "p"))
    assert "totalPressure" in p and "p0" in p and "3" in p


def test_fixed_flux_outlet(tmp_path) -> None:
    s = projects.create_project("f", tmp_path, "Pipe flow")
    bc = PressureOutlet(outlet_type="fixedFlux")
    p = _joined(bc_matrix.patch_entries(s.model, "outlet", bc, "p"))
    assert "fixedFluxPressure" in p


def test_fixed_value_outlet_default(tmp_path) -> None:
    s = projects.create_project("d", tmp_path, "Pipe flow")
    bc = PressureOutlet(gauge_pressure=0.0)
    p = _joined(bc_matrix.patch_entries(s.model, "outlet", bc, "p"))
    assert "fixedValue" in p


def test_interfoam_fixed_flux_outlet_on_prgh(tmp_path) -> None:
    s = projects.create_project("if", tmp_path, "Dam break (3D breach)")
    bc = PressureOutlet(outlet_type="fixedFlux")
    p = _joined(bc_matrix.patch_entries(s.model, "outlet", bc, "p_rgh"))
    assert "fixedFluxPressure" in p


# ---------------------------------------------------------------- per-field override


def test_field_override_wins_over_generated(tmp_path) -> None:
    s = projects.create_project("o", tmp_path, "Pipe flow")
    bc = Wall()  # would generate noSlip for U
    bc.overrides["U"] = FieldOverride(
        patch_type="rotatingWallVelocity",
        extra={"origin": "(0 0 0)", "axis": "(0 0 1)", "omega": "10"},
        value="")
    out = _joined(_u_entries(s.model, "inlet", bc))
    assert "rotatingWallVelocity" in out and "omega" in out
    assert "noSlip" not in out


def test_override_round_trips_through_case_files(tmp_path) -> None:
    s = projects.create_project("ov", tmp_path, "Pipe flow")
    inlet = s.model.boundaries["inlet"]
    inlet.overrides["k"] = FieldOverride(patch_type="zeroGradient")
    from flowdesk.foam import writer

    writer.write_case(s.model.validated(), s.case_dir)
    k_file = (s.case_dir / "0" / "k").read_text()
    inlet_block = k_file.split("inlet")[1].split("}")[0]
    assert "zeroGradient" in inlet_block


def test_override_persists_in_sidecar(tmp_path) -> None:
    s = projects.create_project("ps", tmp_path, "Pipe flow")
    s.model.boundaries["inlet"].overrides["p"] = FieldOverride(
        patch_type="totalPressure", extra={"p0": "uniform 10"})
    s.save_model()
    reopened = projects.open_project(s.case_dir)
    ov = reopened.model.boundaries["inlet"].overrides
    assert "p" in ov and ov["p"].patch_type == "totalPressure"
    assert ov["p"].extra["p0"] == "uniform 10"


# ---------------------------------------------------------------- solver-aware catalog


def test_catalog_hides_atmosphere_for_single_phase(tmp_path) -> None:
    s = projects.create_project("sp", tmp_path, "Pipe flow")
    kinds = {k for k, _ in bc_catalog.available_kinds(s.model)}
    assert "atmosphere" not in kinds
    assert "velocityInlet" in kinds


def test_catalog_offers_atmosphere_for_interfoam(tmp_path) -> None:
    s = projects.create_project("if", tmp_path, "Dam break (3D breach)")
    kinds = {k for k, _ in bc_catalog.available_kinds(s.model)}
    assert "atmosphere" in kinds


def test_field_groups_single_phase_turbulent(tmp_path) -> None:
    s = projects.create_project("g", tmp_path, "Pipe flow")  # k-omega SST
    groups = dict(bc_catalog.field_groups(s.model))
    assert groups["Flow"] == ["U", "p"]
    assert "k" in groups["Turbulence"] and "omega" in groups["Turbulence"]
    assert "Phase" not in groups


def test_field_groups_interfoam(tmp_path) -> None:
    s = projects.create_project("if", tmp_path, "Dam break (3D breach)")  # laminar
    groups = dict(bc_catalog.field_groups(s.model))
    assert groups["Flow"] == ["U", "p_rgh"]
    assert groups["Phase"] == ["alpha.water"]
    assert "Turbulence" not in groups  # laminar


def test_override_types_per_field() -> None:
    u_types = {t for t, _ in bc_catalog.override_types_for_field("U")}
    assert "noSlip" in u_types and "flowRateInletVelocity" in u_types
    p_types = {t for t, _ in bc_catalog.override_types_for_field("p_rgh")}
    assert "fixedFluxPressure" in p_types
    alpha_types = {t for t, _ in bc_catalog.override_types_for_field("alpha.water")}
    assert "inletOutlet" in alpha_types
    assert bc_catalog.field_is_vector("U")
    assert not bc_catalog.field_is_vector("p")


def test_existing_templates_still_generate(tmp_path) -> None:
    """The two-layer change must not disturb templates with no overrides."""
    for tpl in ("Pipe flow", "External aero", "Dam break (3D breach)"):
        s = projects.create_project(tpl.replace(" ", "_"), tmp_path, tpl)
        s.model.validated()  # must be valid
        files = generators.generate_case(s.model)
        assert "0/U" in files
