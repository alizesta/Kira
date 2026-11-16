"""Application startup composition root.

The UI remains in its legacy module during the incremental migration. Keeping
construction here prevents the entry point from owning UI setup details.
"""
from __future__ import annotations

import sys


def run_application() -> None:
    from PySide6.QtWidgets import QApplication

    # Imports are intentionally delayed: main.py defines MainWindow and remains
    # the compatibility module until UI extraction is completed.
    from ..config import load_settings
    from ..main import MainWindow
    from ..theme import build_style
    from .. import winfx

    app = QApplication(sys.argv)
    app.setStyleSheet(build_style(winfx.active_effect(load_settings().get("window_effect"))))
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
