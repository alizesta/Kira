"""Desktop composition root: bind application services to Qt and the MainWindow."""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from time import perf_counter

from ..core.interfaces.transfer import ChatTransferFilePort


def _show_startup_splash(app):
    """Paint a lightweight native splash before importing the application graph."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
    from PySide6.QtWidgets import QSplashScreen

    pixmap = QPixmap(520, 180)
    pixmap.fill(QColor("#0A0A1C"))
    painter = QPainter(pixmap)
    painter.setPen(QColor("#E8E7FF"))
    title_font = QFont()
    title_font.setPointSize(22)
    title_font.setBold(True)
    painter.setFont(title_font)
    painter.drawText(0, 52, 520, 48, Qt.AlignmentFlag.AlignCenter, "KIRA")
    body_font = QFont()
    body_font.setPointSize(10)
    painter.setFont(body_font)
    painter.setPen(QColor("#A9A7D8"))
    painter.drawText(0, 104, 520, 28, Qt.AlignmentFlag.AlignCenter, "Starting your workspace...")
    painter.end()

    splash = QSplashScreen(pixmap, Qt.WindowType.WindowStaysOnTopHint)
    splash.show()
    app.processEvents()
    return splash


def _write_startup_metrics(data_dir: Path, phases: dict[str, dict[str, float]]) -> None:
    """Append one small, privacy-safe startup timing record for local diagnosis."""
    try:
        log_dir = Path(data_dir) / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        record = {
            "recorded_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "phases": phases,
            "total_ms": max((item["elapsed_ms"] for item in phases.values()), default=0.0),
        }
        with (log_dir / "startup-performance.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False) + "\\n")
    except OSError:
        # Diagnostics must never prevent the desktop application from starting.
        pass


def run_application(*, transfer_file_port: ChatTransferFilePort | None = None) -> None:
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("Kira")
    started_at = perf_counter()
    previous_mark = started_at
    phases: dict[str, dict[str, float]] = {}

    def mark_phase(name: str) -> None:
        nonlocal previous_mark
        now = perf_counter()
        phases[name] = {
            "elapsed_ms": round((now - started_at) * 1000, 2),
            "since_previous_ms": round((now - previous_mark) * 1000, 2),
        }
        previous_mark = now

    splash = _show_startup_splash(app)
    mark_phase("qt_ready_and_splash_visible")
    data_dir = None

    try:
        from ..chat.events import ChatEventPublisher
        from ..chat.session_manager import SessionManager
        from ..chat_sessions import ChatSession
        from ..config import DATA_DIR, ROOT, load_settings
        from ..tools import ToolAgent
        from .main_window import MainWindow
        from .main_window_composition import initialize_main_window
        from ..app.dependency_container import DependencyContainer
        from ..app.event_bus import EventBus
        from ..app.feature_modules import register_application_modules
        from ..app.module_manager import ModuleManager, ModuleState

        data_dir = DATA_DIR
        mark_phase("application_imports")

        if transfer_file_port is None:
            from ..infrastructure.chat_transfer_file_adapter import LocalChatTransferFileAdapter

            transfer_file_port = LocalChatTransferFileAdapter()

        settings = load_settings()
        mark_phase("settings_loaded")
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
        mark_phase("modules_registered")

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
        mark_phase("modules_started")

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
            initiative_application_service_factory=container.resolve("initiative_application_service_factory"),
            brain_application_service=container.resolve("brain_application_service"),
            reflection_application_service=container.resolve("reflection_application_service"),
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
        mark_phase("window_composed")
    except Exception:
        splash.close()
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
    splash.finish(window)
    mark_phase("window_shown")

    def record_interactive_startup() -> None:
        mark_phase("event_loop_first_tick")
        if data_dir is not None:
            _write_startup_metrics(data_dir, phases)

    QTimer.singleShot(0, record_interactive_startup)
    sys.exit(app.exec())
