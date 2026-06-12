"""Runtime monitors: function-object generation + postProcessing readback."""

from __future__ import annotations

from pathlib import Path

from flowdesk.app import projects
from flowdesk.exec import monitors_io
from flowdesk.foam import generators
from flowdesk.model.monitors import (
    FieldValueMonitor,
    FlowRateMonitor,
    ForcesMonitor,
    ProbesMonitor,
)

# ----------------------------------------------------------- generation


def test_empty_functions_block_when_no_monitors(tmp_path) -> None:
    session = projects.create_project("a", tmp_path, "Lid-driven cavity")
    control = generators.control_dict(session.model)
    assert "functions\n{\n}" in control.replace("    ", "")


def test_forces_function_object(tmp_path) -> None:
    session = projects.create_project("f", tmp_path, "External aero")
    session.model.monitors = [ForcesMonitor(name="bodyForces", patches=["body"],
                                            u_inf=10.0, a_ref=2.0, l_ref=0.5)]
    control = generators.control_dict(session.model)
    assert "bodyForces" in control
    assert "type            forceCoeffs;" in control
    assert "patches         (body);" in control
    assert "magUInf         10;" in control
    assert "Aref            2;" in control


def test_flow_rate_function_object(tmp_path) -> None:
    session = projects.create_project("fr", tmp_path, "Pipe flow")
    session.model.monitors = [FlowRateMonitor(name="outletFlow", patch="outlet")]
    control = generators.control_dict(session.model)
    assert "outletFlow" in control
    assert "type            surfaceFieldValue;" in control
    assert "name            outlet;" in control
    assert "fields          (phi);" in control


def test_field_value_and_probes(tmp_path) -> None:
    session = projects.create_project("v", tmp_path, "Lid-driven cavity")
    session.model.monitors = [
        FieldValueMonitor(name="avgP", field="p", operation="volAverage"),
        ProbesMonitor(name="pts", fields=["U", "p"],
                      locations=[(0.05, 0.05, 0.005), (0.08, 0.02, 0.005)]),
    ]
    control = generators.control_dict(session.model)
    assert "type            volFieldValue;" in control
    assert "operation       volAverage;" in control
    assert "type            probes;" in control
    assert "(0.05 0.05 0.005)" in control
    assert "fields          (U p);" in control


def test_monitors_survive_save_load(tmp_path) -> None:
    session = projects.create_project("s", tmp_path, "Pipe flow")
    session.model.monitors = [FlowRateMonitor(name="q", patch="outlet")]
    session.save_model()
    reopened = projects.open_project(session.case_dir)
    assert len(reopened.model.monitors) == 1
    assert reopened.model.monitors[0].patch == "outlet"


# ----------------------------------------------------------- readback


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_read_flow_rate(tmp_path) -> None:
    _write(tmp_path / "postProcessing" / "q" / "0" / "surfaceFieldValue.dat",
           "# Region type : patch outlet\n"
           "# Time          sum(phi)\n"
           "0.005  0.0231\n0.010  0.0240\n0.015  0.0245\n")
    series = monitors_io.monitor_series(tmp_path, FlowRateMonitor(name="q", patch="outlet"))
    assert "flow rate (m³/s)" in series
    pts = series["flow rate (m³/s)"]
    assert pts[0] == (0.005, 0.0231)
    assert pts[-1] == (0.015, 0.0245)


def test_read_force_coefficients(tmp_path) -> None:
    _write(tmp_path / "postProcessing" / "fc" / "0" / "coefficient.dat",
           "# Force coefficients\n"
           "# Time Cd Cs Cl CmRoll CmPitch CmYaw\n"
           "1 0.45 0.0 0.12 0 0.01 0\n"
           "2 0.42 0.0 0.15 0 0.01 0\n")
    series = monitors_io.monitor_series(tmp_path, ForcesMonitor(name="fc"))
    assert series["Cd"] == [(1.0, 0.45), (2.0, 0.42)]
    assert series["Cl"] == [(1.0, 0.12), (2.0, 0.15)]


def test_read_probes_scalar_and_vector(tmp_path) -> None:
    locs = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)]
    _write(tmp_path / "postProcessing" / "pr" / "0" / "p",
           "# Probe 0 (0 0 0)\n# Probe 1 (1 0 0)\n#  Time  0  1\n"
           "0.1  2.0  3.0\n0.2  2.5  3.5\n")
    _write(tmp_path / "postProcessing" / "pr" / "0" / "U",
           "# Probe 0 (0 0 0)\n# Probe 1 (1 0 0)\n#  Time  0  1\n"
           "0.1  (3 4 0)  (1 0 0)\n")
    mon = ProbesMonitor(name="pr", fields=["p", "U"], locations=locs)
    series = monitors_io.monitor_series(tmp_path, mon)
    assert series["p@p0"] == [(0.1, 2.0), (0.2, 2.5)]
    assert series["p@p1"][-1] == (0.2, 3.5)
    assert series["U@p0"] == [(0.1, 5.0)]  # |(3,4,0)| = 5


def test_no_output_yet_is_empty(tmp_path) -> None:
    assert monitors_io.monitor_series(
        tmp_path, FlowRateMonitor(name="q", patch="outlet")) == {}
