"""Smoke + logic tests for the Physics / Boundaries / Numerics stage widgets."""

from __future__ import annotations

import pytest

from flowdesk.app import projects
from flowdesk.model.boundaries import PressureOutlet, VelocityInlet, Wall
from flowdesk.model.findings import Stage
from flowdesk.model.numerics import Preset
from flowdesk.model.physics import Turbulence
from flowdesk.ui.stages.boundaries import BoundariesStage, patch_color
from flowdesk.ui.stages.numerics import NumericsStage
from flowdesk.ui.stages.physics import PhysicsStage


@pytest.fixture
def aero_session(tmp_path):
    return projects.create_project("aero", tmp_path, "External aero")


def test_physics_apply_switch_turbulence_marks_bc_stale(qtbot, aero_session) -> None:
    stage = PhysicsStage(aero_session)
    qtbot.addWidget(stage)
    stage.turbulence_combo.setCurrentText("k-ε")
    stage.apply()
    assert aero_session.model.physics.turbulence is Turbulence.K_EPSILON
    assert aero_session.staleness.is_stale(Stage.BOUNDARIES)
    assert "wall functions regenerate" in aero_session.staleness.reason(Stage.BOUNDARIES)


def test_physics_derived_values_shown(qtbot, aero_session) -> None:
    stage = PhysicsStage(aero_session)
    qtbot.addWidget(stage)
    assert "k =" in stage.derived_label.text()
    assert "ω =" in stage.derived_label.text()


def test_physics_transient_fields_toggle(qtbot, aero_session) -> None:
    stage = PhysicsStage(aero_session)
    qtbot.addWidget(stage)
    assert not stage.transient_box.isVisibleTo(stage)
    stage._on_time_changed(1)
    assert stage.transient_box.isVisibleTo(stage)
    assert "pimpleFoam" in stage.solver_label.text()


def test_boundaries_assign_and_prune(qtbot, aero_session) -> None:
    stage = BoundariesStage(aero_session)
    qtbot.addWidget(stage)
    # select the 'top' patch row and assign a wall
    for i in range(stage.patch_list.count()):
        item = stage.patch_list.item(i)
        item.setSelected(item.data(0x0100) == "top")  # Qt.UserRole
    stage.type_combo.setCurrentText("Wall (no-slip)")
    stage.wall_moving.setChecked(False)
    stage.assign()
    assert isinstance(aero_session.model.boundaries["top"], Wall)


def test_boundaries_apply_writes_field_files(qtbot, aero_session) -> None:
    stage = BoundariesStage(aero_session)
    qtbot.addWidget(stage)
    assert stage.apply()
    assert (aero_session.case_dir / "0" / "U").exists()
    assert (aero_session.case_dir / "0" / "omega").exists()


def test_boundaries_form_reflects_existing_assignment(qtbot, aero_session) -> None:
    stage = BoundariesStage(aero_session)
    qtbot.addWidget(stage)
    for i in range(stage.patch_list.count()):
        item = stage.patch_list.item(i)
        item.setSelected(item.data(0x0100) == "inlet")
    stage._on_selection()
    assert stage.type_combo.currentText() == "Velocity inlet"
    assert stage.inlet_speed.value() == 10.0


def test_patch_color_mapping() -> None:
    assert patch_color(VelocityInlet()) == "#0072B2"
    assert patch_color(PressureOutlet()) == "#D55E00"
    assert patch_color(None) is None


def test_numerics_preset_switch_and_custom_flip(qtbot, aero_session) -> None:
    stage = NumericsStage(aero_session)
    qtbot.addWidget(stage)
    stage._on_preset(2)  # Accurate
    assert aero_session.model.numerics.preset is Preset.ACCURATE
    assert aero_session.model.numerics.residual_targets.u == 1e-6

    # touching an advanced field flips to Custom (§4.6)
    stage._fields["relax_u"]._edit.setText("0.6")
    stage._fields["relax_u"]._commit()
    assert aero_session.model.numerics.preset is Preset.CUSTOM
    assert "based on accurate" in stage.preset_caption.text()

    stage.apply()
    assert aero_session.model.numerics.relaxation.u == 0.6


def test_numerics_first_order_apply(qtbot, aero_session) -> None:
    stage = NumericsStage(aero_session)
    qtbot.addWidget(stage)
    stage.first_order_chk.setChecked(False)
    stage.apply()
    assert not aero_session.model.numerics.first_order_start.enabled
