"""Desktop composition root: bind application services to Qt and the MainWindow."""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from time import perf_counter

from ..core.interfaces.transfer import ChatTransferFilePort
from ..lazy_tool_agent import LazyToolAgent


def _create_tool_agent(settings, data_dir, program_root):
    """Import the Windows tool stack only when Kira first needs a PC capability."""
    from ..tools import ToolAgent

    return ToolAgent(settings, data_dir, program_root)


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


def _write_startup_metrics(
    data_dir: Path,
    phases: dict[str, dict[str, float]],
    memory_samples: dict[str, dict[str, float]] | None = None,
) -> None:
    """Append startup timing and process-memory samples without user content."""
    try:
        log_dir = Path(data_dir) / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        record = {
            "schema_version": 2,
            "recorded_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "phases": phases,
            "total_ms": max((item["elapsed_ms"] for item in phases.values()), default=0.0),
            "memory_samples": memory_samples or {},
        }
        with (log_dir / "startup-performance.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        # Diagnostics must never prevent the desktop application from starting.
        pass


def _process_memory_snapshot() -> dict[str, float] | None:
    """Sample process memory without adding a third-party dependency."""
    try:
        if sys.platform == "win32":
            import ctypes
            from ctypes import wintypes

            size_t = ctypes.c_size_t

            class ProcessMemoryCountersEx(ctypes.Structure):
                _fields_ = [
                    ("cb", wintypes.DWORD),
                    ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", size_t),
                    ("WorkingSetSize", size_t),
                    ("QuotaPeakPagedPoolUsage", size_t),
                    ("QuotaPagedPoolUsage", size_t),
                    ("QuotaPeakNonPagedPoolUsage", size_t),
                    ("QuotaNonPagedPoolUsage", size_t),
                    ("PagefileUsage", size_t),
                    ("PeakPagefileUsage", size_t),
                    ("PrivateUsage", size_t),
                ]

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            psapi = ctypes.WinDLL("psapi", use_last_error=True)
            kernel32.GetCurrentProcess.restype = wintypes.HANDLE
            get_memory = psapi.GetProcessMemoryInfo
            get_memory.argtypes = (
                wintypes.HANDLE,
                ctypes.POINTER(ProcessMemoryCountersEx),
                wintypes.DWORD,
            )
            get_memory.restype = wintypes.BOOL
            counters = ProcessMemoryCountersEx()
            counters.cb = ctypes.sizeof(counters)
            if not get_memory(
                kernel32.GetCurrentProcess(),
                ctypes.byref(counters),
                counters.cb,
            ):
                return None
            to_mb = 1024.0 * 1024.0
            return {
                "working_set_mb": round(counters.WorkingSetSize / to_mb, 2),
                "peak_working_set_mb": round(counters.PeakWorkingSetSize / to_mb, 2),
                "private_bytes_mb": round(counters.PrivateUsage / to_mb, 2),
            }

        import resource

        peak_rss = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        divisor = 1024.0 * 1024.0 if sys.platform == "darwin" else 1024.0
        return {"peak_rss_mb": round(peak_rss / divisor, 2)}
    except Exception:  # noqa: BLE001 - diagnostics must never block application startup
        return None




def run_application(*, transfer_file_port: ChatTransferFilePort | None = None) -> None:
    from PySide6.QtCore import QTimer, Qt
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("Kira")
    try:                                                    # application / taskbar / dialog icon: Kira's face
        from PySide6.QtGui import QIcon
        icon_path = Path(__file__).resolve().parents[2] / "assets" / "kira_icon.png"
        if icon_path.is_file():
            app.setWindowIcon(QIcon(str(icon_path)))
    except Exception:                                       # noqa: BLE001 - an icon must never block start-up
        pass
    try:                                                    # Vazirmatn (SIL OFL): calm, readable Persian/Latin text for long chats
        from PySide6.QtGui import QFont, QFontDatabase
        fonts_dir = Path(__file__).resolve().parents[2] / "assets" / "fonts"
        loaded = [QFontDatabase.addApplicationFont(str(f)) for f in sorted(fonts_dir.glob("Vazirmatn-*.ttf"))]
        if any(index >= 0 for index in loaded):
            app.setFont(QFont("Vazirmatn", 10))
    except Exception:                                       # noqa: BLE001 - a font must never block start-up
        pass
    started_at = perf_counter()
    previous_mark = started_at
    phases: dict[str, dict[str, float]] = {}
    memory_samples: dict[str, dict[str, float]] = {}

    def mark_phase(name: str) -> None:
        nonlocal previous_mark
        now = perf_counter()
        phases[name] = {
            "elapsed_ms": round((now - started_at) * 1000, 2),
            "since_previous_ms": round((now - previous_mark) * 1000, 2),
        }
        previous_mark = now
        memory_snapshot = _process_memory_snapshot()
        if memory_snapshot:
            memory_samples[name] = memory_snapshot
        progress_labels = {
            "application_imports": "Loading application modules...",
            "settings_loaded": "Loading your settings...",
            "modules_registered": "Preparing services...",
            "modules_started": "Starting services...",
            "window_composed": "Building your workspace...",
        }
        splash.showMessage(
            progress_labels.get(name, "Starting your workspace..."),
            Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter,
            QColor("#A9A7D8"),
        )
        app.processEvents()

    splash = _show_startup_splash(app)
    from .console_log import ConsoleLogCapture
    console_log_capture = ConsoleLogCapture()
    console_log_capture.install()
    mark_phase("qt_ready_and_splash_visible")
    data_dir = None

    try:
        from ..chat.events import ChatEventPublisher
        from ..chat.session_manager import SessionManager
        from ..chat_sessions import ChatSession
        from ..config import DATA_DIR, ROOT, load_settings
        from .main_window import MainWindow
        from ..app.dependency_container import DependencyContainer
        from ..app.event_bus import EventBus
        from ..app.feature_modules import (
            REQUIRED_APPLICATION_MODULES,
            register_application_modules,
        )
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
        required_failed = {
            module_id: error for module_id, error in failed.items()
            if module_id in REQUIRED_APPLICATION_MODULES
        }
        optional_failed = {
            module_id: error for module_id, error in failed.items()
            if module_id not in REQUIRED_APPLICATION_MODULES
        }
        if optional_failed:
            logging.getLogger("kira.bootstrap").warning(
                "Optional application modules did not start: %s", optional_failed
            )
        if required_failed:
            raise RuntimeError(
                f"Required application modules failed to start: {required_failed}"
            )
        mark_phase("modules_started")

        session_manager = SessionManager(ChatSession)
        tool_agent = LazyToolAgent(
            lambda: _create_tool_agent(settings, DATA_DIR, ROOT),
            data_dir=DATA_DIR,
        )
        tool_agent.set_settings(settings)
        window = MainWindow()
        from ..app.vision_runtime import VisionRuntimeProvider, VisionRuntimeServices
        from .main_window_composition import initialize_main_window

        def build_vision_runtime():
            from .vision_frame_codec import QtVisionFrameCodec, GeminiLiveTransportAdapter
            from .perception_worker_controller import PerceptionWorkerController
            from ..request_trace import vision_trace
            from ..gemini_live import MAX_VIDEO_FRAME_BYTES

            context = window.presentation_context
            runtime_controller = context.controllers.require("runtime")
            frame_codec = QtVisionFrameCodec()
            transport = GeminiLiveTransportAdapter(
                readiness=runtime_controller.is_gemini_live_ready,
                clear_frames=runtime_controller.clear_gemini_video_frames,
                send_frame=runtime_controller.send_gemini_video_frame,
            )
            runtime = VisionRuntimeServices(
                game_mode_adapter=context.adapters.game_mode,
                game_mode_application_service=context.services.game_mode_application_service,
                vision_application_service=context.services.vision_application_service,
                desktop_context_application_service=context.services.desktop_context_application_service,
                settings=context.services.settings,
                frame_codec=frame_codec,
                live_transport=transport,
                max_frame_bytes_provider=lambda: MAX_VIDEO_FRAME_BYTES,
                trace=vision_trace,
            )
            context.adapters.perception_worker_controller = PerceptionWorkerController(
                runtime.perception_application_service,
                frame_codec,
                context.services.settings,
                is_closing=lambda: bool(context.state._closing),
                game_mode_enabled=lambda: bool(context.state._game_mode_enabled),
                trace=vision_trace,
                parent=window,
            )
            return runtime

        vision_runtime_provider = VisionRuntimeProvider(build_vision_runtime)
        initialize_main_window(
            window,
            vision_runtime_provider=vision_runtime_provider,
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
            desktop_context_application_service=container.resolve("desktop_context_application_service"),
            runtime_settings_application_service=container.resolve("runtime_settings_application_service"),
            console_log_capture=console_log_capture,
        )
        mark_phase("window_composed")
    except Exception:
        if "module_manager" in locals():
            module_manager.shutdown()
        if "event_bus" in locals():
            event_bus.close()
        console_log_capture.restore()
        splash.close()
        raise

    window._dependency_container = container
    window._event_bus = event_bus
    window._chat_event_publisher = chat_event_publisher
    window._session_manager = session_manager
    window._module_manager = module_manager
    window._feature_module_ids = module_ids
    window._console_log_capture = console_log_capture
    app.aboutToQuit.connect(console_log_capture.restore)
    app.aboutToQuit.connect(module_manager.shutdown)
    app.aboutToQuit.connect(event_bus.close)
    if os.environ.pop("KIRA_AUTOSTART", "") == "1" and getattr(window.presentation_context.views, "tray", None) is not None:
        # Launched by Windows at login: stay out of the way (tray + companion only).
        try:
            window.feature_controller("lifecycle").hide_to_tray()
            splash.close()
        except Exception:  # noqa: BLE001 - if hiding fails, show the window normally
            window.show()
            splash.finish(window)
    else:
        window.show()
        window.repaint()
        splash.finish(window)
    mark_phase("window_shown")

    def record_interactive_startup() -> None:
        mark_phase("event_loop_first_tick")
        if data_dir is not None:
            _write_startup_metrics(data_dir, phases, memory_samples)

    QTimer.singleShot(0, record_interactive_startup)
    sys.exit(app.exec())
