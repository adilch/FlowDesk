"""SVG icon set rendered to themed QIcons.

FlowDesk's own clean line icons (outline, 24px grid, stroke = theme color) so
the app uses real icons instead of Unicode glyphs. Authored geometric shapes -
not copied from any icon set. Render with `icon(name, color)`.
"""

from __future__ import annotations

from functools import lru_cache

from PyQt6.QtCore import QByteArray, QRectF, Qt
from PyQt6.QtGui import QIcon, QPainter, QPixmap
from PyQt6.QtSvg import QSvgRenderer

from flowdesk.ui.theme import COLORS

# Inner SVG bodies; CURRENTCOLOR is substituted with the requested colour.
_ICONS: dict[str, str] = {
    # workflow stages
    "geometry": '<path d="M12 2 21 7 21 17 12 22 3 17 3 7Z"/>'
                '<path d="M3 7 12 12 21 7"/><path d="M12 12 12 22"/>',
    "mesh": '<rect x="3" y="3" width="18" height="18" rx="1"/>'
            '<path d="M3 9H21M3 15H21M9 3V21M15 3V21"/>',
    "physics": '<path d="M3 8C6 5 9 11 12 8 15 5 18 11 21 8"/>'
               '<path d="M3 14C6 11 9 17 12 14 15 11 18 17 21 14"/>',
    "boundaries": '<path d="M4 9V5a1 1 0 0 1 1-1h4"/>'
                  '<path d="M15 4h4a1 1 0 0 1 1 1v4"/>'
                  '<path d="M20 15v4a1 1 0 0 1-1 1h-4"/>'
                  '<path d="M9 20H5a1 1 0 0 1-1-1v-4"/>',
    "numerics": '<path d="M4 7H20M4 12H20M4 17H20"/>'
                '<circle cx="9" cy="7" r="2"/><circle cx="15" cy="12" r="2"/>'
                '<circle cx="8" cy="17" r="2"/>',
    "run": '<path d="M8 5v14l11-7z"/>',
    "results": '<path d="M3 20H21"/><rect x="5" y="11" width="3.5" height="7"/>'
               '<rect x="10.2" y="5" width="3.5" height="13"/>'
               '<rect x="15.5" y="13" width="3.5" height="5"/>',
    # actions / chrome
    "save": '<path d="M5 3h11l5 5v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z"/>'
            '<path d="M8 3v5h8"/><rect x="8" y="13" width="8" height="6"/>',
    "close": '<path d="M6 6 18 18M18 6 6 18"/>',
    "chevron-left": '<path d="M15 6 9 12 15 18"/>',
    "chevron-right": '<path d="M9 6 15 12 9 18"/>',
    "chevron-up": '<path d="M6 15 12 9 18 15"/>',
    "chevron-down": '<path d="M6 9 12 15 18 9"/>',
    "plus": '<path d="M12 5V19M5 12H19"/>',
    "import": '<path d="M12 3v12M7 8l5-5 5 5"/><path d="M4 17v3h16v-3"/>',
    "folder": '<path d="M3 7a1 1 0 0 1 1-1h5l2 2h9a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1H4'
              'a1 1 0 0 1-1-1z"/>',
    "play": '<path d="M8 5v14l11-7z"/>',
    "stop": '<rect x="6" y="6" width="12" height="12" rx="1"/>',
    "eye": '<path d="M2 12C5 6 19 6 22 12 19 18 5 18 2 12Z"/>'
           '<circle cx="12" cy="12" r="3"/>',
    "eye-off": '<path d="M3 3 21 21"/>'
               '<path d="M10.6 10.6a3 3 0 0 0 4 4"/>'
               '<path d="M9.4 5.2A10 10 0 0 1 12 5c5 0 9 4 10 7a13 13 0 0 1-2.2 3.1"/>'
               '<path d="M6.3 6.3A13 13 0 0 0 2 12c1 3 5 7 10 7a10 10 0 0 0 2.6-.3"/>',
    "fit": '<path d="M4 8V4h4M16 4h4v4M20 16v4h-4M8 20H4v-4"/>',
    "refresh": '<path d="M4 12a8 8 0 0 1 14-5l2 2"/><path d="M20 5v4h-4"/>'
               '<path d="M20 12a8 8 0 0 1-14 5l-2-2"/><path d="M4 19v-4h4"/>',
    "trash": '<path d="M4 7h16"/><path d="M9 7V5h6v2"/>'
             '<path d="M6 7l1 13h10l1-13"/>',
    "ruler": '<rect x="3" y="8" width="18" height="8" rx="1"/>'
             '<path d="M7 8v3M11 8v4M15 8v3M19 8v4"/>',
}

_VIEWBOX = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" ' \
           'fill="none" stroke="CURRENTCOLOR" stroke-width="1.8" ' \
           'stroke-linecap="round" stroke-linejoin="round">{body}</svg>'


@lru_cache(maxsize=256)
def _render(name: str, color: str, size: int) -> QIcon:
    body = _ICONS[name]
    svg = _VIEWBOX.format(body=body).replace("CURRENTCOLOR", color)
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter, QRectF(0, 0, size, size))
    painter.end()
    return QIcon(pixmap)


def icon(name: str, color: str | None = None, size: int = 20) -> QIcon:
    """A themed QIcon for `name`. Default colour is the primary text token."""
    return _render(name, color or COLORS["text-1"], size)


STAGE_ICON = {
    "geometry": "geometry", "mesh": "mesh", "physics": "physics",
    "boundaries": "boundaries", "numerics": "numerics", "run": "run",
    "results": "results",
}
