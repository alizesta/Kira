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
    from .event_bus import EventBus
    from .module_manager import ModuleManager
    from ..main import MainWindow
    from ..services import CharacterProfileService, PersonaMemoryService, MoodStateService
    from ..theme import build_style
    from .. import winfx

    container = DependencyContainer()
    container.register_factory("memory_service", PersonaMemoryService)
    container.register_factory("mood_service", MoodStateService)
    container.register_factory("character_service", CharacterProfileService)
    event_bus = EventBus()
    module_manager = ModuleManager(container, event_bus)

    app = QApplication(sys.argv)
    app.setStyleSheet(build_style(winfx.active_effect(load_settings().get("window_effect"))))
    window = MainWindow(
        memory_service=container.resolve("memory_service"),
        mood_service=container.resolve("mood_service"),
        character_service=container.resolve("character_service"),
    )
    # Retain the composition root for the lifetime of the application.
    window._dependency_container = container
    window._event_bus = event_bus
    window._module_manager = module_manager
    app.aboutToQuit.connect(module_manager.shutdown)
    window.show()
    sys.exit(app.exec())
