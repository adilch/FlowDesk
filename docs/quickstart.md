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
