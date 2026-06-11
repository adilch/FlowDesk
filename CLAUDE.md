# FlowDesk

Desktop GUI (PyQt6) for OpenFOAM CFD. Spec: `FlowDesk_PRD.md` in
`C:\Users\adilj\OneDrive\Documents\ClaudeApp\FlowDesk\` — the PRD gates all work.
Target: OpenFOAM.com **v2506, pinned**. License: GPL-3.0-or-later.

## Commands

- `uv run pytest` — test suite (WSL-dependent tests auto-skip when WSL absent)
- `uv run ruff check .` — lint (must stay clean)
- `uv run flowdesk-gallery` — living style gallery of the design system
- `uv run python spikes/viewer_spike.py --seconds 5` — viewer FPS spike

## Architecture rules (PRD §7.1 — enforced by review, violations are bugs)

Strict layering, imports only downward:
`ui → app → model → foam → exec → platform`

- `flowdesk.model` is the single source of truth: pydantic, no Qt, no file I/O.
- UI never touches files or processes directly.
- All OpenFOAM file I/O goes through foamlib in `flowdesk.foam`.
- All WSL/cross-boundary paths go through `flowdesk.platform.wsl` — nowhere else.
- **No `setStyleSheet` outside `ui/theme.py`** (test-enforced). Widgets use dynamic
  properties (`variant`, `status`, `banner`…) + `theme.repolish()`.
- Components must come from the PRD §6.4 inventory — don't invent ad-hoc widgets.

## Conventions

- LF line endings everywhere (`.gitattributes` enforces; golden tests compare bytes).
- Generated dictionaries must be deterministic: identical model ⇒ identical bytes.
- Honesty principle: never swallow OpenFOAM errors, never silently retry, never
  write a file FlowDesk couldn't re-read. Unparseable user edits → file "detached".
- foamlib normalizes whitespace on rewritten lines: byte-stability holds only for
  foamlib/FlowDesk-formatted files; semantic equality is the contract for user files.

## State

All MVP milestones M0–M6 complete (2026-06-11). The full 15-minute journey,
all four templates serial+parallel, round-trip/ownership, detached run with
re-attach, results post-processing, environment flows, and the PyInstaller
build (474 MB) are implemented and gate-tested against real OpenFOAM v2506
via WSL. Remaining for release: human beta testing (§11 M6), clean-VM install
verification, Ubuntu GUI pass, and code signing.

Build the exe: `uv run pyinstaller flowdesk.spec --noconfirm` → dist/FlowDesk/.
