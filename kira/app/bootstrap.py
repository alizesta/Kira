"""Application startup composition root.

The UI remains in its legacy module during the incremental migration. Keeping
construction here prevents the entry point from owning UI setup details.
"""
from __future__ import annotations

import sys


def run_application() -> None:
    from PySide6.QtWidgets import QApplication

    # The old window is retained temporarily while its features move into modules.
    from ..config import load_settings
    from .dependency_container import DependencyContainer
    from .event_bus import EventBus
    from ..chat.events import ChatEventPublisher
    from .module_manager import ModuleManager, ModuleState
    from ..oldmain import MainWindow
    from ..services import CharacterProfileService, PersonaMemoryService, MoodStateService, SqliteChatHistoryService
    from ..modules import ServiceModule
    from ..theme import build_style
    from .. import winfx

    container = DependencyContainer()
    event_bus = EventBus()
    chat_event_publisher = ChatEventPublisher(event_bus)
    module_manager = ModuleManager(container, event_bus)
    service_modules = (
        ("memory", "memory_service", PersonaMemoryService),
        ("mood", "mood_service", MoodStateService),
        ("characters", "character_service", CharacterProfileService),
        ("chat_history", "chat_history_service", SqliteChatHistoryService),
    )
    for module_id, service_key, factory in service_modules:
        module_manager.register(
            module_id,
            lambda key=service_key, service_factory=factory: ServiceModule(key, service_factory),
            optional=False,
        )
    states = module_manager.start_all()
    failed = {
        module_id: module_manager.error(module_id)
        for module_id, state in states.items()
        if state != ModuleState.STARTED
    }
    if failed:
        module_manager.shutdown()
        raise RuntimeError(f"Required application modules failed to start: {failed}")

    app = QApplication(sys.argv)
    app.setStyleSheet(build_style(winfx.active_effect(load_settings().get("window_effect"))))
    try:
        window = MainWindow(
            memory_service=container.resolve("memory_service"),
            mood_service=container.resolve("mood_service"),
            character_service=container.resolve("character_service"),
            chat_history_service=container.resolve("chat_history_service"),
            chat_event_publisher=chat_event_publisher,
        )
    except Exception:
        module_manager.shutdown()
        raise
    # Retain the composition root for the lifetime of the application.
    window._dependency_container = container
    window._event_bus = event_bus
    window._chat_event_publisher = chat_event_publisher
    window._module_manager = module_manager
    app.aboutToQuit.connect(module_manager.shutdown)
    app.aboutToQuit.connect(event_bus.close)
    window.show()
    sys.exit(app.exec())
