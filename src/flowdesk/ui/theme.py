"""FlowDesk design system (PRD §6). The ONLY place styling may be defined.

No inline styles anywhere else in the codebase: ``setStyleSheet`` outside this
module is forbidden and lint-enforced (tests/test_no_inline_styles.py).
Widgets opt into variants via Qt dynamic properties, e.g.::

    button.setProperty("variant", "primary")
    chip.setProperty("status", "complete")
"""

from __future__ import annotations

from dataclasses import dataclass

# --- Color tokens (PRD §6.1, dark theme - MVP ships dark-only) -----------------

COLORS = {
    "bg-0": "#15191E",  # app background
    "bg-1": "#1C2127",  # panels, rail
    "bg-2": "#242A32",  # cards, inputs, drawer
    "border": "#313A45",  # 1px hairlines
    "text-1": "#E8EDF2",  # primary text
    "text-2": "#9AA7B4",  # secondary, units, captions
    "accent": "#3D9BE9",  # primary actions, selection, links, focus ring
    "accent-press": "#2E7FC4",
    "ok": "#3FB970",
    "warn": "#E0A93E",
    "error": "#E25D5D",
    "run": "#8B6FE8",  # running state, progress
    "viewport-top": "#262B33",  # 3D viewer gradient only
    "viewport-bottom": "#1A1E24",
}

# OpenFOAM dictionary syntax highlighting (file editor, §4.9) - part of the one theme
SYNTAX_COLORS = {
    "comment": "#6A7A89",
    "keyword": "#3D9BE9",  # FoamFile, dictionary structure words
    "number": "#B5CEA8",
    "string": "#CE9178",
    "dimension": "#8B6FE8",  # [0 1 -1 0 0 0 0]
    "directive": "#E0A93E",  # #include, #eval, $macro
}

# Patch-assignment categorical palette (color-blind-safe, Okabe-Ito; PRD §6.1)
PATCH_COLORS = {
    "inlet": "#0072B2",
    "outlet": "#D55E00",
    "wall": "#999999",
    "symmetry": "#56B4E9",
    "slip": "#009E73",
    # unassigned renders as amber hazard stripes in the viewer, not a flat color
}

# --- Typography (PRD §6.2) ------------------------------------------------------
# Inter / JetBrains Mono are to be bundled with the installer (M6); until then we
# fall back to close system equivalents so development builds look right.

FONT_UI = '"Inter", "Segoe UI", "Noto Sans", sans-serif'
FONT_MONO = '"JetBrains Mono", "Cascadia Mono", "Consolas", monospace'

FONT_SIZE_UI = 13  # px, weight 400
FONT_SIZE_TITLE = 18  # px, weight 600
FONT_SIZE_MONO = 12.5  # px
FONT_SIZE_PLOT = 11  # px, plot axes

# --- Spacing & geometry (PRD §6.3) -----------------------------------------------

GRID = 4  # base grid, px
PANEL_PADDING = 16
CONTROL_RHYTHM = 8  # vertical rhythm between controls
GROUP_GAP = 24
RADIUS_INPUT = 6
RADIUS_CARD = 8
CONTROL_HEIGHT = 32
TABLE_ROW_HEIGHT = 28
RAIL_WIDTH = 220
RIGHT_PANEL_WIDTH = 320  # resizable 280-420
RIGHT_PANEL_MIN = 280
RIGHT_PANEL_MAX = 420
DRAWER_HEIGHT = 280


@dataclass(frozen=True)
class StageStatus:
    """The six stage states (PRD §4.0) with their chip glyph and color token."""

    key: str
    glyph: str
    color: str  # token name in COLORS
    label: str


STAGE_STATUSES = {
    "empty": StageStatus("empty", "○", "text-2", "Not started"),
    "in_progress": StageStatus("in_progress", "◐", "accent", "In progress"),
    "complete": StageStatus("complete", "✔", "ok", "Complete"),
    "warnings": StageStatus("warnings", "⚠", "warn", "Complete with warnings"),
    "invalid": StageStatus("invalid", "❌", "error", "Blocking errors"),
    "stale": StageStatus("stale", "⟳", "run", "Upstream change - stale"),
}


