# Quickstart

## Install

**Windows 11:** run the FlowDesk installer. On first launch FlowDesk checks for
WSL2 and OpenFOAM v2506 and walks you through anything missing (one UAC prompt;
a reboot only if Windows requires it — FlowDesk tells you honestly either way).

**Ubuntu 24.04:** install OpenFOAM v2506 from openfoam.com's apt repository,
then `pip install flowdesk` / run the AppImage (packaging in progress).

## The 15-minute path: STL → running case

1. **New Project** → pick a template (External aero is a good externals start).
2. **Geometry**: import your STL. FlowDesk checks watertightness and normals,
   and asks about units if the size looks like millimetres.
3. **Mesh**: *Fit to geometry* sizes the background box; the Refinement tab has
   per-surface levels and boundary layers. *Suggest* picks the material point.
   **Generate Mesh** runs the chain and shows a traffic-light quality report.
4. **Physics**: steady/transient, turbulence model, fluid. The derived k/ω/ε
   values update live.
5. **Boundary Conditions**: click patches, assign physical intent ("velocity
   inlet, 2 m/s") — FlowDesk writes every field file consistently, wall
   functions included.
6. **Numerics**: leave it on *Robust* the first time.
7. **Run**: parallel by default, live residuals. The solver is detached — you
   can close FlowDesk and re-open later; it re-attaches.
8. **Results**: slice, probe, screenshot — or *Open in ParaView*.

## Try a transient case

The **Vortex shedding (transient)** template is the recommended first transient
run: laminar flow past a square cylinder at Re = 100 — a textbook von Kármán
vortex street. The cylinder geometry is generated for you.

1. New Project → *Vortex shedding (transient)*.
2. **Mesh → Generate Mesh** (snappy refines around the cylinder; ~30 s).
3. **Run** — watch the Courant readout and the residuals oscillate as shedding
   develops (that's physics, not divergence).
4. **Results**: step through the time selector to watch vortices convect, or
   *Open in ParaView* and animate. Probe a point at (1.0, 0, 0.025) and step
   times to see the periodic velocity signal.

It simulates 10 s of flow time with output every 0.2 s — the street takes
~5 s to develop, then sheds periodically. About two minutes of wall time on
4 cores. The case is quasi-2D (thin slab, slip front/back) because
snappyHexMesh cannot preserve true one-cell 2D meshes — stated here so you
don't wonder.

## Free surface: the dam break

Two dam-break templates ship:

**Dam break (3D breach)** follows the SimFlow dam-break tutorial workflow: a
50 × 30 × 20 m valley **domain** is meshed with the generated `dam.stl`
**obstacle** carved out by snappyHexMesh (the material point sits downstream
in the fluid at (10, 15, 5) — the domain is meshed, never the dam itself),
and the **water_init volume** [-20..0, 0..30, 0..9] — drawn as a translucent
blue box in the viewer — initializes the reservoir behind the dam. Run it and
water pours through the 6 m breach. An upstream inlet feeds 250 m³/s with
zero-gradient phase. Ships at 10 s of flow time; extend toward 60 s for the
full tutorial draining.

**Dam break (2D column)** is the classic fast benchmark: a
0.146 m × 0.292 m water column collapses across a 0.584 m tank under gravity
(2D, laminar — matching the canonical OpenFOAM tutorial).

1. New Project → *Dam break (2D column)*.
2. **Mesh → Generate Mesh** (pure blockMesh; instant).
3. **Run** — FlowDesk runs `setFields` first (you'll see it in the log) to
   place the water column, then interFoam. About 10 s of wall time for 1 s of
   flow at 50 output frames.
4. **Results**: pick the **alpha.water** field (1 = water, 0 = air) and step
   through time — collapse, surge across the floor, impact and climb up the
   right wall (~0.5 s), then slosh back. *Open in ParaView* and threshold at
   alpha = 0.5 to see the free surface itself.

Free-surface physics lives in **Physics → Free surface (interFoam)**: second
fluid, surface tension, gravity, and the initial water column box. The
**Atmosphere (open)** BC type is the matching open-top boundary. Restarting a
finished run does *not* re-flood the column (setFields only runs on a virgin
case) — use *Reset case & rerun* to start the collapse over.

## Hydraulics: flow over a weir

The **Flow over a weir** template is a channel with a generated half-depth weir:
water accelerates over the crest and recirculates downstream — slice on Y at
mid-channel to see it. It saves every 100th iteration with nothing purged, so
the **Results time selector lets you scrub through the convergence history**,
not just the final state.

Honest scope note: this is single-phase with a rigid-lid (slip) surface. A true
free-surface dam break (like SimFlow's interFoam tutorial) needs multiphase
solvers — that is FlowDesk's Phase-2 hydraulics target, not in the MVP.

### Controlling what gets saved

Run stage → **Write controls (controlDict)**:

- *Write every* — iterations (steady) or seconds (transient) between saves.
- *Keep last N writes* — OpenFOAM's `purgeWrite`; **0 keeps everything**.
  Steady templates other than the weir default to keeping the last 2.
- Format and precision, with a live disk-use estimate.

## Where things live

- Your project = one OpenFOAM case directory (+ `flowdesk.json` sidecar).
- On Windows, projects default to the Linux filesystem
  (`\\wsl$\Ubuntu-24.04\home\<you>\flowdesk`) because OpenFOAM I/O is 5–20×
  faster there. Browse it from Explorer like any folder.
- Hand-edit any case file: FlowDesk detects it, marks those keys ✎ yours, and
  never overwrites them. "Take back control" reverts to managed values.

## Keyboard

| Key | Action |
|---|---|
| Ctrl+1…7 | Jump to workflow stage |
| Ctrl+S | Force-save the model |
| Ctrl+R | Go to Run |
| F | Fit the 3D view |
