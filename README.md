# FlowDesk

**A native desktop GUI for setting up, running, and post-processing OpenFOAM® CFD
simulations — with no artificial limits and nothing hidden.**

FlowDesk wraps the canonical OpenFOAM workflow — Geometry → Mesh → Physics →
Boundary Conditions → Numerics → Run → Results — in a single, modern, consistent
cockpit. It generates **standard, transparent, inspectable** OpenFOAM cases; it never
locks them away in a proprietary format.

> **Core philosophy: "Generate, don't hide."** Every UI action maps to standard
> OpenFOAM dictionary entries you can open, read, diff, and version-control. Power
> users can drop to the files at any time; beginners never have to. FlowDesk is a
> *case compiler with a cockpit*, not a black box.

---

## Why FlowDesk?

OpenFOAM is the most capable open-source CFD suite in existence, but its native
workflow is hostile to working engineers: hand-edited dictionary files with
unforgiving syntax, a case directory assembled by convention, a chain of CLI utilities
that must run in the right order with the right flags, and error messages written for
C++ developers. The existing GUI ecosystem is either expensive, cloud-locked and
metered, artificially capped, abandoned, or bolted onto a host CAD application.

FlowDesk is built for the engineer who knows CFD theory but uses OpenFOAM
intermittently and shouldn't have to relearn the dictionary syntax every project.

### Objective

Take a practicing engineer from **an STL and basic CFD knowledge to a running,
converged case in minutes** — without documentation — and produce a case directory a
CLI purist would find completely standard and portable.

### What makes it different

- **No artificial limits.** No cell caps, no core caps, no metered hours. Your
  hardware is the only limit.
- **Case transparency.** Generated cases are vanilla OpenFOAM (target:
  OpenFOAM.com v2506) — portable to clusters, ParaView, and colleagues.
- **First-class Windows** via managed WSL2: detection, guided install, transparent
  path translation.
- **Honest errors.** Real OpenFOAM stderr surfaced verbatim, with a plain-language
  explanation layered on top — never swallowed, never faked.
- **Round-trip contract.** Hand-edit a generated file and FlowDesk detects it, marks
  those keys "user-owned", and never silently overwrites your work.

---

## Features

### Workflow & setup
- **Step-by-step model wizard** — a SimScale-style decision tree (Single Phase /
  Multiphase / Free Surface / …) that resolves to the right OpenFOAM solver, with a
  feature-badge summary and a "choose solver manually" bypass.
- **Project templates** — a gallery of ready-to-run cases (lid-driven cavity, pipe
  flow, external aero, open channel, flow over a weir, dam break, vortex shedding,
  scalar mixing), plus **save any case as your own reusable template**.

### Geometry
- STL/OBJ import with automatic diagnostics (watertight, normals, units sanity).
- **Create primitives in-app** (box / sphere / cylinder / cone / plane), editable and
  regenerated on the fly, with per-object visibility toggles.

### Meshing
- `blockMesh` background mesh + `snappyHexMesh` refinement and snapping, with
  auto-suggested domain bounds and material point.
- **Optional surface refinement** — snap the geometry without adding refinement for a
  fast first mesh.
- A `checkMesh` **traffic-light quality report** and live mesh preview where you can
  **click patches to highlight them** in distinct colors.

### Physics & boundary conditions
- Steady (`simpleFoam`) and transient (`pimpleFoam`) single-phase flow; laminar,
  k-ε and k-ω SST turbulence.
- **Free-surface multiphase** (`interFoam`) for dam-break / hydraulics, with a water
  column initialized via `setFields`.
- **Passive scalar transport** for mixing and tracer studies.
- A **physical-intent boundary-condition system** (velocity/flow-rate/pressure inlets,
  pressure/total-pressure outlets, walls, slip, symmetry, atmosphere) that generates
  every field file atomically and consistently — plus per-field overrides for power
  users. Selecting a patch highlights it in the 3D view.

