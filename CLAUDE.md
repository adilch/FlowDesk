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

- M0 (scaffold, theme/gallery, foamlib + viewer + WSL-bridge spikes) ✅
- Next: M1 — case model (§7.4), dictionary generation for §4, ownership/round-trip
  engine (§4.9), file browser/editor, golden-file harness.
