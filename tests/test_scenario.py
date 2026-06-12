"""Model-select decision tree (scenario.py) + the ModelSelector wizard widget."""

from __future__ import annotations

import pytest

from flowdesk.app import projects, scenario
from flowdesk.model.physics import SteadyTime, TransientTime, Turbulence

# ---------------------------------------------------------------- tree shape


def test_tree_navigates_to_interfoam() -> None:
    path = ["multiphase", "freeSurface", "immiscible", "twoFluids"]
    node = scenario.node_at(path)
    assert node.is_leaf
    assert node.resolution.free_surface
    assert node.resolution.force_transient
    assert scenario.breadcrumb_labels(path) == [
        "Multiphase", "Free Surface", "Immiscible", "2 Fluids"]


def test_single_phase_incompressible_is_supported_leaf() -> None:
    node = scenario.node_at(["singlePhase", "incompressible"])
    assert node.is_leaf and node.supported
    assert not node.resolution.free_surface


@pytest.mark.parametrize("path", [
    ["heatTransfer"], ["multicomponent"], ["singlePhase", "compressible"],
    ["multiphase", "dispersed"], ["multiphase", "phaseChange"],
    ["multiphase", "freeSurface", "miscible"],
    ["multiphase", "freeSurface", "immiscible", "multipleFluids"],
])
def test_unsupported_branches_flagged(path) -> None:
    node = scenario.node_at(path)
    assert not node.supported
    assert node.note  # carries the Phase-2 explanation


# ---------------------------------------------------------------- resolution


def test_apply_two_fluids_sets_interfoam(tmp_path) -> None:
    session = projects.create_project("a", tmp_path, "Lid-driven cavity")
    assert session.model.physics.solver == "simpleFoam"
    node = scenario.node_at(["multiphase", "freeSurface", "immiscible", "twoFluids"])
    scenario.apply_resolution(session.model, node.resolution)
    assert session.model.physics.free_surface is not None
    assert isinstance(session.model.physics.time, TransientTime)
    assert session.model.physics.solver == "interFoam"


def test_apply_single_phase_clears_free_surface(tmp_path) -> None:
    session = projects.create_project("b", tmp_path, "Dam break (3D breach)")
    assert session.model.physics.free_surface is not None
    node = scenario.node_at(["singlePhase", "incompressible"])
    scenario.apply_resolution(session.model, node.resolution)
    assert session.model.physics.free_surface is None


def test_apply_resolution_preserves_existing_free_surface_tuning(tmp_path) -> None:
    session = projects.create_project("c", tmp_path, "Dam break (3D breach)")
    original = session.model.physics.free_surface.water_column_max
    node = scenario.node_at(["multiphase", "freeSurface", "immiscible", "twoFluids"])
    scenario.apply_resolution(session.model, node.resolution)
    # re-applying must not clobber the user's water column
    assert session.model.physics.free_surface.water_column_max == original


@pytest.mark.parametrize("solver,free_surface,steady", [
    ("simpleFoam", False, True),
    ("pimpleFoam", False, False),
    ("interFoam", True, False),
])
def test_manual_solver_mapping(solver, free_surface, steady, tmp_path) -> None:
    session = projects.create_project("m", tmp_path, "Lid-driven cavity")
    scenario.apply_manual_solver(session.model, solver)
    assert (session.model.physics.free_surface is not None) == free_surface
    assert isinstance(session.model.physics.time, SteadyTime) == steady
    assert session.model.physics.solver == solver


def test_current_path_reflects_model(tmp_path) -> None:
    steady = projects.create_project("s", tmp_path, "Lid-driven cavity")
    assert scenario.current_path(steady.model) == ["singlePhase", "incompressible"]
    fs = projects.create_project("f", tmp_path, "Dam break (3D breach)")
    assert scenario.current_path(fs.model)[0] == "multiphase"


# ---------------------------------------------------------------- features


