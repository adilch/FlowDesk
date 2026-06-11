"""Core reusable components (PRD §6.4). Nothing outside this inventory may be invented ad hoc.

All styling comes from theme.py via dynamic properties - no setStyleSheet calls here.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from flowdesk.ui.theme import CONTROL_RHYTHM, STAGE_STATUSES, repolish

# --- Buttons --------------------------------------------------------------------


def make_button(
    text: str, variant: str = "secondary", parent: QWidget | None = None
) -> QPushButton:
    """Button factory. variant: primary | secondary | ghost | danger."""
    btn = QPushButton(text, parent)
    if variant != "secondary":
        btn.setProperty("variant", variant)
    return btn


# --- Numeric input with unit suffix (PRD §4 conventions, §6.4) --------------------

# Conversion factors to the SI base unit of each dimension.
_UNIT_FACTORS: dict[str, dict[str, float]] = {
    "m": {"m": 1.0, "mm": 1e-3, "cm": 1e-2, "in": 0.0254, "ft": 0.3048},
    "m/s": {"m/s": 1.0, "mm/s": 1e-3, "km/h": 1 / 3.6, "ft/s": 0.3048},
    "m2/s": {"m2/s": 1.0, "m^2/s": 1.0, "cSt": 1e-6},
    "s": {"s": 1.0, "ms": 1e-3, "min": 60.0, "h": 3600.0},
    "%": {"%": 1.0},
    "deg": {"deg": 1.0, "°": 1.0},
    "": {"": 1.0},
}

_NUM_WITH_UNIT = re.compile(r"^\s*([+-]?[\d.]+(?:[eE][+-]?\d+)?)\s*([a-zA-Z/%°^\d]*)\s*$")


def parse_quantity(text: str, si_unit: str) -> float | None:
    """Parse '200 mm' -> 0.2 when si_unit='m'. Returns None if unparseable."""
    m = _NUM_WITH_UNIT.match(text)
    if not m:
        return None
    value = float(m.group(1))
    unit = m.group(2)
    factors = _UNIT_FACTORS.get(si_unit, {"": 1.0})
    if not unit:
        return value
    if unit in factors:
        return value * factors[unit]
    return None


class UnitLineEdit(QWidget):
    """Numeric field with its SI unit rendered inside the field ([num] control).

    Accepts unit-suffixed entry ('200 mm' -> 0.2 m). Emits valueChanged(float)
    with the SI value on every successful edit; sets the 'invalid' property on
    parse failure or range violation (validate on blur, never block typing).
    """

    valueChanged = pyqtSignal(float)

    def __init__(
        self,
        unit: str = "",
        value: float = 0.0,
        minimum: float | None = None,
        maximum: float | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._unit = unit
        self._min = minimum
        self._max = maximum
        self._value = value

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._edit = QLineEdit(self._format(value))
        self._edit.editingFinished.connect(self._commit)
        layout.addWidget(self._edit)
        if unit:
            suffix = QLabel(unit)
            suffix.setProperty("role", "unit")
            layout.addWidget(suffix)
            layout.setSpacing(6)

    @staticmethod
    def _format(v: float) -> str:
        return f"{v:g}"

    def value(self) -> float:
        return self._value

    def set_value(self, v: float) -> None:
        self._value = v
        self._edit.setText(self._format(v))
        self._set_invalid(False)

    def _set_invalid(self, bad: bool) -> None:
        self._edit.setProperty("invalid", "true" if bad else "false")
        repolish(self._edit)

    def _commit(self) -> None:
        v = parse_quantity(self._edit.text(), self._unit)
        if v is None or (self._min is not None and v < self._min) or (
            self._max is not None and v > self._max
        ):
            self._set_invalid(True)
            return
        self._set_invalid(False)
        self._value = v
        self._edit.setText(self._format(v))  # normalize '200 mm' -> '0.2'
        self.valueChanged.emit(v)


class Vec3Input(QWidget):
    """Three numeric fields (x, y, z) sharing one unit ([vec3] control)."""

    valueChanged = pyqtSignal(float, float, float)

    def __init__(self, unit: str = "m", value=(0.0, 0.0, 0.0), parent: QWidget | None = None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(CONTROL_RHYTHM)
        self._fields: list[UnitLineEdit] = []
        for axis, v in zip("xyz", value, strict=True):
            field = UnitLineEdit(unit="", value=v)
            field._edit.setPlaceholderText(axis)
            field.valueChanged.connect(self._emit)
            self._fields.append(field)
            layout.addWidget(field)
        suffix = QLabel(unit)
        suffix.setProperty("role", "unit")
        layout.addWidget(suffix)

    def value(self) -> tuple[float, float, float]:
        x, y, z = (f.value() for f in self._fields)
        return (x, y, z)

    def set_values(self, values: tuple[float, float, float]) -> None:
        for field, v in zip(self._fields, values, strict=True):
            field.set_value(v)

    def _emit(self) -> None:
        self.valueChanged.emit(*self.value())


# --- Segmented control ------------------------------------------------------------


class SegmentedControl(QWidget):
    """[seg] control: exclusive choice rendered as joined buttons."""

    selectionChanged = pyqtSignal(int)

    def __init__(self, options: Sequence[str], current: int = 0, parent: QWidget | None = None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        for i, label in enumerate(options):
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setProperty("segment", "true")
            if i == 0:
                btn.setProperty("segment", "first")
            if i == len(options) - 1:
                btn.setProperty("segment", "last")
            btn.setChecked(i == current)
            self._group.addButton(btn, i)
            layout.addWidget(btn)
        self._group.idClicked.connect(self.selectionChanged.emit)

    def current(self) -> int:
        return self._group.checkedId()


# --- Status chip -------------------------------------------------------------------


class StatusChip(QLabel):
    """Stage status chip - the six states of PRD §4.0."""

    def __init__(self, status: str = "empty", parent: QWidget | None = None):
        super().__init__(parent)
        self.setProperty("chip", "true")
        self.set_status(status)

    def set_status(self, status: str) -> None:
        info = STAGE_STATUSES[status]
        self.setText(f"{info.glyph} {info.label}")
        self.setProperty("status", status)
        repolish(self)


# --- Banner (inline info/warn/error - never modal) -----------------------------------


class Banner(QFrame):
    """Inline banner. severity: info | warn | error. Follows the §6.5 message pattern."""

    def __init__(self, message: str, severity: str = "info", parent: QWidget | None = None):
        super().__init__(parent)
        self.setProperty("banner", severity)
        self.severity = severity
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        icon = {"info": "ℹ", "warn": "⚠", "error": "❌"}[severity]
        self._label = QLabel(f"{icon}  {message}")
        self._label.setWordWrap(True)
        layout.addWidget(self._label)

    def text(self) -> str:
        return self._label.text()


# --- Traffic-light metric row (checkMesh quality report, §4.3.3) -----------------------


class TrafficLightRow(QWidget):
    """One quality metric: name, value, pass/warn/fail light."""

    def __init__(self, name: str, value: str, verdict: str, parent: QWidget | None = None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)
        status = {"pass": "complete", "warn": "warnings", "fail": "invalid"}[verdict]
        glyph = {"pass": "●", "warn": "●", "fail": "●"}[verdict]
        light = QLabel(glyph)
        light.setProperty("status", status)
        name_label = QLabel(name)
        value_label = QLabel(value)
        value_label.setProperty("role", "caption")
        layout.addWidget(light)
        layout.addWidget(name_label, stretch=1)
        layout.addWidget(value_label)


# --- Collapsible "Advanced" group (progressive disclosure) ----------------------------


class CollapsibleGroup(QWidget):
    """Form group with a collapsible body, used for 'Advanced' sections."""

    def __init__(self, title: str = "Advanced", parent: QWidget | None = None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self._toggle = QToolButton()
        self._toggle.setText(f"▸ {title}")
        self._toggle.setCheckable(True)
        self._toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self._title = title
        self.body = QWidget()
        self.body.setVisible(False)
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(16, CONTROL_RHYTHM, 0, 0)
        self.body_layout.setSpacing(CONTROL_RHYTHM)
        outer.addWidget(self._toggle)
        outer.addWidget(self.body)
        self._toggle.toggled.connect(self._on_toggle)

    def _on_toggle(self, checked: bool) -> None:
        self.body.setVisible(checked)
        self._toggle.setText(f"{'▾' if checked else '▸'} {self._title}")


# --- Log view ---------------------------------------------------------------------------


class LogView(QPlainTextEdit):
    """Streaming log view: monospace, read-only, capped block count for jank-free streaming."""

    def __init__(self, max_lines: int = 100_000, parent: QWidget | None = None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setProperty("role", "log")
        self.setMaximumBlockCount(max_lines)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        font = QFont("JetBrains Mono")
        font.setStyleHint(QFont.StyleHint.Monospace)
        self.setFont(font)

    def append_line(self, line: str) -> None:
        self.appendPlainText(line.rstrip("\n"))


# --- Empty state -------------------------------------------------------------------------


class EmptyState(QWidget):
    """Icon, one sentence, one action (PRD §6.4)."""

    def __init__(self, icon: str, sentence: str, action: str, parent: QWidget | None = None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(CONTROL_RHYTHM * 2)
        icon_label = QLabel(icon)
        icon_label.setProperty("role", "title")
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        text = QLabel(sentence)
        text.setProperty("role", "caption")
        text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.action_button = make_button(action, variant="primary")
        layout.addWidget(icon_label)
        layout.addWidget(text)
        layout.addWidget(self.action_button, alignment=Qt.AlignmentFlag.AlignCenter)
