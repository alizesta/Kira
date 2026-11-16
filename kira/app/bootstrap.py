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
    from .dependency_container import DependencyContainer
    from ..main import MainWindow
    from ..services import PersonaMemoryService, MoodStateService
    from ..theme import build_style
    from .. import winfx

    container = DependencyContainer()
    container.register_factory("memory_service", PersonaMemoryService)
    container.register_factory("mood_service", MoodStateService)

    app = QApplication(sys.argv)
    app.setStyleSheet(build_style(winfx.active_effect(load_settings().get("window_effect"))))
    window = MainWindow(
        memory_service=container.resolve("memory_service"),
        mood_service=container.resolve("mood_service"),
    )
    # Retain the composition root for the lifetime of the application.
    window._dependency_container = container
    window.show()
    sys.exit(app.exec())
