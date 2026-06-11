# FlowDesk

A native desktop GUI (Windows + Linux) for setting up, running, and post-processing
OpenFOAM® CFD simulations.

**Core philosophy: "Generate, don't hide."** Every UI action maps to standard OpenFOAM
dictionary entries the user can open, read, diff, and version-control. FlowDesk is a
*case compiler with a cockpit*, not a proprietary wrapper.

- No artificial limits — no cell caps, no core caps, no metered hours.
- Generated cases are vanilla OpenFOAM (target: OpenFOAM.com v2506), portable anywhere.
- First-class Windows support via managed WSL2.
- Honest errors: real OpenFOAM stderr, verbatim, with plain-language explanations on top.

## Development

```
uv sync                 # install dependencies
uv run pytest           # run tests
uv run ruff check .     # lint
uv run flowdesk-gallery # living style gallery (design system)
```

## Architecture

Strict layering — imports allowed only downward (see PRD §7.1):

| Layer | Package | Responsibility |
|---|---|---|
| UI | `flowdesk.ui` | PyQt6 widgets, QSS theme, viewer |
| Application | `flowdesk.app` | project mgr, validation orchestration, staleness, undo |
| Case model | `flowdesk.model` | typed, serializable, validating — single source of truth |
| OpenFOAM adapter | `flowdesk.foam` | model ⇄ dictionaries via foamlib; version profiles; round-trip |
| Execution | `flowdesk.exec` | process supervision, pipelines, log parsers |
| Platform | `flowdesk.platform` | env discovery, WSL2 bridge, path translation |

## License

GPL-3.0-or-later.

*OPENFOAM® is a registered trade mark of OpenCFD Limited. This product is not approved
or endorsed by OpenCFD Limited.*
