# Contributing to FlowDesk

Thank you for considering a contribution — it genuinely means a lot. FlowDesk aims to
make OpenFOAM approachable for working engineers, and every improvement, big or small,
moves that forward. **All contributions are warmly welcomed and deeply appreciated.**

## Ways to contribute

- **Report bugs.** The most valuable report includes a project/case that reproduces the
  problem, what you expected, and what happened (the OpenFOAM log is helpful).
- **Request features** or describe a workflow you wish were faster.
- **Add templates, error explanations, BC types, or solver support.**
- **Improve documentation** — clarity fixes count.
- **Write code** — the `flowdesk.model` and `flowdesk.foam` layers are headless and
  fully unit-tested, which makes them a friendly starting point.

## Development setup

FlowDesk uses [`uv`](https://docs.astral.sh/uv/) and targets Python 3.13+ with
OpenFOAM.com v2506 (native Linux, or Windows via WSL2).

```bash
uv sync                  # install dependencies
uv run flowdesk          # launch the app
uv run pytest            # run the test suite
uv run ruff check .      # lint (must pass)
```

## Pull request guidelines

1. Fork the repository and create a branch off `main`.
2. Keep changes focused; open an issue first to discuss larger ones.
3. Add or update tests for any behavior you change — the suite is the safety net.
4. Run `uv run pytest` and `uv run ruff check .` before opening the PR; both should pass.
5. Match the surrounding code style. All UI styling lives in `theme.py`
   (the no-inline-styles rule is lint-enforced).
6. Describe what changed and why. Screenshots help for UI changes.

## Code of conduct

Be kind, patient, and constructive. We want FlowDesk to be a welcoming place for
people of all experience levels — first-time contributors especially.

## License

By contributing, you agree that your contributions are licensed under the project's
**GPL-3.0-or-later** license.
