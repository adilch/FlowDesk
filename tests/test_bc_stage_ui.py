"""BC stage UI: solver-aware character list, inlet/outlet sub-type controls,
and the per-field override editor."""

from __future__ import annotations

from PyQt6.QtCore import Qt

from flowdesk.app import projects
from flowdesk.model.boundaries import PressureOutlet, VelocityInlet
from flowdesk.ui.stages.boundaries import BoundariesStage


def _select(stage, name: str) -> None:
    for i in range(stage.patch_list.count()):
        item = stage.patch_list.item(i)
        item.setSelected(item.data(Qt.ItemDataRole.UserRole) == name)


def test_type_list_is_solver_aware(qtbot, tmp_path) -> None:
    single = projects.create_project("sp", tmp_path, "Pipe flow")
    stage = BoundariesStage(single)
    qtbot.addWidget(stage)
    labels = [stage.type_combo.itemText(i) for i in range(stage.type_combo.count())]
    assert "Atmosphere (open)" not in labels

    fs = projects.create_project("if", tmp_path, "Dam break (3D breach)")
    stage2 = BoundariesStage(fs)
    qtbot.addWidget(stage2)
    labels2 = [stage2.type_combo.itemText(i) for i in range(stage2.type_combo.count())]
    assert "Atmosphere (open)" in labels2


def test_assign_mass_flow_inlet(qtbot, tmp_path) -> None:
    s = projects.create_project("m", tmp_path, "Pipe flow")
    stage = BoundariesStage(s)
    qtbot.addWidget(stage)
    _select(stage, "inlet")
    stage.type_combo.setCurrentText("Velocity inlet")
    stage.inlet_spec.setCurrentIndex(stage.inlet_spec.findData("massFlowRate"))
    stage.inlet_mass.set_value(250.0)
    stage.assign()
    bc = s.model.boundaries["inlet"]
    assert isinstance(bc, VelocityInlet)
    assert bc.mode == "massFlowRate" and bc.mass_flow_rate == 250.0


def test_assign_total_pressure_outlet(qtbot, tmp_path) -> None:
    s = projects.create_project("o", tmp_path, "Pipe flow")
    stage = BoundariesStage(s)
    qtbot.addWidget(stage)
    _select(stage, "outlet")
    stage.type_combo.setCurrentText("Pressure outlet")
    stage.outlet_type_combo.setCurrentIndex(
        stage.outlet_type_combo.findData("totalPressure"))
    stage.outlet_total.set_value(5.0)
    stage.assign()
    bc = s.model.boundaries["outlet"]
    assert isinstance(bc, PressureOutlet)
    assert bc.outlet_type == "totalPressure" and bc.total_pressure == 5.0


def test_inlet_spec_rows_toggle(qtbot, tmp_path) -> None:
    s = projects.create_project("r", tmp_path, "Pipe flow")
    stage = BoundariesStage(s)
    qtbot.addWidget(stage)
    stage.inlet_spec.setCurrentIndex(stage.inlet_spec.findData("normal"))
    assert stage.inlet_speed.isVisible() or not stage.isVisible()
    stage.inlet_spec.setCurrentIndex(stage.inlet_spec.findData("volumetricFlowRate"))
    # the volumetric field is the active row, speed row hidden
    assert stage._inlet_rows["volumetricFlowRate"][1].isVisibleTo(stage)
    assert not stage._inlet_rows["normal"][1].isVisibleTo(stage)


def _override_combos(stage) -> list:
    """QComboBoxes currently laid out in the override editor (live, not pending-
    deleted)."""
    from PyQt6.QtWidgets import QComboBox

    found = []

    def walk(layout):
        for i in range(layout.count()):
            item = layout.itemAt(i)
            if item.widget():
                found.extend(item.widget().findChildren(QComboBox))
            elif item.layout():
                walk(item.layout())

    walk(stage._override_box)
    return found


def test_per_field_override_editor_shows_field_rows(qtbot, tmp_path) -> None:
    s = projects.create_project("ov", tmp_path, "Pipe flow")
    stage = BoundariesStage(s)
    qtbot.addWidget(stage)
    _select(stage, "inlet")  # has a VelocityInlet from the template

    assert _override_combos(stage), "override editor showed no field rows"

    # set an override on the model the way a row's commit does
    bc = s.model.boundaries["inlet"]
    from flowdesk.model.boundaries import FieldOverride

    bc.overrides["k"] = FieldOverride(patch_type="zeroGradient")
    stage._refresh_patch_labels()
    texts = [stage.patch_list.item(i).text() for i in range(stage.patch_list.count())]
    assert any("override" in t for t in texts)


def test_override_editor_hidden_for_multiselect(qtbot, tmp_path) -> None:
    s = projects.create_project("ms", tmp_path, "Pipe flow")
    stage = BoundariesStage(s)
    qtbot.addWidget(stage)
    for i in range(stage.patch_list.count()):
        stage.patch_list.item(i).setSelected(True)  # select all
    # no per-field rows when multiple patches selected
    assert not _override_combos(stage)
