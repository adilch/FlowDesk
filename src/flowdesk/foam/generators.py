"""Dictionary generation: CaseModel -> file texts for the full §4 surface.

Pure functions, headless, deterministic (identical model => byte-identical
output, NFR §9). generate_case() returns {relative path: text}; writing and
ownership are handled by flowdesk.foam.writer.
"""

from __future__ import annotations

from flowdesk.foam import bc_matrix
from flowdesk.foam.emitter import block, dimensioned, document, entry, fmt
from flowdesk.model.boundaries import VelocityInlet
from flowdesk.model.case import CaseModel
from flowdesk.model.mesh import BlockFace, BoxRegion, CylinderRegion, SphereRegion
from flowdesk.model.numerics import RunMode, auto_non_orth_correctors
from flowdesk.model.physics import Turbulence

# §4.3.1 vertex ordering: z-min plane then z-max plane, counter-clockwise from (x-,y-)
_FACE_VERTICES = {
    BlockFace.X_MIN: (0, 4, 7, 3),
    BlockFace.X_MAX: (1, 2, 6, 5),
    BlockFace.Y_MIN: (0, 1, 5, 4),
    BlockFace.Y_MAX: (3, 7, 6, 2),
    BlockFace.Z_MIN: (0, 3, 2, 1),
    BlockFace.Z_MAX: (4, 5, 6, 7),
}

FIELD_DIMENSIONS = {
    "U": (0, 1, -1, 0, 0, 0, 0),
    "p": (0, 2, -2, 0, 0, 0, 0),  # kinematic (p/rho)
    "p_rgh": (1, -1, -2, 0, 0, 0, 0),  # Pa - interFoam is a rho-based solver
    "alpha.water": (0, 0, 0, 0, 0, 0, 0),
    "k": (0, 2, -2, 0, 0, 0, 0),
    "omega": (0, 0, -1, 0, 0, 0, 0),
    "epsilon": (0, 2, -3, 0, 0, 0, 0),
    "nut": (0, 2, -1, 0, 0, 0, 0),
}


def generate_case(model: CaseModel) -> dict[str, str]:
    """All files FlowDesk manages, keyed by case-relative path (LF text)."""
    free_surface = model.physics.free_surface is not None
    files: dict[str, str] = {
        "system/controlDict": control_dict(model),
        "system/fvSchemes": fv_schemes(model),
        "system/fvSolution": fv_solution(model),
        "system/blockMeshDict": block_mesh_dict(model),
        "constant/transportProperties": transport_properties(model),
        "constant/turbulenceProperties": turbulence_properties(model),
    }
    if free_surface:
        files["constant/g"] = gravity_file(model)
        files["system/setFieldsDict"] = set_fields_dict(model)
    if model.geometry.surfaces:
        files["system/snappyHexMeshDict"] = snappy_hex_mesh_dict(model)
        files["system/surfaceFeatureExtractDict"] = surface_feature_extract_dict(model)
    if model.run.mode is RunMode.PARALLEL:
        files["system/decomposeParDict"] = decompose_par_dict(model)
    for field in bc_matrix.fields_for(model.physics.turbulence, free_surface):
        files[f"0/{field}"] = field_file(model, field)
    st = model.physics.scalar_transport
    if st is not None:
        files[f"0/{st.field}"] = scalar_field_file(model, st)
    return files


