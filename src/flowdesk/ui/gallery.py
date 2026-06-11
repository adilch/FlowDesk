"""Living style gallery (M0 deliverable): every core component rendered with the theme.

Run with: uv run flowdesk-gallery
"""

from __future__ import annotations

import sys

from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QProgressBar,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from flowdesk.ui.components import (
    Banner,
    CollapsibleGroup,
    EmptyState,
    LogView,
    SegmentedControl,
    StatusChip,
    TrafficLightRow,
    UnitLineEdit,
    Vec3Input,
    make_button,
)
from flowdesk.ui.theme import GROUP_GAP, PANEL_PADDING, STAGE_STATUSES, apply_theme


def _section(title: str) -> QLabel:
    label = QLabel(title.upper())
    label.setProperty("role", "section")
    return label


class GalleryWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("FlowDesk — Style Gallery")
        self.resize(900, 800)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        root = QVBoxLayout(content)
        margin = PANEL_PADDING * 2
        root.setContentsMargins(margin, margin, margin, margin)
        root.setSpacing(GROUP_GAP)

        title = QLabel("FlowDesk design system")
        title.setProperty("role", "title")
        root.addWidget(title)

        # Buttons
        root.addWidget(_section("Buttons"))
        buttons = QHBoxLayout()
        for variant in ("primary", "secondary", "ghost", "danger"):
            buttons.addWidget(make_button(variant.capitalize(), variant))
        buttons.addStretch()
        root.addLayout(buttons)

        # Inputs
        root.addWidget(_section("Numeric with unit / vec3"))
        grid = QGridLayout()
        grid.addWidget(QLabel("Target cell size"), 0, 0)
        grid.addWidget(UnitLineEdit(unit="m", value=0.05, minimum=0.0), 0, 1)
        grid.addWidget(QLabel("Inlet velocity"), 1, 0)
        grid.addWidget(UnitLineEdit(unit="m/s", value=2.0), 1, 1)
        grid.addWidget(QLabel("Domain min"), 2, 0)
        grid.addWidget(Vec3Input(unit="m", value=(-1.0, -1.0, 0.0)), 2, 1)
        grid.setColumnStretch(1, 1)
        root.addLayout(grid)
        hint = QLabel("Try typing '200 mm' into a length field — it normalizes to SI.")
        hint.setProperty("role", "caption")
        root.addWidget(hint)

        # Dropdown, segmented, checkbox
        root.addWidget(_section("Dropdown / segmented / checkbox"))
        row = QHBoxLayout()
        combo = QComboBox()
        combo.addItems(["k-ω SST", "k-ε", "Laminar"])
        row.addWidget(combo)
        row.addWidget(SegmentedControl(["Steady", "Transient"]))
        row.addWidget(QCheckBox("Make boundary layers"))
        row.addStretch()
        root.addLayout(row)

        # Status chips
        root.addWidget(_section("Stage status chips"))
        chips = QHBoxLayout()
        for key in STAGE_STATUSES:
            chips.addWidget(StatusChip(key))
        chips.addStretch()
        root.addLayout(chips)

        # Banners
        root.addWidget(_section("Banners"))
        root.addWidget(Banner("Found OpenFOAM v2506 in WSL distro Ubuntu-24.04.", "info"))
        root.addWidget(
            Banner(
                "Geometry is 1200 m across. Was it exported in mm? → Geometry → "
                "Apply a scale preset. [Fix scale]",
                "warn",
            )
        )
        root.addWidget(
            Banner(
                "Inlet velocity not set on patch 'inlet'. → Boundary Conditions → "
                "Set a velocity or change the BC type. [Go to patch]",
                "error",
            )
        )

        # Traffic-light quality report
        root.addWidget(_section("checkMesh quality report"))
        root.addWidget(TrafficLightRow("Max non-orthogonality", "58.3", "pass"))
        root.addWidget(TrafficLightRow("Max skewness", "5.1", "warn"))
        root.addWidget(TrafficLightRow("Negative-volume cells", "2", "fail"))

        # Table
        root.addWidget(_section("Editable table"))
        table = QTableWidget(2, 3)
        table.setHorizontalHeaderLabels(["Surface", "Level min–max", "Layers"])
        for r, (name, lvl, lay) in enumerate([("weir", "2–3", "3"), ("ground", "1–2", "off")]):
            table.setItem(r, 0, QTableWidgetItem(name))
            table.setItem(r, 1, QTableWidgetItem(lvl))
            table.setItem(r, 2, QTableWidgetItem(lay))
        table.setMaximumHeight(120)
        root.addWidget(table)

        # Progress + collapsible
        root.addWidget(_section("Progress / advanced disclosure"))
        bar = QProgressBar()
        bar.setValue(62)
        root.addWidget(bar)
        adv = CollapsibleGroup("Advanced")
        adv.body_layout.addWidget(QLabel("nSmoothPatch, tolerance, nSolveIter…"))
        root.addWidget(adv)

        # Log view
        root.addWidget(_section("Log view"))
        log = LogView()
        log.setMaximumHeight(140)
        for line in (
            "Create mesh for time = 0",
            "Time = 100",
            "smoothSolver:  Solving for Ux, Initial residual = 0.00123",
            "GAMG:  Solving for p, Initial residual = 0.0456",
            "bounding k, min: 0 max: 1.2 average: 0.05",
        ):
            log.append_line(line)
        root.addWidget(log)

        # Empty state
        root.addWidget(_section("Empty state"))
        root.addWidget(EmptyState("📐", "No geometry imported yet.", "Import STL…"))

        scroll.setWidget(content)
        self.setCentralWidget(scroll)


def main() -> int:
    app = QApplication(sys.argv)
    apply_theme(app)
    window = GalleryWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
