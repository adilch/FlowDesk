"""M0 spike: pyvistaqt inside PyQt6 - load an STL, spin it, report FPS.

Gate: "STL spins at 60 fps in the widget."

Usage:  uv run python spikes/viewer_spike.py [path/to/file.stl] [--seconds N]
If no STL is given, a ~100k-triangle test sphere is generated on the fly.
--seconds N auto-quits after N seconds (for unattended verification).
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pyvista as pv
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication, QLabel, QMainWindow, QVBoxLayout, QWidget

from flowdesk.ui.theme import apply_theme
from flowdesk.ui.viewer import ViewerWidget


def make_test_stl(path: Path) -> Path:
    sphere = pv.Sphere(theta_resolution=220, phi_resolution=220)  # ~96k triangles
    sphere.save(str(path))
    return path


class SpikeWindow(QMainWindow):
    def __init__(self, stl_path: Path):
        super().__init__()
        self.setWindowTitle("FlowDesk — viewer spike")
        self.resize(1000, 750)

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        self.viewer = ViewerWidget()
        self.fps_label = QLabel("FPS: —")
        self.fps_label.setProperty("role", "caption")
        layout.addWidget(self.viewer, stretch=1)
        layout.addWidget(self.fps_label)
        self.setCentralWidget(central)

        mesh = self.viewer.load_surface(stl_path)
        self.fps_label.setText(f"FPS: — | {mesh.n_cells:,} triangles | spinning…")

        # Spin the camera and measure wall-clock frame rate.
        self._frames = 0
        self._t0 = time.perf_counter()
        self._spin = QTimer(self)
        self._spin.timeout.connect(self._rotate)
        self._spin.start(0)  # render as fast as the event loop allows

        self._report = QTimer(self)
        self._report.timeout.connect(self._report_fps)
        self._report.start(1000)
        self._n_cells = mesh.n_cells

    def _rotate(self) -> None:
        self.viewer.plotter.camera.azimuth = self.viewer.plotter.camera.azimuth + 1
        self.viewer.plotter.render()
        self._frames += 1

    def _report_fps(self) -> None:
        elapsed = time.perf_counter() - self._t0
        fps = self._frames / elapsed if elapsed > 0 else 0.0
        self.fps_label.setText(f"FPS: {fps:5.1f} | {self._n_cells:,} triangles | spinning")
        print(f"FPS: {fps:5.1f}")
        self._frames = 0
        self._t0 = time.perf_counter()


def main() -> int:
    args = sys.argv[1:]
    seconds = 0
    if "--seconds" in args:
        i = args.index("--seconds")
        seconds = int(args[i + 1])
        del args[i : i + 2]

    app = QApplication(sys.argv)
    apply_theme(app)
    if args:
        stl = Path(args[0])
    else:
        stl = make_test_stl(Path(__file__).parent / "_test_sphere.stl")
        print(f"Generated test STL: {stl}")
    window = SpikeWindow(stl)
    window.show()
    if seconds:
        QTimer.singleShot(seconds * 1000, app.quit)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
