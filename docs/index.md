# FlowDesk

A native desktop GUI (Windows + Linux) for setting up, running, and post-processing
OpenFOAM® CFD simulations.

**Generate, don't hide.** Every control in FlowDesk maps to a standard OpenFOAM
dictionary entry. The case directory FlowDesk produces is vanilla OpenFOAM v2506 —
open it, diff it, version-control it, copy it to a cluster, or hand it to a
colleague who has never heard of FlowDesk. Delete `flowdesk.json` and nothing
else changes.

## Why FlowDesk

| | |
|---|---|
| **No artificial limits** | No cell caps, no core caps, no metered hours. Your hardware is the limit. |
| **Transparent cases** | Standard, portable OpenFOAM v2506 cases. The built-in editor shows exactly what FlowDesk manages and what you own. |
| **First-class Windows** | Managed WSL2: guided install, transparent path policy, Windows ParaView against `\\wsl$` paths. |
| **Honest errors** | The verbatim OpenFOAM message, always — with a plain-language explanation layered on top when FlowDesk recognizes the pattern. |

## Get started

See the [Quickstart](quickstart.md). The short version: install, click
**Try the cavity tutorial**, and you'll have meshed, solved, and sliced a case
inside five minutes.

## License & trademarks

FlowDesk is free software under the [GPL-3.0-or-later](../LICENSE).
Bundled fonts (Inter, JetBrains Mono) are licensed under the SIL Open Font
License — see `src/flowdesk/ui/assets/fonts/`.

*OPENFOAM® is a registered trade mark of OpenCFD Limited. This offering is not
approved or endorsed by OpenCFD Limited, producer and distributor of the
OpenFOAM software via www.openfoam.com.*