def scalar_field_file(model: CaseModel, st) -> str:
    """0/<scalar>: a dimensionless tracer, injected at velocity inlets."""
    from flowdesk.model.boundaries import (
        Atmosphere,
        Empty,
        Outflow,
        PressureOutlet,
        Symmetry,
        VelocityInlet,
    )

    def patch_entries(bc) -> list[str]:
        if isinstance(bc, Symmetry):
            return [entry("type", "symmetry")]
        if isinstance(bc, Empty):
            return [entry("type", "empty")]
        if isinstance(bc, VelocityInlet):
            return [entry("type", "fixedValue"),
                    entry("value", f"uniform {fmt(st.inlet_value)}")]
        if isinstance(bc, PressureOutlet | Outflow | Atmosphere):
            return [entry("type", "inletOutlet"),
                    entry("inletValue", "uniform 0"), entry("value", "uniform 0")]
        return [entry("type", "zeroGradient")]  # walls, slip

    lines = [f"{'dimensions'.ljust(15)} [0 0 0 0 0 0 0];", "",
             f"{'internalField'.ljust(15)} uniform 0;", ""]
    order = [p for p in model.expected_patches() if p in model.boundaries]
    patch_blocks: list[str] = []
    for i, patch in enumerate(order):
        patch_blocks += block(patch, patch_entries(model.boundaries[patch]))
        if i < len(order) - 1:
            patch_blocks.append("")
    lines += block("boundaryField", patch_blocks)
    return document(st.field, "\n".join(lines), cls="volScalarField")


# ----------------------------------------------------------------- system/


