"""Execution engine: pipeline over QProcess, checkMesh parser."""

from __future__ import annotations

import sys
from pathlib import Path

from flowdesk.exec.parsers import CheckMeshParser, read_boundary_patches, verdict
from flowdesk.exec.pipeline import PipelineRunner, PipelineState, Step, file_exists_condition

CHECKMESH_SAMPLE = """\
Mesh stats
    points:           882
    internal points:  0
    faces:            1640
    internal faces:   760
    cells:            400
    faces per cell:   6
    boundary patches: 3
    point zones:      0

Checking geometry...
    Overall domain bounding box (0 0 0) (0.1 0.1 0.01)
    Mesh has 2 geometric (non-empty/wedge) directions (1 1 0)
    Boundary openness (1.45434e-19 9.66782e-19 -4.10876e-17) OK.
    Max cell openness = 2.16842e-16 OK.
    Max aspect ratio = 1.00071 OK.
    Minimum face area = 2.5e-05. Maximum face area = 2.5e-05.  Face area magnitudes OK.
    Min volume = 1.25e-07. Max volume = 1.25e-07.  Total volume = 5e-05.  Cell volumes OK.
    Mesh non-orthogonality Max: 2.86939 average: 0.24893
    Non-orthogonality check OK.
    Face pyramids OK.
    Max skewness = 0.333333 OK.
    Coupled point location match (average 0) OK.

Mesh OK.

End
"""


def test_checkmesh_parser_full_sample() -> None:
    parser = CheckMeshParser()
    for line in CHECKMESH_SAMPLE.splitlines():
        parser.feed(line)
    assert parser.cell_count == 400
    assert parser.report.max_non_ortho == 2.86939
    assert parser.report.max_skewness == 0.333333
    assert parser.report.max_aspect_ratio == 1.00071
    assert parser.report.negative_volume_cells == 0
    assert parser.report.mesh_ok


def test_checkmesh_parser_failure_line() -> None:
    parser = CheckMeshParser()
    parser.feed(" ***Zero or negative cell volume detected.  "
                "Number of negative volume cells: 3")
    parser.feed("Failed 1 mesh checks.")
    assert parser.report.negative_volume_cells == 3
    assert not parser.report.mesh_ok


def test_snappy_layer_parser() -> None:
    from flowdesk.exec.parsers import SnappyLayerParser

    # verbatim v2506 output (observed during M3 development)
    sample = """\
Handling cells with warped patch faces ...
Set displacement to zero on 0 warped faces

patch faces    layers avg thickness[m]
                     near-wall overall
----- -----    ------ --------- -------
weir 1864     2      0.00545   0.012
ground 1200     1.4      0.0011    0.003

Outer iteration : 0
"""
    parser = SnappyLayerParser()
    for line in sample.splitlines():
        parser.feed(line)
    assert len(parser.coverage) == 2
    weir = parser.coverage[0]
    assert (weir.surface, weir.n_faces) == ("weir", 1864)
    assert weir.layers_achieved == 2
    assert weir.thickness_overall == 0.012
    assert parser.coverage[1].layers_achieved == 1.4


def test_verdicts_match_prd_table() -> None:
    assert verdict("max_non_ortho", 50) == "pass"
    assert verdict("max_non_ortho", 70) == "warn"
    assert verdict("max_non_ortho", 80) == "fail"
    assert verdict("max_skewness", 5) == "warn"
    assert verdict("max_aspect_ratio", None) == "unknown"


def test_read_boundary_patches(tmp_path: Path) -> None:
    boundary = tmp_path / "constant" / "polyMesh" / "boundary"
    boundary.parent.mkdir(parents=True)
    boundary.write_text("""\
FoamFile { version 2.0; format ascii; class polyBoundaryMesh; object boundary; }
3
(
    movingWall
    {
        type            wall;
        inGroups        1(wall);
        nFaces          20;
        startFace       760;
    }
    fixedWalls
    {
        type            wall;
        nFaces          60;
        startFace       780;
    }
    frontAndBack
    {
        type            empty;
        nFaces          800;
        startFace       840;
    }
)
""")
    patches = read_boundary_patches(tmp_path)
    assert [(p.name, p.n_faces) for p in patches] == [
        ("movingWall", 20), ("fixedWalls", 60), ("frontAndBack", 800)]


# ------------------------------------------------------------------- pipeline


def _python_step(name: str, code: str, **kwargs) -> Step:
    return Step(name=name, argv=[sys.executable, "-c", code], **kwargs)


def test_pipeline_runs_steps_in_order(qtbot) -> None:
    runner = PipelineRunner()
    lines: list[str] = []
    runner.line.connect(lambda text, stream: lines.append(text))
    steps = [
        _python_step("one", "print('alpha')"),
        _python_step("two", "print('beta')"),
    ]
    with qtbot.waitSignal(runner.finished, timeout=30_000) as blocker:
        runner.run(steps)
    assert blocker.args == [True]
    assert runner.state is PipelineState.DONE
    alpha = lines.index("alpha")
    beta = lines.index("beta")
    assert alpha < beta


def test_pipeline_stops_on_failure(qtbot) -> None:
    runner = PipelineRunner()
    seen: list[str] = []
    runner.step_started.connect(lambda name, i, n: seen.append(name))
    steps = [
        _python_step("bad", "import sys; sys.exit(2)"),
        _python_step("never", "print('x')"),
    ]
    with qtbot.waitSignal(runner.finished, timeout=30_000) as blocker:
        runner.run(steps)
    assert blocker.args == [False]
    assert runner.state is PipelineState.FAILED
    assert seen == ["bad"]


def test_pipeline_post_condition_catches_silent_failure(qtbot, tmp_path) -> None:
    """§7.5: zero-exit-code-but-broken runs are still caught."""
    runner = PipelineRunner()
    steps = [_python_step(
        "liar", "print('ok')",
        post_condition=file_exists_condition(tmp_path / "missing", "output not created"),
    )]
    with qtbot.waitSignal(runner.finished, timeout=30_000) as blocker:
        runner.run(steps)
    assert blocker.args == [False]
    assert runner.state is PipelineState.FAILED


def test_pipeline_parser_receives_lines(qtbot) -> None:
    collected: list[str] = []
    runner = PipelineRunner()
    steps = [_python_step("emitter", "print('cells: 42')", on_line=collected.append)]
    with qtbot.waitSignal(runner.finished, timeout=30_000):
        runner.run(steps)
    assert "cells: 42" in collected
