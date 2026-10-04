"""Application entry point: ``dronecalc-gui`` or ``python -m dronecalc.ui``."""

from __future__ import annotations

import sys

import pyqtgraph as pg
from PySide6.QtWidgets import QApplication

from dronecalc.ui.main_window import MainWindow
from dronecalc.ui.state import AppState


def create_window(custom_dir=None, interactive: bool = False) -> MainWindow:
    """Build the main window (used by ``main`` and by tests)."""
    pg.setConfigOptions(antialias=True)
    return MainWindow(AppState(custom_dir=custom_dir), interactive=interactive)


def main(argv: list[str] | None = None) -> int:
    app = QApplication.instance() or QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("DroneCalc")
    window = create_window(interactive=True)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