def test_feature_badges_interfoam(tmp_path) -> None:
    session = projects.create_project("i", tmp_path, "Dam break (3D breach)")
    feats = {f.label: f for f in scenario.feature_badges(session.model)}
    assert feats["Free Surface"].on and not feats["Free Surface"].interactive
    assert feats["Transient"].on and not feats["Transient"].interactive  # locked
    assert feats["VOF / MULES"].on
    assert feats["Turbulence"].interactive


def test_feature_badges_single_phase(tmp_path) -> None:
    session = projects.create_project("sp", tmp_path, "Lid-driven cavity")
    feats = {f.label: f for f in scenario.feature_badges(session.model)}
    assert "SIMPLE" in feats  # steady
    assert feats["Transient"].interactive and not feats["Transient"].on


def test_set_feature_transient_toggles_time(tmp_path) -> None:
    session = projects.create_project("t", tmp_path, "Lid-driven cavity")
    scenario.set_feature(session.model, "transient", True)
    assert isinstance(session.model.physics.time, TransientTime)
    assert session.model.physics.solver == "pimpleFoam"
    scenario.set_feature(session.model, "transient", False)
    assert isinstance(session.model.physics.time, SteadyTime)


def test_set_feature_turbulence_toggles_laminar(tmp_path) -> None:
    session = projects.create_project("tu", tmp_path, "Lid-driven cavity")
    scenario.set_feature(session.model, "turbulence", False)
    assert session.model.physics.turbulence is Turbulence.LAMINAR
    scenario.set_feature(session.model, "turbulence", True)
    assert session.model.physics.turbulence is not Turbulence.LAMINAR


def test_transient_feature_locked_for_free_surface(tmp_path) -> None:
    session = projects.create_project("l", tmp_path, "Dam break (3D breach)")
    scenario.set_feature(session.model, "transient", False)  # must be a no-op
    assert isinstance(session.model.physics.time, TransientTime)


# ---------------------------------------------------------------- widget


def test_wizard_resolves_interfoam_through_clicks(qtbot, tmp_path) -> None:
    from flowdesk.ui.stages.model_selector import ModelSelector

    session = projects.create_project("w", tmp_path, "Lid-driven cavity")
    sel = ModelSelector(session)
    qtbot.addWidget(sel)
    applied: list[bool] = []
    sel.applied.connect(lambda: applied.append(True))

    sel._enter_chooser()
    sel._choose(scenario.node_at(["multiphase"]))
    sel._choose(scenario.node_at(["multiphase", "freeSurface"]))
    sel._choose(scenario.node_at(["multiphase", "freeSurface", "immiscible"]))
    sel._choose(scenario.node_at(
        ["multiphase", "freeSurface", "immiscible", "twoFluids"]))

    assert applied  # emitted on leaf
    assert session.model.physics.solver == "interFoam"
    assert sel._mode == "summary"


def test_wizard_manual_path(qtbot, tmp_path) -> None:
    from flowdesk.ui.stages.model_selector import ModelSelector

    session = projects.create_project("wm", tmp_path, "Lid-driven cavity")
    sel = ModelSelector(session)
    qtbot.addWidget(sel)
    sel._enter_manual()
    sel._manual_combo.setCurrentText("interFoam")
    sel._apply_manual()
    assert session.model.physics.solver == "interFoam"


def test_physics_stage_hosts_wizard_and_syncs(qtbot, tmp_path) -> None:
    from flowdesk.ui.stages.physics import PhysicsStage

    session = projects.create_project("ps", tmp_path, "Lid-driven cavity")
    stage = PhysicsStage(session)
    qtbot.addWidget(stage)
    # drive the wizard to interFoam; the (hidden) backing controls must follow
    stage.model_selector._enter_manual()
    stage.model_selector._manual_combo.setCurrentText("interFoam")
    stage.model_selector._apply_manual()
    assert stage.free_surface_chk.isChecked()
    assert stage.fs_box.isVisibleTo(stage)
    assert "interFoam" in stage.solver_label.text()