def build_qss() -> str:
    """Assemble the application stylesheet from the tokens above."""
    c = COLORS
    return f"""
QWidget {{
    background-color: {c["bg-0"]};
    color: {c["text-1"]};
    font-family: {FONT_UI};
    font-size: {FONT_SIZE_UI}px;
}}

/* ---- Panels & cards ---- */
QFrame[panel="true"] {{
    background-color: {c["bg-1"]};
    border: none;
}}
QFrame[card="true"] {{
    background-color: {c["bg-2"]};
    border: 1px solid {c["border"]};
    border-radius: {RADIUS_CARD}px;
}}

/* ---- Labels ---- */
QLabel {{ background: transparent; }}
QLabel[role="title"] {{ font-size: {FONT_SIZE_TITLE}px; font-weight: 600; }}
QLabel[role="section"] {{
    font-size: {FONT_SIZE_UI}px; font-weight: 600;
    letter-spacing: 1px; text-transform: uppercase;
    color: {c["text-2"]};
}}
QLabel[role="caption"] {{ color: {c["text-2"]}; }}
QLabel[role="unit"] {{ color: {c["text-2"]}; }}

/* ---- Buttons ---- */
QPushButton {{
    background-color: {c["bg-2"]};
    border: 1px solid {c["border"]};
    border-radius: {RADIUS_INPUT}px;
    min-height: {CONTROL_HEIGHT - 2}px;
    padding: 0 14px;
}}
QPushButton:hover {{ border-color: {c["accent"]}; }}
QPushButton:pressed {{ background-color: {c["bg-1"]}; }}
QPushButton:disabled {{ color: {c["text-2"]}; border-color: {c["border"]}; }}
QPushButton[variant="primary"] {{
    background-color: {c["accent"]};
    border: none;
    color: #FFFFFF;
    font-weight: 600;
}}
QPushButton[variant="primary"]:hover {{ background-color: #4FA8F0; }}
QPushButton[variant="primary"]:pressed {{ background-color: {c["accent-press"]}; }}
QPushButton[variant="danger"] {{
    background-color: transparent;
    border: 1px solid {c["error"]};
    color: {c["error"]};
}}
QPushButton[variant="danger"]:hover {{ background-color: {c["error"]}; color: #FFFFFF; }}
QPushButton[variant="ghost"] {{
    background-color: transparent;
    border: none;
    color: {c["accent"]};
}}
QPushButton[variant="ghost"]:hover {{ text-decoration: underline; }}

/* ---- Inputs ---- */
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background-color: {c["bg-2"]};
    border: 1px solid {c["border"]};
    border-radius: {RADIUS_INPUT}px;
    min-height: {CONTROL_HEIGHT - 2}px;
    padding: 0 8px;
    selection-background-color: {c["accent"]};
}}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{
    border-color: {c["accent"]};
}}
QLineEdit[invalid="true"], QSpinBox[invalid="true"], QDoubleSpinBox[invalid="true"] {{
    border-color: {c["error"]};
}}
QLineEdit:disabled, QComboBox:disabled {{ color: {c["text-2"]}; }}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox QAbstractItemView {{
    background-color: {c["bg-2"]};
    border: 1px solid {c["border"]};
    selection-background-color: {c["accent"]};
}}

/* ---- Checkboxes ---- */
QCheckBox {{ background: transparent; spacing: 8px; }}
QCheckBox::indicator {{
    width: 16px; height: 16px;
    border: 1px solid {c["border"]};
    border-radius: 4px;
    background-color: {c["bg-2"]};
}}
QCheckBox::indicator:checked {{
    background-color: {c["accent"]};
    border-color: {c["accent"]};
}}

/* ---- Tables ---- */
QTableWidget, QTableView {{
    background-color: {c["bg-1"]};
    border: 1px solid {c["border"]};
    border-radius: {RADIUS_INPUT}px;
    gridline-color: {c["border"]};
}}
QHeaderView::section {{
    background-color: {c["bg-2"]};
    color: {c["text-2"]};
    border: none;
    border-bottom: 1px solid {c["border"]};
    padding: 4px 8px;
    font-weight: 600;
}}
QTableWidget::item:selected {{ background-color: {c["accent"]}; }}

/* ---- Progress bars: tall enough that the value text is readable ---- */
QProgressBar {{
    background-color: {c["bg-2"]};
    border: none;
    border-radius: 4px;
    min-height: 20px;
    max-height: 20px;
    text-align: center;
    color: {c["text-1"]};
    font-weight: 600;
}}
QProgressBar::chunk {{ background-color: {c["run"]}; border-radius: 4px; }}

/* ---- Scrollbars ---- */
QScrollBar:vertical {{ background: {c["bg-1"]}; width: 10px; }}
QScrollBar::handle:vertical {{
    background: {c["border"]}; border-radius: 5px; min-height: 24px;
}}
QScrollBar::handle:vertical:hover {{ background: {c["text-2"]}; }}
QScrollBar:horizontal {{ background: {c["bg-1"]}; height: 10px; }}
QScrollBar::handle:horizontal {{
    background: {c["border"]}; border-radius: 5px; min-width: 24px;
}}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}

/* ---- Log / code views ---- */
QPlainTextEdit[role="log"], QTextEdit[role="code"] {{
    background-color: {c["bg-0"]};
    border: 1px solid {c["border"]};
    border-radius: {RADIUS_INPUT}px;
    font-family: {FONT_MONO};
    font-size: {FONT_SIZE_MONO}px;
}}

/* ---- Banners (inline, never modal) ---- */
QFrame[banner="info"] {{
    background-color: rgba(61, 155, 233, 0.12);
    border: 1px solid {c["accent"]};
    border-radius: {RADIUS_INPUT}px;
}}
QFrame[banner="warn"] {{
    background-color: rgba(224, 169, 62, 0.12);
    border: 1px solid {c["warn"]};
    border-radius: {RADIUS_INPUT}px;
}}
QFrame[banner="error"] {{
    background-color: rgba(226, 93, 93, 0.12);
    border: 1px solid {c["error"]};
    border-radius: {RADIUS_INPUT}px;
}}

/* ---- Status chips ---- */
QLabel[chip="true"] {{
    border-radius: 9px;
    padding: 1px 8px;
    background-color: {c["bg-2"]};
}}
QLabel[status="empty"] {{ color: {c["text-2"]}; }}
QLabel[status="in_progress"] {{ color: {c["accent"]}; }}
QLabel[status="complete"] {{ color: {c["ok"]}; }}
QLabel[status="warnings"] {{ color: {c["warn"]}; }}
QLabel[status="invalid"] {{ color: {c["error"]}; }}
QLabel[status="stale"] {{ color: {c["run"]}; }}

/* ---- Segmented control (QPushButton group) ---- */
QPushButton[segment="true"] {{
    border-radius: 0;
    border: 1px solid {c["border"]};
    background-color: {c["bg-2"]};
}}
QPushButton[segment="true"]:checked {{
    background-color: {c["accent"]};
    color: #FFFFFF;
    border-color: {c["accent"]};
}}
QPushButton[segment="first"] {{
    border-top-left-radius: {RADIUS_INPUT}px;
    border-bottom-left-radius: {RADIUS_INPUT}px;
}}
QPushButton[segment="last"] {{
    border-top-right-radius: {RADIUS_INPUT}px;
    border-bottom-right-radius: {RADIUS_INPUT}px;
}}

/* ---- Tooltips ---- */
QToolTip {{
    background-color: {c["bg-2"]};
    color: {c["text-1"]};
    border: 1px solid {c["border"]};
    padding: 6px;
}}
"""


def load_bundled_fonts() -> list[str]:
    """Register the bundled Inter + JetBrains Mono (OFL; licenses ship alongside).
    Falls back silently to system fonts when loading fails."""
    from pathlib import Path

    from PyQt6.QtGui import QFontDatabase

    loaded = []
    fonts_dir = Path(__file__).parent / "assets" / "fonts"
    if not fonts_dir.exists():
        return loaded
    for ttf in sorted(fonts_dir.glob("*.ttf")):
        font_id = QFontDatabase.addApplicationFont(str(ttf))
        if font_id >= 0:
            loaded += QFontDatabase.applicationFontFamilies(font_id)
    return loaded


def apply_theme(app) -> None:
    """Apply the FlowDesk theme to a QApplication. Call once at startup."""
    load_bundled_fonts()
    app.setStyleSheet(build_qss())


def repolish(widget) -> None:
    """Force a style re-evaluation after changing a dynamic property at runtime."""
    widget.style().unpolish(widget)
    widget.style().polish(widget)
