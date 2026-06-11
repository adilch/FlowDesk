"""Deterministic OpenFOAM dictionary emitter.

FlowDesk *generates* files with its own canonical formatting (identical model =>
byte-identical output, NFR §9) and uses foamlib to *read* them back for the
round-trip contract. Output style matches the hand-written look of stock
OpenFOAM tutorials so generated cases read as vanilla (PRD §1.2).
"""

from __future__ import annotations

from collections.abc import Iterable

BANNER = """\
/*--------------------------------*- C++ -*----------------------------------*\\
| =========                 |                                                 |
| \\\\      /  F ield         | OpenFOAM: The Open Source CFD Toolbox           |
|  \\\\    /   O peration     | Version:  v2506                                 |
|   \\\\  /    A nd           | Website:  www.openfoam.com                      |
|    \\\\/     M anipulation  |                                                 |
\\*---------------------------------------------------------------------------*/
"""

SEPARATOR = "// * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * //"
FOOTER = "// ************************************************************************* //"

KEY_COLUMN = 16  # keyword padded to this width, like stock tutorials


def fmt(value: object) -> str:
    """Format a scalar value the OpenFOAM way."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return f"{value:g}"
    if isinstance(value, (tuple, list)):
        return "(" + " ".join(fmt(v) for v in value) + ")"
    return str(value)


def entry(key: str, value: object, indent: int = 0) -> str:
    pad = " " * indent
    key_padded = key.ljust(KEY_COLUMN - 1) if len(key) < KEY_COLUMN - 1 else key
    return f"{pad}{key_padded} {fmt(value)};"


def dimensioned(key: str, dims: Iterable[int], value: object, indent: int = 0) -> str:
    pad = " " * indent
    key_padded = key.ljust(KEY_COLUMN - 1) if len(key) < KEY_COLUMN - 1 else key
    dim_str = "[" + " ".join(str(d) for d in dims) + "]"
    return f"{pad}{key_padded} {dim_str} {fmt(value)};"


def block(name: str, lines: list[str], indent: int = 0) -> list[str]:
    """A named { ... } block; lines are already-formatted inner lines."""
    pad = " " * indent
    out = [f"{pad}{name}", f"{pad}{{"]
    out += [f"    {line}" if line else "" for line in lines]
    out.append(f"{pad}}}")
    return out


def foam_file(obj: str, cls: str = "dictionary", location: str | None = None) -> str:
    lines = [
        "FoamFile",
        "{",
        entry("version", "2.0", 4),
        entry("format", "ascii", 4),
        entry("class", cls, 4),
    ]
    if location is not None:
        lines.append(entry("location", f'"{location}"', 4))
    lines.append(entry("object", obj, 4))
    lines.append("}")
    return "\n".join(lines)


def document(obj: str, body: str, cls: str = "dictionary", location: str | None = None) -> str:
    """Assemble a complete dictionary file: banner, FoamFile, body, footer. Always LF."""
    return (
        BANNER
        + foam_file(obj, cls, location)
        + "\n"
        + SEPARATOR
        + "\n\n"
        + body.rstrip("\n")
        + "\n\n"
        + FOOTER
        + "\n"
    )
