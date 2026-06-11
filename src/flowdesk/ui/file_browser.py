"""Case file browser & editor (PRD §4.9): the transparency surface.

Left: tree of the case directory. Right: editor with OpenFOAM syntax
highlighting. Ownership state is surfaced per file: managed / user-owned keys
(✎) / detached, driven by flowdesk.json.

Dev entry point: uv run flowdesk-files <case_dir>
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from PyQt6.QtCore import QDir, Qt
from PyQt6.QtGui import QColor, QFileSystemModel, QFont, QSyntaxHighlighter, QTextCharFormat
from PyQt6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPlainTextEdit,
    QSplitter,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from flowdesk.model.case import SIDECAR_NAME, CaseModel
from flowdesk.ui.components import Banner, make_button
from flowdesk.ui.theme import FONT_SIZE_MONO, SYNTAX_COLORS, apply_theme

MAX_EDITABLE_BYTES = 5 * 1024 * 1024  # §4.9: larger files open as summary view


class OpenFoamHighlighter(QSyntaxHighlighter):
    """Keywords, comments, numbers, strings, dimension sets, directives/macros."""

    RULES: list[tuple[re.Pattern[str], str]] = [
        (re.compile(r"\b(FoamFile|version|format|class|object|location)\b"), "keyword"),
        (re.compile(r"[+-]?\b\d+\.?\d*(?:[eE][+-]?\d+)?\b"), "number"),
        (re.compile(r"\[[\d\s+-]+\]"), "dimension"),
        (re.compile(r'"[^"]*"'), "string"),
        (re.compile(r"[#$]\w+"), "directive"),
        (re.compile(r"//[^\n]*"), "comment"),
    ]

    def __init__(self, document):
        super().__init__(document)
        self._formats: dict[str, QTextCharFormat] = {}
        for name, color in SYNTAX_COLORS.items():
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(color))
            self._formats[name] = fmt

    def highlightBlock(self, text: str) -> None:
        for pattern, name in self.RULES:
            for m in pattern.finditer(text):
                self.setFormat(m.start(), m.end() - m.start(), self._formats[name])
        # Block comments /* ... */ across lines
        self._block_comment(text)

    def _block_comment(self, text: str) -> None:
        fmt = self._formats["comment"]
        start = 0 if self.previousBlockState() == 1 else text.find("/*")
        while start >= 0:
            end = text.find("*/", start)
            if end < 0:
                self.setCurrentBlockState(1)
                self.setFormat(start, len(text) - start, fmt)
                return
            self.setFormat(start, end + 2 - start, fmt)
            start = text.find("/*", end + 2)
        self.setCurrentBlockState(0)


class FileBrowserWidget(QWidget):
    """Tree + editor with the ownership banner. Stateless against the model:
    re-reads flowdesk.json for ownership info on each file open."""

    def __init__(self, case_dir: Path, parent: QWidget | None = None):
        super().__init__(parent)
        self.case_dir = case_dir
        self._current: Path | None = None

        self._fs_model = QFileSystemModel(self)
        self._fs_model.setRootPath(str(case_dir))
        self._fs_model.setFilter(QDir.Filter.AllEntries | QDir.Filter.NoDotAndDotDot)

        self._tree = QTreeView()
        self._tree.setModel(self._fs_model)
        self._tree.setRootIndex(self._fs_model.index(str(case_dir)))
        for col in range(1, 4):  # name only; hide size/type/date
            self._tree.hideColumn(col)
        self._tree.setHeaderHidden(True)
        self._tree.clicked.connect(self._on_select)

        self._banner_slot = QVBoxLayout()
        self._editor = QPlainTextEdit()
        self._editor.setProperty("role", "log")
        font = QFont("JetBrains Mono")
        font.setStyleHint(QFont.StyleHint.Monospace)
        font.setPointSizeF(FONT_SIZE_MONO * 0.75)
        self._editor.setFont(font)
        self._editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self._highlighter = OpenFoamHighlighter(self._editor.document())

        self._save_btn = make_button("Save", "primary")
        self._save_btn.clicked.connect(self._save)
        self._save_btn.setEnabled(False)
        self._path_label = QLabel("Select a file")
        self._path_label.setProperty("role", "caption")

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        header = QHBoxLayout()
        header.addWidget(self._path_label, stretch=1)
        header.addWidget(self._save_btn)
        right_layout.addLayout(header)
        right_layout.addLayout(self._banner_slot)
        right_layout.addWidget(self._editor)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._tree)
        splitter.addWidget(right)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([260, 700])

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(splitter)

    # ------------------------------------------------------------------ slots

    def _on_select(self, index) -> None:
        path = Path(self._fs_model.filePath(index))
        if path.is_dir():
            return
        self.open_file(path)

    def open_file(self, path: Path) -> None:
        self._current = path
        rel = path.relative_to(self.case_dir).as_posix()
        self._path_label.setText(rel)
        self._clear_banners()

        read_only = path.name == SIDECAR_NAME
        if read_only:
            self._add_banner("flowdesk.json is FlowDesk's case model — read-only here. "
                             "Deleting it simply makes this a plain OpenFOAM case.", "info")

        if path.stat().st_size > MAX_EDITABLE_BYTES or _looks_binary(path):
            self._editor.setPlainText(_summary_header(path))
            self._editor.setReadOnly(True)
            self._save_btn.setEnabled(False)
            return

        self._editor.setPlainText(path.read_text(encoding="utf-8", errors="replace"))
        self._editor.setReadOnly(read_only)
        self._save_btn.setEnabled(not read_only)
        self._show_ownership(rel)

    def _show_ownership(self, rel: str) -> None:
        ownership = self._load_ownership()
        if ownership is None:
            return
        record = ownership.files.get(rel)
        if record is None:
            self._add_banner("Not managed by FlowDesk — edits here are entirely yours. ℹ",
                             "info")
            return
        if record.detached:
            self._add_banner(
                "Detached: FlowDesk no longer writes this file (it could not be parsed "
                "back). Revert to managed from the owning stage to reattach.", "warn")
        elif record.user_keys:
            keys = ", ".join(record.user_keys)
            self._add_banner(
                f"✎ User-owned keys: {keys} — set manually; FlowDesk will preserve them "
                "on every write.", "warn")
        else:
            self._add_banner("Managed by FlowDesk — manual edits will be detected and "
                             "preserved per-key on the next write.", "info")

    def _load_ownership(self):
        try:
            return CaseModel.load(self.case_dir).ownership
        except Exception:
            return None

    def _save(self) -> None:
        if self._current is None:
            return
        text = self._editor.toPlainText()
        if not text.endswith("\n"):
            text += "\n"
        self._current.write_text(text, encoding="utf-8", newline="\n")
        rel = self._current.relative_to(self.case_dir).as_posix()
        self._clear_banners()
        self._add_banner(f"Saved {rel}. FlowDesk will reconcile ownership on its next "
                         "write of this file.", "info")

    # ------------------------------------------------------------------ banners

    def _add_banner(self, message: str, severity: str) -> None:
        self._banner_slot.addWidget(Banner(message, severity))

    def _clear_banners(self) -> None:
        while self._banner_slot.count():
            item = self._banner_slot.takeAt(0)
            if item.widget():
                item.widget().deleteLater()


def _looks_binary(path: Path) -> bool:
    chunk = path.open("rb").read(2048)
    return b"\x00" in chunk


def _summary_header(path: Path) -> str:
    size = path.stat().st_size
    head = path.open("rb").read(4096).decode("utf-8", errors="replace")
    return (
        f"// {path.name}: {size:,} bytes - too large or binary; shown as summary "
        f"(not editable).\n\n{head}\n…"
    )


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: flowdesk-files <case_dir>")
        return 2
    case_dir = Path(sys.argv[1]).resolve()
    app = QApplication(sys.argv)
    apply_theme(app)
    window = QMainWindow()
    window.setWindowTitle(f"FlowDesk — Files: {case_dir.name}")
    window.resize(1100, 800)
    window.setCentralWidget(FileBrowserWidget(case_dir))
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
