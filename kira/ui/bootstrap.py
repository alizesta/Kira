"""Desktop composition root: bind application services to Qt and the MainWindow."""
from __future__ import annotations

import sys

from ..core.interfaces.transfer import ChatTransferFilePort


def run_application(*, transfer_file_port: ChatTransferFilePort | None = None) -> None:
    from PySide6.QtWidgets import QApplication

    from .. import winfx
    from ..chat.events import ChatEventPublisher
    from ..chat.session_manager import SessionManager
    from ..chat_sessions import ChatSession
    from ..config import DATA_DIR, ROOT, load_settings
    from ..theme import build_style
    from ..tools import ToolAgent
    from .main_window import MainWindow
    from .main_window_composition import initialize_main_window
    from ..app.dependency_container import DependencyContainer
    from ..app.event_bus import EventBus
    from ..app.feature_modules import register_application_modules
    from ..app.module_manager import ModuleManager, ModuleState

    if transfer_file_port is None:
        from ..infrastructure.chat_transfer_file_adapter import LocalChatTransferFileAdapter

        transfer_file_port = LocalChatTransferFileAdapter()

    settings = load_settings()
    container = DependencyContainer()
    event_bus = EventBus()
    chat_event_publisher = ChatEventPublisher(event_bus)
    module_manager = ModuleManager(container, event_bus)
    module_ids = register_application_modules(
        module_manager,
        container,
        settings=settings,
        event_publisher=chat_event_publisher,
        transfer_file_port=transfer_file_port,
    )

    states = module_manager.start_all()
    failed = {
        module_id: module_manager.error(module_id)
        for module_id, state in states.items()
        if state != ModuleState.STARTED
    }
    if failed:
        module_manager.shutdown()
        event_bus.close()
        raise RuntimeError(f"Required application modules failed to start: {failed}")

    try:
        app = QApplication(sys.argv)
        app.setStyleSheet(build_style(winfx.active_effect(settings.get("window_effect"))))
        session_manager = SessionManager(ChatSession)
        tool_agent = ToolAgent(settings, DATA_DIR, ROOT)
        window = MainWindow()
        initialize_main_window(
            window,
            memory_service=container.resolve("memory_service"),
            mood_service=container.resolve("mood_service"),
            character_service=container.resolve("character_service"),
            chat_application_service_factory=container.resolve("chat_application_service_factory"),
            session_application_service_factory=container.resolve("session_application_service_factory"),
            web_search_service=container.resolve("web_search_service"),
            shared_skills_application_service=container.resolve("shared_skills_application_service"),
            conversation_organization_application_service=container.resolve(
                "conversation_organization_application_service"
            ),
            chat_search_application_service=container.resolve("chat_search_application_service"),
            chat_transfer_application_service=container.resolve("chat_transfer_application_service"),
            voice_application_service_factory=container.resolve("voice_application_service_factory"),
            game_mode_application_service=container.resolve("game_mode_application_service"),
            session_manager=session_manager,
            chat_event_publisher=chat_event_publisher,
            settings=settings,
            tool_agent=tool_agent,
            provider_application_service=container.resolve("provider_application_service"),
            coding_agent_application_service=container.resolve("coding_agent_application_service"),
            vision_application_service=container.resolve("vision_application_service"),
            runtime_settings_application_service=container.resolve("runtime_settings_application_service"),
        )
    except Exception:
        module_manager.shutdown()
        event_bus.close()
        raise

    window._dependency_container = container
    window._event_bus = event_bus
    window._chat_event_publisher = chat_event_publisher
    window._session_manager = session_manager
    window._module_manager = module_manager
    window._feature_module_ids = module_ids
    app.aboutToQuit.connect(module_manager.shutdown)
    app.aboutToQuit.connect(event_bus.close)
    window.show()
    sys.exit(app.exec())