### Numerics & running
- Robust / Balanced / Accurate numerics presets, with a first-order-start assist.
- **Detached parallel execution**: the solver runs decoupled from the GUI, so closing
  FlowDesk doesn't kill the run — and reopening the project **re-attaches** to it.
- Live residual plots, Courant/continuity monitoring, graceful stop / kill.
- **Smart divergence diagnosis**: detects a struggling run from the live signals and
  offers one-click fixes (apply Robust numerics, lower the Courant number).
- **Runtime monitors** (function objects): forces & coefficients, flow rate, field
  min/max/average, point probes.

### Results
- In-app slices, surface contours, vector glyphs, and point probes via PyVista.
- **Animate through time steps** with a play/pause control, loop, and speed; a
  **color-range filter** (auto or fixed min/max) keeps colors comparable across frames.
- One-click **Open in ParaView** for everything beyond the in-app set.

### Platform & UX
- Managed WSL2 on Windows with guided OpenFOAM install and a `.wslconfig` helper.
- A collapsible icon rail, consistent resizable panels, a clean two-column landing
  screen, and a built-in dictionary file browser/editor.

---

## Installation & usage

FlowDesk targets **OpenFOAM.com v2506** on Linux, or Windows via WSL2. It uses
[`uv`](https://docs.astral.sh/uv/) for dependency management.

```bash
uv sync                  # install dependencies (Python 3.13+, PyQt6, PyVista, foamlib)
uv run flowdesk          # launch the app
```

On first launch FlowDesk probes your environment; if OpenFOAM (or WSL2 on Windows)
isn't found, a guided setup panel walks you through installing it once.

Developer commands:

```bash
uv run pytest            # run the test suite
uv run ruff check .      # lint
uv run flowdesk-gallery  # living style-gallery window (the design system)
```

---

## Architecture

Strict downward-only layering keeps the model and adapter headless and unit-testable
without Qt — which is also the seed of a future scripting API.

| Layer | Package | Responsibility |
|---|---|---|
| UI | `flowdesk.ui` | PyQt6 widgets, QSS theme, 3D viewer |
| Application | `flowdesk.app` | project manager, validation, staleness, templates |
| Case model | `flowdesk.model` | typed, serializable, validating — single source of truth |
| OpenFOAM adapter | `flowdesk.foam` | model ⇄ dictionaries via foamlib; round-trip engine |
| Execution | `flowdesk.exec` | process supervision, pipelines, log parsers, diagnosis |
| Platform | `flowdesk.platform` | environment discovery, WSL2 bridge, path translation |

The generated case is plain OpenFOAM plus a single `flowdesk.json` sidecar inside the
case directory. Delete the sidecar and you have an ordinary OpenFOAM case — by design.

---

## Contributing

**FlowDesk is open source and we'd genuinely love your help.** Whether you're a CFD
engineer, a Python/Qt developer, or just someone who hit a rough edge — contributions
of every size are warmly welcomed and deeply appreciated. 🙏

Ways to help:

- **Try it and report what breaks.** Bug reports with a case that reproduces the issue
  are gold.
- **Suggest features** or share the workflows you wish were faster.
- **Add or improve templates**, error explanations, BC types, or solvers.
- **Improve docs** — even fixing a confusing sentence helps the next person.
- **Pick up code** — the model and adapter layers are headless and fully tested, so
  they're a friendly place to start.

To get started: fork the repo, `uv sync`, make your change, run `uv run pytest` and
`uv run ruff check .`, and open a pull request. Open an issue first if you'd like to
discuss a larger change. Please be kind and constructive — this is a welcoming project.

If FlowDesk is useful to you, a ⭐ on the repo genuinely helps and means a lot.

---

## Status

FlowDesk is under active development. The core workflow (geometry → mesh → physics →
BCs → numerics → run → results) is complete and verified end-to-end against real
OpenFOAM v2506, including parallel runs, free-surface dam breaks, and transient vortex
shedding. See the commit history for the milestone-by-milestone build.

## License

**GPL-3.0-or-later.**

*OPENFOAM® is a registered trade mark of OpenCFD Limited. This product is not approved
or endorsed by OpenCFD Limited.*