def block_mesh_dict(model: CaseModel) -> str:
    b = model.mesh.block
    (x0, y0, z0), (x1, y1, z1) = b.bounds_min, b.bounds_max
    vertices = [
        (x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
        (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1),
    ]
    lines = [entry("scale", 1), ""]
    lines += ["vertices", "("]
    for i in range(0, 8, 4):
        lines.append("    " + " ".join(fmt(v) for v in vertices[i : i + 4]))
    lines += [");", ""]
    lines += [
        "blocks",
        "(",
        f"    hex (0 1 2 3 4 5 6 7) {fmt(b.cells)} simpleGrading {fmt(b.grading)}",
        ");",
        "",
    ]
    lines += ["boundary", "("]
    for p in b.patches:
        patch_type = _block_patch_type(model, p.name, p.type)
        faces = " ".join(fmt(_FACE_VERTICES[f]) for f in p.faces)
        lines.append(f"    {p.name} {{ type {patch_type}; faces ({faces}); }}")
    lines += [");"]
    return document("blockMeshDict", "\n".join(lines))


def _block_patch_type(model: CaseModel, patch: str, declared: str) -> str:
    """Boundary type follows the assigned physical BC when one exists (§4.5 consistency)."""
    bc = model.boundaries.get(patch)
    if bc is not None:
        from flowdesk.model.boundaries import BLOCK_PATCH_TYPE

        return BLOCK_PATCH_TYPE[bc.kind]
    return declared


def snappy_hex_mesh_dict(model: CaseModel) -> str:
    s = model.mesh.snappy
    g = s.globals
    any_layers = any(r.layers is not None for r in s.surfaces)

    lines = [
        entry("castellatedMesh", g.castellated),
        entry("snap", g.snap),
        entry("addLayers", any_layers),
        "",
    ]

    geo: list[str] = []
    for surf in model.geometry.surfaces:
        geo.append(f"{surf.name}.stl {{ type triSurfaceMesh; name {surf.name}; }}")
    if g.refinement_enabled:  # refinement-region geometry is unused when off
        for region in s.regions:
            geo.append(_region_geometry(region))
    lines += block("geometry", geo) + [""]

    cast: list[str] = [
        entry("maxLocalCells", g.max_local_cells),
        entry("maxGlobalCells", g.max_global_cells),
        entry("minRefinementCells", 10),
        entry("nCellsBetweenLevels", g.cells_between_levels),
        "",
    ]
    # When refinement is disabled, snappy still snaps the geometry into the
    # background mesh but adds no refinement: feature/surface levels forced to 0
    # and refinement regions skipped.
    refine = g.refinement_enabled

    def _feat_level(r) -> int:
        if not refine:
            return 0
        return r.feature_level if r.feature_level is not None else r.level_max

    features = " ".join(
        f'{{ file "{r.surface}.eMesh"; level {_feat_level(r)}; }}'
        for r in s.surfaces
    )
    cast.append(f"features ( {features} );")
    cast.append("")
    refinement = [
        f"{r.surface} {{ level ({r.level_min} {r.level_max}); }}" if refine
        else f"{r.surface} {{ level (0 0); }}"
        for r in s.surfaces
    ]
    cast += block("refinementSurfaces", refinement)
    cast.append("")
    regions = [
        f"{r.name} {{ mode {r.mode}; levels ((1E15 {r.level})); }}" for r in s.regions
    ] if refine else []
    cast += block("refinementRegions", regions)
    cast.append("")
    location = s.location_in_mesh if s.location_in_mesh is not None else (0.0, 0.0, 0.0)
    cast.append(entry("locationInMesh", location))
    cast.append(entry("resolveFeatureAngle", g.resolve_feature_angle))
    cast.append(entry("allowFreeStandingZoneFaces", True))
    lines += block("castellatedMeshControls", cast) + [""]

    lines += block("snapControls", [
        entry("nSmoothPatch", g.n_smooth_patch),
        entry("tolerance", g.snap_tolerance),
        entry("nSolveIter", 30),
        entry("nRelaxIter", 5),
        entry("nFeatureSnapIter", 10),
        entry("implicitFeatureSnap", False),
        entry("explicitFeatureSnap", True),
    ]) + [""]

    layer_surfaces = [r for r in s.surfaces if r.layers is not None]
    first = layer_surfaces[0].layers if layer_surfaces else None
    layer_lines = [entry("relativeSizes", True)]
    layer_lines += block(
        "layers",
        [f"{r.surface} {{ nSurfaceLayers {r.layers.n_layers}; }}" for r in layer_surfaces],
    )
    layer_lines += [
        entry("expansionRatio", first.expansion_ratio if first else 1.2),
        entry("finalLayerThickness", first.final_layer_thickness if first else 0.3),
        entry("minThickness", first.min_thickness if first else 0.1),
        entry("nGrow", 0),
        entry("featureAngle", 130),
        entry("nRelaxIter", 5),
        entry("nSmoothSurfaceNormals", 1),
        entry("nSmoothNormals", 3),
        entry("nSmoothThickness", 10),
        entry("maxFaceThicknessRatio", 0.5),
        entry("maxThicknessToMedialRatio", 0.3),
        # PRD §4.3.2 example shows the legacy spelling 'minMedianAxisAngle';
        # OpenFOAM v2506 requires 'minMedialAxisAngle' (verified against the solver).
        entry("minMedialAxisAngle", 90),
        entry("nBufferCellsNoExtrude", 0),
        entry("nLayerIter", 50),
    ]
    lines += block("addLayersControls", layer_lines) + [""]

    lines += block("meshQualityControls", [
        entry("maxNonOrtho", 65),
        entry("maxBoundarySkewness", 20),
        entry("maxInternalSkewness", 4),
        entry("maxConcave", 80),
        entry("minVol", 1e-13),
        entry("minTetQuality", 1e-15),
        entry("minArea", -1),
        entry("minTwist", 0.02),
        entry("minDeterminant", 0.001),
        entry("minFaceWeight", 0.05),
        entry("minVolRatio", 0.01),
        entry("minTriangleTwist", -1),
        entry("nSmoothScale", 4),
        entry("errorReduction", 0.75),
    ]) + [""]

    lines.append(entry("writeFlags", "(scalarLevels layerSets layerFields)"))
    lines.append(entry("mergeTolerance", 1e-6))
    return document("snappyHexMeshDict", "\n".join(lines))


def _region_geometry(region) -> str:
    g = region.geometry
    if isinstance(g, BoxRegion):
        return f"{region.name} {{ type searchableBox; min {fmt(g.min)}; max {fmt(g.max)}; }}"
    if isinstance(g, SphereRegion):
        return (
            f"{region.name} {{ type searchableSphere; centre {fmt(g.centre)}; "
            f"radius {fmt(g.radius)}; }}"
        )
    if isinstance(g, CylinderRegion):
        return (
            f"{region.name} {{ type searchableCylinder; point1 {fmt(g.point1)}; "
            f"point2 {fmt(g.point2)}; radius {fmt(g.radius)}; }}"
        )
    raise ValueError(f"unknown region shape: {g}")


def surface_feature_extract_dict(model: CaseModel) -> str:
    lines: list[str] = []
    angle_by_surface = {r.surface: r.included_angle for r in model.mesh.snappy.surfaces}
    for surf in model.geometry.surfaces:
        angle = angle_by_surface.get(surf.name, 150.0)
        lines += block(f"{surf.name}.stl", [
            entry("extractionMethod", "extractFromSurface"),
            entry("includedAngle", angle),
        ])
        lines.append("")
    return document("surfaceFeatureExtractDict", "\n".join(lines))


def gravity_file(model: CaseModel) -> str:
    fs = model.physics.free_surface
    body = "\n".join([
        entry("dimensions", "[0 1 -2 0 0 0 0]"),
        entry("value", fmt(fs.gravity)),
    ])
    return document("g", body, cls="uniformDimensionedVectorField")


def set_fields_dict(model: CaseModel) -> str:
    """Initial water column: alpha.water = 1 inside the box, 0 elsewhere.
    Run by the execution engine before the first solve (and after a reset)."""
    fs = model.physics.free_surface
    lines = [
        "defaultFieldValues",
        "(",
        "    volScalarFieldValue alpha.water 0",
        ");",
        "",
        "regions",
        "(",
        "    boxToCell",
        "    {",
        f"        box {fmt(fs.water_column_min)} {fmt(fs.water_column_max)};",
        "        fieldValues",
        "        (",
        "            volScalarFieldValue alpha.water 1",
        "        );",
        "    }",
        ");",
    ]
    return document("setFieldsDict", "\n".join(lines))


def control_dict(model: CaseModel) -> str:
    p = model.physics
    if p.is_steady:
        # Clamp: a write interval beyond endTime would end the run with zero
        # results written (found the hard way - M5 results tests)
        write_interval = min(model.run.write_interval_steady,
                             model.run.max_iterations)
        lines = [
            entry("application", p.solver),
            "",
            entry("startFrom", "latestTime"),
            entry("startTime", 0),
            entry("stopAt", "endTime"),
            entry("endTime", model.run.max_iterations),
            entry("deltaT", 1),
            "",
            entry("writeControl", "timeStep"),
            entry("writeInterval", write_interval),
            entry("purgeWrite", model.run.purge_write),
        ]
    else:
        t = p.time
        # Safety net: adjustableRunTime writes at multiples of the interval and
        # NOT automatically at endTime, so an interval past endTime saves nothing
        # (reconstructPar then reports 'No times selected'). Clamp so the final
        # frame is always written; validation also flags interval > endTime.
        write_interval = min(t.output_interval, t.end_time)
        lines = [
            entry("application", p.solver),
            "",
            entry("startFrom", "latestTime"),
            entry("startTime", 0),
            entry("stopAt", "endTime"),
            entry("endTime", t.end_time),
            entry("deltaT", t.initial_dt),
            entry("adjustTimeStep", True),
            entry("maxCo", t.max_courant),
        ]
        if p.free_surface is not None:
            # interface Courant limit: the interface must not cross a cell/step
            lines.append(entry("maxAlphaCo", min(t.max_courant, 1.0)))
            lines.append(entry("maxDeltaT", 1))
        lines += [
            "",
            entry("writeControl", "adjustableRunTime"),
            entry("writeInterval", write_interval),
            entry("purgeWrite", model.run.purge_write_transient),
        ]
    lines += [
        entry("writeFormat", model.run.write_format),
        entry("writePrecision", model.run.write_precision),
        entry("timeFormat", "general"),
        entry("runTimeModifiable", True),
        "",
        # Function objects: runtime monitors (forces, flow rate, field values, probes)
        "functions",
        "{",
        *("    " + ln for ln in function_objects(model)),
        "}",
    ]
    return document("controlDict", "\n".join(lines))


def function_objects(model: CaseModel) -> list[str]:
    """Inner lines of controlDict's `functions {}` block, one dict per monitor."""
    from flowdesk.model.monitors import (
        FieldValueMonitor,
        FlowRateMonitor,
        ForcesMonitor,
        ProbesMonitor,
    )

    lines: list[str] = []
    st = model.physics.scalar_transport
    if st is not None:
        lines += _scalar_transport_fo(st)
        lines.append("")
    for mon in model.monitors:
        if isinstance(mon, ForcesMonitor):
            lines += _forces_fo(mon)
        elif isinstance(mon, FlowRateMonitor):
            lines += _flow_rate_fo(mon)
        elif isinstance(mon, FieldValueMonitor):
            lines += _field_value_fo(mon)
        elif isinstance(mon, ProbesMonitor):
            lines += _probes_fo(mon)
        lines.append("")
    return lines


def _scalar_transport_fo(st) -> list[str]:
    return [
        "scalarTransport",
        "{",
        "    type            scalarTransport;",
        '    libs            ("libsolverFunctionObjects.so");',
        f"    field           {st.field};",
        f"    D               {fmt(st.diffusivity)};",
        "    nCorr           1;",
        "    resetOnStartUp  false;",
        "}",
    ]


def _forces_fo(mon) -> list[str]:
    patches = " ".join(mon.patches)
    return [
        f"{mon.name}",
        "{",
        "    type            forceCoeffs;",
        '    libs            ("libforces.so");',
        f"    patches         ({patches});",
        "    rho             rhoInf;",
        f"    rhoInf          {fmt(mon.rho_inf)};",
        f"    CofR            {fmt(mon.centre_of_rotation)};",
        f"    liftDir         {fmt(mon.lift_dir)};",
        f"    dragDir         {fmt(mon.drag_dir)};",
        f"    pitchAxis       {fmt(mon.pitch_axis)};",
        f"    magUInf         {fmt(mon.u_inf)};",
        f"    lRef            {fmt(mon.l_ref)};",
        f"    Aref            {fmt(mon.a_ref)};",
        "    writeControl    timeStep;",
        "    writeInterval   1;",
        "}",
    ]


def _flow_rate_fo(mon) -> list[str]:
    return [
        f"{mon.name}",
        "{",
        "    type            surfaceFieldValue;",
        '    libs            ("libfieldFunctionObjects.so");',
        "    regionType      patch;",
        f"    name            {mon.patch};",
        "    operation       sum;",
        "    fields          (phi);",
        "    writeFields     false;",
        "    log             true;",
        "    writeControl    timeStep;",
        "    writeInterval   1;",
        "}",
    ]


def _field_value_fo(mon) -> list[str]:
    return [
        f"{mon.name}",
        "{",
        "    type            volFieldValue;",
        '    libs            ("libfieldFunctionObjects.so");',
        "    regionType      all;",
        f"    operation       {mon.operation};",
        f"    fields          ({mon.field});",
        "    writeFields     false;",
        "    log             true;",
        "    writeControl    timeStep;",
        "    writeInterval   1;",
        "}",
    ]


def _probes_fo(mon) -> list[str]:
    fields = " ".join(mon.fields)
    lines = [
        f"{mon.name}",
        "{",
        "    type            probes;",
        '    libs            ("libsampling.so");',
        f"    fields          ({fields});",
        "    probeLocations",
        "    (",
    ]
    lines += [f"        {fmt(loc)}" for loc in mon.locations]
    lines += [
        "    );",
        "    writeControl    timeStep;",
        "    writeInterval   1;",
        "}",
    ]
    return lines


def fv_schemes(model: CaseModel) -> str:
    if model.physics.free_surface is not None:
        return _fv_schemes_interfoam(model)
    n = model.numerics
    p = model.physics
    ddt = "steadyState" if p.is_steady else n.transient.ddt_scheme
    turb_fields = {"k", "omega"} if p.turbulence is Turbulence.K_OMEGA_SST else {"k", "epsilon"}

    lines = block("ddtSchemes", [entry("default", ddt)]) + [""]
    lines += block("gradSchemes", [entry("default", n.grad_scheme)]) + [""]
    div = [entry("default", "none"), entry("div(phi,U)", n.div_u)]
    if p.turbulence is not Turbulence.LAMINAR:
        for f in sorted(turb_fields):
            div.append(entry(f"div(phi,{f})", n.div_turb))
    if p.scalar_transport is not None:
        div.append(entry(f"div(phi,{p.scalar_transport.field})",
                         "Gauss limitedLinear 1"))
    div.append(entry("div((nuEff*dev2(T(grad(U)))))", "Gauss linear"))
    lines += block("divSchemes", div) + [""]
    lines += block("laplacianSchemes", [entry("default", n.laplacian_scheme)]) + [""]
    lines += block("interpolationSchemes", [entry("default", "linear")]) + [""]
    lines += block("snGradSchemes", [entry("default", n.sn_grad_scheme)]) + [""]
    lines += block("wallDist", [entry("method", "meshWave")])
    return document("fvSchemes", "\n".join(lines))


def _fv_schemes_interfoam(model: CaseModel) -> str:
    """interFoam scheme set (v2506 damBreak conventions): MULES interface
    capture needs the vanLeer/interfaceCompression pair; momentum uses
    linearUpwind. Customization beyond this is file-editor territory."""
    p = model.physics
    div = [
        entry("div(rhoPhi,U)", "Gauss linearUpwind grad(U)"),
        entry("div(phi,alpha)", "Gauss vanLeer"),
        entry("div(phirb,alpha)", "Gauss linear"),
    ]
    if p.turbulence is not Turbulence.LAMINAR:
        turb_fields = {"k", "omega"} if p.turbulence is Turbulence.K_OMEGA_SST \
            else {"k", "epsilon"}
        for f in sorted(turb_fields):
            div.append(entry(f"div(phi,{f})", "Gauss upwind"))
    div.append(entry("div(((rho*nuEff)*dev2(T(grad(U)))))", "Gauss linear"))

    lines = block("ddtSchemes", [entry("default", "Euler")]) + [""]
    lines += block("gradSchemes", [entry("default", "Gauss linear")]) + [""]
    lines += block("divSchemes", [entry("default", "none")] + div) + [""]
    lines += block("laplacianSchemes", [entry("default", "Gauss linear corrected")]) + [""]
    lines += block("interpolationSchemes", [entry("default", "linear")]) + [""]
    lines += block("snGradSchemes", [entry("default", "corrected")]) + [""]
    lines += block("wallDist", [entry("method", "meshWave")])
    return document("fvSchemes", "\n".join(lines))


def fv_solution(model: CaseModel) -> str:
    if model.physics.free_surface is not None:
        return _fv_solution_interfoam(model)
    n = model.numerics
    p = model.physics
    turb_group = "(k|omega)" if p.turbulence is Turbulence.K_OMEGA_SST else "(k|epsilon)"
    smooth_group = f'"(U|{turb_group[1:-1]})"' if p.turbulence is not Turbulence.LAMINAR else '"U"'

    solvers: list[str] = []
    solvers += block("p", [
        entry("solver", "GAMG"),
        entry("smoother", "GaussSeidel"),
        entry("tolerance", n.p_solver.tolerance),
        entry("relTol", n.p_solver.rel_tol),
    ])
    solvers.append("")
    solvers += block(smooth_group, [
        entry("solver", "smoothSolver"),
        entry("smoother", "symGaussSeidel"),
        entry("tolerance", n.u_solver.tolerance),
        entry("relTol", n.u_solver.rel_tol),
    ])
    if not p.is_steady:
        solvers.append("")
        solvers += block("pFinal", [entry("$p", ""), entry("relTol", 0)])
        solvers.append("")
        final_group = smooth_group[:-1] + 'Final"'
        solvers += block(final_group, [
            entry("solver", "smoothSolver"),
            entry("smoother", "symGaussSeidel"),
            entry("tolerance", n.u_solver.tolerance),
            entry("relTol", 0),
        ])

    if p.scalar_transport is not None:
        solvers.append("")
        # asymmetric convection-diffusion matrix: PBiCGStab/DILU, not a
        # symmetric smoother (which FPEs on the scalar's diagonal)
        solvers += block(f'"{p.scalar_transport.field}.*"', [
            entry("solver", "PBiCGStab"),
            entry("preconditioner", "DILU"),
            entry("tolerance", 1e-8),
            entry("relTol", 0.1 if p.is_steady else 0),
        ])

    lines = block("solvers", solvers) + [""]

    n_correctors = (
        n.n_non_orthogonal_correctors
        if n.n_non_orthogonal_correctors is not None
        else auto_non_orth_correctors(
            model.mesh.result.quality.max_non_ortho if model.mesh.result else None
        )
    )
    if p.is_steady:
        simple = [
            entry("nNonOrthogonalCorrectors", n_correctors),
            entry("consistent", "yes" if n.simple_consistent else "no"),
        ]
        if model.enclosed_domain:
            simple += [entry("pRefCell", 0), entry("pRefValue", 0)]
        residual = [
            entry("p", n.residual_targets.p),
            entry("U", n.residual_targets.u),
        ]
        if p.turbulence is not Turbulence.LAMINAR:
            residual.append(entry(f'"{turb_group}"', n.residual_targets.turb))
        simple += [""] + block("residualControl", residual)
        lines += block("SIMPLE", simple) + [""]
    else:
        pimple = [
            entry("nOuterCorrectors", n.transient.n_outer_correctors),
            entry("nCorrectors", n.transient.n_correctors),
            entry("nNonOrthogonalCorrectors", n_correctors),
            entry("momentumPredictor", "yes" if n.transient.momentum_predictor else "no"),
        ]
        if model.enclosed_domain:
            pimple += [entry("pRefCell", 0), entry("pRefValue", 0)]
        lines += block("PIMPLE", pimple) + [""]

    relax_fields = [entry("p", n.relaxation.p)]
    relax_eqns = [entry("U", n.relaxation.u)]
    if p.turbulence is not Turbulence.LAMINAR:
        relax_eqns.append(entry(f'"{turb_group}"', n.relaxation.turb))
    lines += block("relaxationFactors",
                   block("fields", relax_fields) + block("equations", relax_eqns))
    return document("fvSolution", "\n".join(lines))


def _fv_solution_interfoam(model: CaseModel) -> str:
    """interFoam solution set: MULES for alpha, PCG for p_rgh, PISO-mode PIMPLE
    (no relaxation - transient)."""
    n = model.numerics
    p = model.physics
    solvers: list[str] = []
    solvers += block('"alpha.water.*"', [
        entry("nAlphaCorr", 2),
        entry("nAlphaSubCycles", 1),
        entry("cAlpha", 1),
        entry("MULESCorr", "yes"),
        entry("nLimiterIter", 3),
        entry("solver", "smoothSolver"),
        entry("smoother", "symGaussSeidel"),
        entry("tolerance", 1e-8),
        entry("relTol", 0),
    ]) + [""]
    solvers += block('"pcorr.*"', [
        entry("solver", "PCG"),
        entry("preconditioner", "DIC"),
        entry("tolerance", 1e-5),
        entry("relTol", 0),
    ]) + [""]
    solvers += block("p_rgh", [
        entry("solver", "PCG"),
        entry("preconditioner", "DIC"),
        entry("tolerance", 1e-7),
        entry("relTol", 0.05),
    ]) + [""]
    solvers += block("p_rghFinal", [entry("$p_rgh", ""), entry("relTol", 0)]) + [""]
    velocity_group = '"(U|k|omega|epsilon)"'
    solvers += block(velocity_group, [
        entry("solver", "smoothSolver"),
        entry("smoother", "symGaussSeidel"),
        entry("tolerance", 1e-6),
        entry("relTol", 0),
    ]) + [""]
    solvers += block('"(U|k|omega|epsilon)Final"', [
        entry("solver", "smoothSolver"),
        entry("smoother", "symGaussSeidel"),
        entry("tolerance", 1e-6),
        entry("relTol", 0),
    ])

    n_correctors = (
        n.n_non_orthogonal_correctors
        if n.n_non_orthogonal_correctors is not None
        else auto_non_orth_correctors(
            model.mesh.result.quality.max_non_ortho if model.mesh.result else None
        )
    )
    pimple = [
        entry("momentumPredictor", "no"),
        entry("nOuterCorrectors", 1),
        entry("nCorrectors", 3),
        entry("nNonOrthogonalCorrectors", n_correctors),
    ]
    _ = p  # turbulence handled via the velocity group regex above
    lines = block("solvers", solvers) + [""] + block("PIMPLE", pimple)
    return document("fvSolution", "\n".join(lines))


def decompose_par_dict(model: CaseModel) -> str:
    lines = [
        entry("numberOfSubdomains", model.run.cores),
        "",
        entry("method", model.run.decomposition),
    ]
    if model.run.decomposition == "hierarchical":
        lines += [""] + block("coeffs", [
            entry("n", model.run.hierarchical_n),
            entry("order", "xyz"),
        ])
    return document("decomposeParDict", "\n".join(lines))


# ---------------------------------------------------------------- constant/


def transport_properties(model: CaseModel) -> str:
    fs = model.physics.free_surface
    if fs is None:
        lines = [
            entry("transportModel", "Newtonian"),
            "",
            dimensioned("nu", (0, 2, -1, 0, 0, 0, 0), model.physics.fluid.nu),
        ]
        return document("transportProperties", "\n".join(lines))

    # Two-phase (interFoam): the Physics fluid is the heavy phase 'water'
    heavy, light = model.physics.fluid, fs.light_phase
    lines = [entry("phases", "(water air)"), ""]
    lines += block("water", [
        entry("transportModel", "Newtonian"),
        dimensioned("nu", (0, 2, -1, 0, 0, 0, 0), heavy.nu),
        dimensioned("rho", (1, -3, 0, 0, 0, 0, 0), heavy.rho),
    ]) + [""]
    lines += block("air", [
        entry("transportModel", "Newtonian"),
        dimensioned("nu", (0, 2, -1, 0, 0, 0, 0), light.nu),
        dimensioned("rho", (1, -3, 0, 0, 0, 0, 0), light.rho),
    ]) + [""]
    lines.append(dimensioned("sigma", (1, 0, -2, 0, 0, 0, 0), fs.sigma))
    return document("transportProperties", "\n".join(lines))


def turbulence_properties(model: CaseModel) -> str:
    t = model.physics.turbulence
    if t is Turbulence.LAMINAR:
        body = entry("simulationType", "laminar")
    else:
        body = "\n".join(
            [entry("simulationType", "RAS"), ""]
            + block("RAS", [
                entry("RASModel", t.value),
                entry("turbulence", "on"),
                entry("printCoeffs", "on"),
            ])
        )
    return document("turbulenceProperties", body)


# --------------------------------------------------------------------- 0/


def field_file(model: CaseModel, field: str) -> str:
    cls = "volVectorField" if field == "U" else "volScalarField"
    dims = " ".join(str(d) for d in FIELD_DIMENSIONS[field])
    lines = [f"{'dimensions'.ljust(15)} [{dims}];", ""]
    lines.append(f"{'internalField'.ljust(15)} uniform {fmt(_internal_value(model, field))};")
    lines.append("")

    patch_blocks: list[str] = []
    boundary_order = [p for p in model.expected_patches() if p in model.boundaries]
    for i, patch in enumerate(boundary_order):
        bc = model.boundaries[patch]
        patch_blocks += block(patch, bc_matrix.patch_entries(model, patch, bc, field))
        if i < len(boundary_order) - 1:
            patch_blocks.append("")
    lines += block("boundaryField", patch_blocks)
    return document(field, "\n".join(lines), cls=cls)


def _internal_value(model: CaseModel, field: str):
    if field == "U":
        if model.init_from_inlet:
            for patch, bc in model.boundaries.items():
                if isinstance(bc, VelocityInlet):
                    return bc_matrix.resolve_inlet_vector(model, patch, bc)
        return (0, 0, 0)
    if field in ("p", "p_rgh", "nut", "alpha.water"):
        return 0  # alpha.water's water column is applied by setFields, not here
    internal = bc_matrix._internal_turbulence(model)
    return internal[field]
