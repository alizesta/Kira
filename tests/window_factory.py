"""Test factory that builds a fully composed MainWindow the way production does.

``MainWindow()`` is only the Qt shell; ``kira.ui.bootstrap.run_application``
creates the shared services and then calls ``initialize_main_window``. GUI
tests that build a bare ``MainWindow()`` never get that second step and fail on
the first ``show()``. ``make_window`` repeats the bootstrap wiring without
creating a QApplication or entering the event loop.

Keep this in step with ``kira/ui/bootstrap.py``; ``test_composition_root_contract``
pins that file to a single ``MainWindow()`` call, so the wiring is mirrored here
instead of being factored out of production code.
"""
from __future__ import annotations


def _no_audio_devices():
    """Headless CI has no audio server and Qt Multimedia can segfault while enumerating devices."""
    from contextlib import ExitStack
    from unittest import mock

    stack = ExitStack()
    try:
        from PySide6.QtMultimedia import QMediaDevices
    except ImportError:
        return stack
    for name in ("audioOutputs", "audioInputs"):
        stack.enter_context(mock.patch.object(QMediaDevices, name, staticmethod(lambda: []), create=True))
    return stack


def make_window():
    """Return a composed (not yet shown) MainWindow with its services attached."""
    with _no_audio_devices():
        return _make_window()


def _make_window():
    from kira import config
    from kira.app.dependency_container import DependencyContainer
    from kira.app.event_bus import EventBus
    from kira.app.feature_modules import register_application_modules
    from kira.app.module_manager import ModuleManager, ModuleState
    from kira.chat.events import ChatEventPublisher
    from kira.chat.session_manager import SessionManager
    from kira.chat_sessions import ChatSession
    from kira.infrastructure.chat_transfer_file_adapter import LocalChatTransferFileAdapter
    from kira.tools import ToolAgent
    from kira.ui.main_window import MainWindow
    from kira.ui.main_window_composition import initialize_main_window

    settings = config.load_settings()
    container = DependencyContainer()
    event_bus = EventBus()
    publisher = ChatEventPublisher(event_bus)
    module_manager = ModuleManager(container, event_bus)
    module_ids = register_application_modules(
        module_manager,
        container,
        settings=settings,
        event_publisher=publisher,
        transfer_file_port=LocalChatTransferFileAdapter(),
    )
    states = module_manager.start_all()
    failed = {m: module_manager.error(m) for m, s in states.items() if s != ModuleState.STARTED}
    if failed:
        module_manager.shutdown()
        event_bus.close()
        raise RuntimeError(f"Required application modules failed to start: {failed}")

    session_manager = SessionManager(ChatSession)
    tool_agent = ToolAgent(settings, config.DATA_DIR, config.ROOT)
    window = MainWindow()
    r = container.resolve
    initialize_main_window(
        window,
        memory_service=r("memory_service"),
        mood_service=r("mood_service"),
        character_service=r("character_service"),
        chat_application_service_factory=r("chat_application_service_factory"),
        session_application_service_factory=r("session_application_service_factory"),
        initiative_application_service_factory=r("initiative_application_service_factory"),
        brain_application_service=r("brain_application_service"),
        reflection_application_service=r("reflection_application_service"),
        web_search_service=r("web_search_service"),
        shared_skills_application_service=r("shared_skills_application_service"),
        conversation_organization_application_service=r("conversation_organization_application_service"),
        chat_search_application_service=r("chat_search_application_service"),
        chat_transfer_application_service=r("chat_transfer_application_service"),
        voice_application_service_factory=r("voice_application_service_factory"),
        game_mode_application_service=r("game_mode_application_service"),
        session_manager=session_manager,
        chat_event_publisher=publisher,
        settings=settings,
        tool_agent=tool_agent,
        provider_application_service=r("provider_application_service"),
        coding_agent_application_service=r("coding_agent_application_service"),
        vision_application_service=r("vision_application_service"),
        runtime_settings_application_service=r("runtime_settings_application_service"),
    )
    window._dependency_container = container
    window._event_bus = event_bus
    window._chat_event_publisher = publisher
    window._session_manager = session_manager
    window._module_manager = module_manager
    window._feature_module_ids = module_ids
    return window
