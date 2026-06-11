"""Coach marks (PRD §5.3): a 6-step dismissible overlay on the cavity tutorial.

The only onboarding in the app; never repeats unless asked (AppSettings flag).
The 15-minute promise must survive without it.
"""

from __future__ import annotations

from PyQt6.QtCore import QEvent, pyqtSignal
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from flowdesk.ui.components import make_button

CAVITY_STEPS: list[tuple[str, str]] = [
    ("Welcome to FlowDesk",
     "This is the lid-driven cavity — a complete, runnable case. The rail on "
     "the left is the whole workflow, top to bottom."),
    ("1 · Geometry",
     "This template needs no STL (it's a pure box case). For real projects, "
     "import STL surfaces here and FlowDesk checks them for you."),
    ("2 · Mesh",
     "Generate Mesh runs the OpenFOAM meshing chain and reports quality as "
     "traffic lights. Click it now if you like — this case meshes in seconds."),
    ("3-5 · Physics, BCs, Numerics",
     "All pre-filled by the template. Every control maps to a standard "
     "OpenFOAM dictionary entry — hover any field to see which."),
    ("6 · Run",
     "Run starts the solver (detached — it survives FlowDesk closing) with "
     "live residuals. Stop is graceful; the case stays valid."),
    ("7 · Results — and the files",
     "Slice and probe results here, or Open in ParaView. Everything FlowDesk "
     "wrote is a plain OpenFOAM file: open the case folder and look."),
]


class CoachMarks(QFrame):
    """A floating card stepping through (title, text) pairs. Dismissible at
    every step; emits finished() on Done or Skip."""

    finished = pyqtSignal()

    def __init__(self, steps: list[tuple[str, str]] | None = None,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.steps = steps or CAVITY_STEPS
        self._index = 0
        self.setProperty("card", "true")
        self.setFixedWidth(360)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        self.title = QLabel("")
        self.title.setProperty("role", "title")
        self.text = QLabel("")
        self.text.setWordWrap(True)
        self.counter = QLabel("")
        self.counter.setProperty("role", "caption")

        buttons = QHBoxLayout()
        self.skip_btn = make_button("Skip tour", "ghost")
        self.skip_btn.clicked.connect(self._finish)
        self.next_btn = make_button("Next", "primary")
        self.next_btn.clicked.connect(self._next)
        buttons.addWidget(self.skip_btn)
        buttons.addStretch()
        buttons.addWidget(self.counter)
        buttons.addWidget(self.next_btn)

        layout.addWidget(self.title)
        layout.addWidget(self.text)
        layout.addLayout(buttons)
        self._show_step()

    def _show_step(self) -> None:
        title, text = self.steps[self._index]
        self.title.setText(title)
        self.text.setText(text)
        self.counter.setText(f"{self._index + 1}/{len(self.steps)}")
        self.next_btn.setText("Done" if self._index == len(self.steps) - 1 else "Next")

    def _next(self) -> None:
        if self._index >= len(self.steps) - 1:
            self._finish()
            return
        self._index += 1
        self._show_step()

    def _finish(self) -> None:
        self.finished.emit()
        self.hide()
        self.deleteLater()

    def pin_to(self, host: QWidget) -> None:
        """Float in the host's top-right corner."""
        self.setParent(host)
        self.move(host.width() - self.width() - 24, 48)
        self.raise_()
        self.show()
        host.installEventFilter(self)
        self._host = host

    def eventFilter(self, obj, event) -> bool:
        if obj is getattr(self, "_host", None) and event.type() == QEvent.Type.Resize:
            self.move(obj.width() - self.width() - 24, 48)
        return False


def maybe_show_tutorial(shell: QWidget, settings, template: str) -> CoachMarks | None:
    """Show the cavity coach marks once ever (per §5.3), only on the tutorial."""
    if template != "Lid-driven cavity" or settings.coach_done:
        return None
    marks = CoachMarks()
    marks.pin_to(shell)

    def done() -> None:
        settings.coach_done = True
        settings.save()

    marks.finished.connect(done)
    return marks
