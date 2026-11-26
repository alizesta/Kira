"""Composition of the desktop window and its UI feature adapters.

This module owns widget/service assembly. MainWindow is the Qt shell and controller registry; application services
receive typed ports, never the window.
"""
from __future__ import annotations

import logging
import sys


def initialize_main_window(
    window,
    memory_service=None,
    mood_service=None,
    character_service=None,
    session_manager=None,
    chat_event_publisher=None,
    chat_application_service_factory=None,
    session_application_service_factory=None,
    web_search_service=None,
    voice_application_service_factory=None,
    game_mode_application_service=None,
    settings=None,
    tool_agent=None,
    provider_application_service=None,
    coding_agent_application_service=None,
    vision_application_service=None,
    vision_runtime_provider=None,
    desktop_context_application_service=None,
    runtime_settings_application_service=None,
    shared_skills_application_service=None,
    conversation_organization_application_service=None,
    chat_search_application_service=None,
    chat_transfer_application_service=None,
    initiative_application_service_factory=None,
    brain_application_service=None,
    reflection_application_service=None,
    console_log_capture=None,
):
    """Build UI widgets and bind injected services to typed Qt callback adapters."""
    from PySide6.QtWidgets import QApplication

    from .shortcuts import install_window_shortcuts
    from .motion_manager import MotionManager
    from .console_log import build_console_log_page
    from .lazy_game_mode_monitor import LazyGameModeMonitor
    from .lazy_speaker import LazySpeaker
    from .main_window_root_support import (
        AttachmentTile,
        ChatAttachmentController,
        CompanionBubble,
        CompanionWindow,
        EmotionDirector,
        EmotionFaceAnimator,
        LOAD_WARNINGS,
        QFrame,
        QHBoxLayout,
        QMenu,
        QPushButton,
        QSize,
        QTabWidget,
        QTimer,
        QToolButton,
        QVBoxLayout,
        QWidget,
        Qt,
        att,
        load_reactions,
        make_icon,
        winfx,
    )
    from .application_adapters import (
        create_chat_application_ports,
        create_voice_application_ports,
    )
    self = window.presentation_context
    # Application services are constructed and lifecycle-managed by the outer UI Composition Root.
    # This module is only the outer Qt/UI adapter composition boundary.
    required = {
        "memory_service": memory_service,
        "mood_service": mood_service,
        "character_service": character_service,
        "chat_event_publisher": chat_event_publisher,
        "chat_application_service_factory": chat_application_service_factory,
        "session_manager": session_manager,
        "session_application_service_factory": session_application_service_factory,
        "web_search_service": web_search_service,
        "voice_application_service_factory": voice_application_service_factory,
        "game_mode_application_service": game_mode_application_service,
        "settings": settings,
        "provider_application_service": provider_application_service,
        "coding_agent_application_service": coding_agent_application_service,
        "vision_application_service": vision_application_service,
        "vision_runtime_provider": vision_runtime_provider,
        "desktop_context_application_service": desktop_context_application_service,
        "runtime_settings_application_service": runtime_settings_application_service,
        "shared_skills_application_service": shared_skills_application_service,
        "conversation_organization_application_service": conversation_organization_application_service,
        "chat_search_application_service": chat_search_application_service,
        "chat_transfer_application_service": chat_transfer_application_service,
        "initiative_application_service_factory": initiative_application_service_factory,
        "brain_application_service": brain_application_service,
        "reflection_application_service": reflection_application_service,
        "tool_agent": tool_agent,
    }
    missing = tuple(name for name, value in required.items() if value is None)
    if missing:
        raise TypeError("MainWindow composition requires Bootstrap dependencies: " + ", ".join(missing))
    # Icons are cached per glow level: use the saved level before the first widget is built, otherwise every icon
    # is painted once at the default level and a second time when apply_appearance() sets the real one.
    try:
        from ..ui_icons import set_glow_intensity
        set_glow_intensity(float((settings.get("appearance") or {}).get("glow", 58)) / 100.0)
    except (TypeError, ValueError, AttributeError):
        pass
    self.services.memory_service = memory_service
    self.services.mood_service = mood_service
    self.services.character_service = character_service
    if not callable(chat_application_service_factory):
        raise TypeError("chat_application_service_factory must be callable")
    self.services.chat_application_service = chat_application_service_factory(create_chat_application_ports(self))
    if not callable(initiative_application_service_factory):
        raise TypeError("initiative_application_service_factory must be callable")
    self.services.initiative_application_service = initiative_application_service_factory(
        self.services.chat_application_service
    )
    self.services.brain_application_service = brain_application_service
    self.services.reflection_application_service = reflection_application_service
    self.services.web_search_service = web_search_service
    self.services.game_mode_application_service = game_mode_application_service
    self.services.settings = settings
    self.services.provider_application_service = provider_application_service
    self.services.runtime_settings_application_service = runtime_settings_application_service
    self.services.shared_skills_application_service = shared_skills_application_service
    self.services.conversation_organization_application_service = conversation_organization_application_service
    self.services.chat_search_application_service = chat_search_application_service
    self.services.chat_transfer_application_service = chat_transfer_application_service
    self.services.runtime_settings_application_service.configure(self.services.settings)
    self.services.coding_agent_application_service = coding_agent_application_service
    self.services.vision_application_service = vision_application_service
    self.services.vision_runtime_provider = vision_runtime_provider
    self.services.desktop_context_application_service = desktop_context_application_service
    self.state._db_notes = self.services.chat_application_service.init_history()
    self.services.session_manager = session_manager
    self.services.chat_event_publisher = chat_event_publisher
    if not callable(session_application_service_factory):
        raise TypeError("session_application_service_factory must be callable")
    self.services.session_application_service = session_application_service_factory(
        self.services.session_manager, self.services.chat_application_service
    )
    self.services.session_manager.set_runtime_callbacks(
        has_pending_work=self.controllers.require("session")._session_has_pending_chat_work,
        dispose_callback=self.controllers.require("session")._release_chat_session_resources,
    )
    self.state.sessions = self.services.session_manager.sessions_by_character
    self.state.cur = self.services.session_application_service.create_active_session(
        self.services.character_service.active_id(self.services.settings)
    )
    self.state.front = self.state.cur
    self.controllers.require("session")._ensure_session_conversation(self.state.cur)
    self.state._save_warned = False
    self.session._emotion_applied = False
    self.state._closing = False
    self.state._provider_workers = set()
    for resource_name in (
        "_local_voice_worker",
        "_local_stt_test_listener",
        "_mcp_registry_worker",
        "_model_catalog_worker",
        "_model_import_worker",
        "_api_worker",
        "_route_worker",
        "_bench_worker",
        "_scan_worker",
        "_provider_test_worker",
        "_ollama_worker",
        "_web_test_worker",
        "_stopping_game_audio_listener",
    ):
        setattr(self.state, resource_name, None)
    self.state.reactions = load_reactions()
    self.state._last_variant = {}
    self.state._clicks = {}
    self.session._plain_retry = False
    self.state._tr = []
    self.state._status = ("st_checking", {})
    self.session._search_token, self.session._search_worker, self.session._web_found = 0, None, None   # web search for the current message
    self.state._tiles = []                   # attachment cards above the input (files/images chosen for the next message)
    self.state._load_tiles = []              # cards of the batch currently being read
    self.state._upload_tiles = []            # cards shown while the message is being sent to the model
    self.state._upload_token, self.state._upload_done, self.state._att_seq = 0, False, 0
    self.state._chat_action_seq = 0                       # ids of the per-message action chips (copy / edit / speak)
    self.state._chat_action_texts = {}
    self.state._neon_animations = []
    self.state._mood_emotion_glow = None
    self.session._turn_extra = None            # full text + images of the message being answered (history keeps a short form)
    self.session._turn_attach_kinds = []       # kinds ("image"/"text") of what the user attached to the message being answered
    self.session._voice_next = False           # the next submit() comes from the microphone (the model is told it may contain mishearings)
    self.session._voice_preview_pos = None       # temporary live ASR bubble; never persisted as a message
    self.session._turn_voice = False
    self.session._stream_text, self.session._stream_pos, self.session._stream_dirty, self.session._stream_mood = "", None, False, None
    self.session._t_req = self.session._t_first = None
    self.session._route_info = None
    self.session._badge_phase = "idle"
    self.state._loading_route = False
    self.state._provider_editing = set()      # providers currently in Edit mode (their unsaved fields are never collected)
    self.state._bench_busy = False
    self.session.client = self.services.provider_application_service.create_router(self.services.settings)
    self.adapters.game_mode = LazyGameModeMonitor(self.host)
    app = QApplication.instance()
    if app is not None:
        app.aboutToQuit.connect(self.adapters.game_mode.dispose)
    self.state._game_mode_enabled = False
    self.state._game_audio_restart_pending = False
    self.state._game_mode_profile = self.services.game_mode_application_service.normalize_profile(
        self.services.settings.get("eye_mode_profile")      # unknown/missing -> Competitive Safe
    )
    self.state._latest_game_frame = None
    # Vision cadence, safety gating and deduplication are owned by the application service.
    self.session._vision_worker = None
    self.session._vision_session = None
    self.adapters.game_audio_listener = None
    self.state._game_prev_mic = False
    self.state._game_prev_wake = False
    self.services.tool_agent = tool_agent
    set_desktop_context_provider = getattr(tool_agent, "set_desktop_context_provider", None)
    if callable(set_desktop_context_provider):
        set_desktop_context_provider(self.services.desktop_context_application_service.summary)
    self.session._tool_plan = None             # tool plan of the message being answered (None = ordinary chat, nothing added to the prompt)
    self.services.ollama_client = self.services.provider_application_service.create_ollama_client(self.services.settings)
    self.adapters.director = EmotionDirector.from_default()        # emotion library + engine (kira/emotion, emotion_library/)
    self.adapters.animator = EmotionFaceAnimator(self.host, director=self.adapters.director)
    # One window-owned manager will serve all future UI motion features.
    self.adapters.motion = MotionManager(self.host)
    from .appearance_runtime import AppearanceRuntime
    self.adapters.appearance_runtime = AppearanceRuntime(self)
    self.adapters.companion = CompanionWindow(self.adapters.animator)
    self.adapters.companion.pet.settings = self.services.settings          # live reference: perch / hang / auto_dance switches
    self.adapters.music_watcher = None

    def _start_music_watcher():
        if (
            self.state._closing
            or self.adapters.music_watcher is not None
            or sys.platform != "win32"
            or not self.services.settings.get("auto_dance", True)
        ):
            return
        try:
            from ..music_dance import MusicWatcher

            watcher = MusicWatcher(self.host)
            watcher.state.connect(self.adapters.companion.pet.on_music)
            watcher.error.connect(lambda message: logging.getLogger("kira.pet").warning("%s", message))
            QApplication.instance().aboutToQuit.connect(lambda w=watcher: (w.stop(), w.wait(1500)))
            watcher.start()
            self.adapters.music_watcher = watcher
        except Exception as exc:                                           # noqa: BLE001 - optional animation
            logging.getLogger("kira.pet").warning("music watcher not started: %s", exc)

    # Optional loopback analysis waits until after the desktop has painted.
    self.state._music_watcher_timer = QTimer(self.host)
    self.state._music_watcher_timer.setSingleShot(True)
    self.state._music_watcher_timer.timeout.connect(_start_music_watcher)
    self.state._music_watcher_timer.start(10000)
    self.adapters.appearance_runtime.apply_character_art()
    self.controllers.require("chat")._install_chat_commands()
    self.adapters.bubble = CompanionBubble()
    self.adapters.bubble.submitted.connect(self.controllers.require("chat").submit)
    self.adapters.bubble.imageSearchToggled.connect(self.controllers.require("chat").toggle_image_search)
    self.adapters.bubble.set_image_search(bool(self.services.settings.get("image_search", False)))
    self.adapters.companion.geometry_changed.connect(self.controllers.require("lifecycle").update_bubble)
    self.adapters.companion.visibility.connect(lambda _=None: self.controllers.require("lifecycle").update_bubble())
    def create_speaker():
        from ..voice import Speaker
        return Speaker(self.services.settings, self.host)

    self.adapters.speaker = LazySpeaker(create_speaker, settings=self.services.settings, parent=self.host)
    self.host.voice_listener_finished.connect(self.controllers.require("runtime")._on_voice_listener_finished)
    if not callable(voice_application_service_factory):
        raise TypeError("voice_application_service_factory must be callable")
    self.services.voice_application_service = voice_application_service_factory(create_voice_application_ports(self, self.adapters.speaker))
    self.state.awake = False
    self.session.busy = False
    self.session._speech_live = False
    self.adapters.speaker.started.connect(self.controllers.require("runtime").on_speech_started)
    self.adapters.speaker.finished.connect(self.controllers.require("runtime").on_speech_finished)
    self.adapters.speaker.level.connect(self.adapters.animator.set_mouth_target)
    self.adapters.speaker.level.connect(self.controllers.require("runtime")._on_kira_level)
    self.adapters.speaker.error.connect(self.controllers.require("session").on_voice_error)
    self.state._local_tts_test_active = False
    self.adapters.speaker.started.connect(self.controllers.require("voice_settings")._on_local_tts_playback_started)
    self.adapters.speaker.finished.connect(self.controllers.require("voice_settings")._on_local_tts_playback_finished)
    self.adapters.speaker.cancelled.connect(self.controllers.require("voice_settings")._on_local_tts_playback_cancelled)
    self.adapters.speaker.error.connect(self.controllers.require("voice_settings")._on_local_tts_playback_error)
    self.views.wake_timer = QTimer(self.host)
    self.views.wake_timer.setSingleShot(True)
    self.views.wake_timer.timeout.connect(self.controllers.require("runtime").go_sleep)
    self.state._game_poll_timer = QTimer(self.host)
    self.state._game_poll_timer.setInterval(2500)
    self.state._game_poll_timer.timeout.connect(self.adapters.game_mode.poll)
    self.state._game_poll_timer.start()
    self.state._game_capture_timer = QTimer(self.host)
    # The capture timer is stopped until Eye Mode is enabled. Its policy-specific
    # interval is applied by the Vision controller when the feature is activated.
    self.state._game_capture_timer.setInterval(5000)
    self.state._game_capture_timer.timeout.connect(
        lambda: self.controllers.require("attachments_vision")._capture_active_vision_frame()
    )
    self.adapters.game_mode.game_detected.connect(
        lambda *args: self.controllers.require("attachments_vision").on_game_detected(*args)
    )
    self.host.resize(900, 720)
    self.host.setAcceptDrops(True)                          # drop images / files anywhere on the window to attach them
    self.state._effect = winfx.active_effect(self.services.settings.get("window_effect"))
    if self.state._effect != "off":
        self.host.setAttribute(Qt.WA_TranslucentBackground, True)    # the DWM paints the glass behind the transparent window
    self.views.tabs = QTabWidget()
    voice_controller = self.controllers.require("voice_settings")
    session_controller = self.controllers.require("session")
    voice_controller.build_chat_tab()

    # Reserve stable tab indexes, but construct settings pages only on first entry.
    self.views.tab_keys = ["tab_chat", "tab_voice", "tab_char", "tab_appearance", "tab_general", "tab_ai", "tab_eye"]
    def _ensure_assistant_section():
        if not hasattr(self.views, "assistant_page"):
            voice_controller.build_assistant_section()

    def _build_characters_tab():
        _ensure_assistant_section()
        self.controllers.require("character_settings").build_characters_tab()

    def _build_appearance_tab():
        self.controllers.require("character_settings").build_appearance_tab()

    def _build_general_tab():
        self.controllers.require("character_settings").build_general_tab()

    def _build_ai_tab():
        _ensure_assistant_section()
        self.controllers.require("provider_settings").build_ai_tab()

    def _build_eye_tab():
        page = self.controllers.require("attachments_vision").build_eye_vision_page()
        self.views.tabs.addTab(session_controller.page(page), "")

    lazy_tab_builders = {
        1: ("tab_voice", voice_controller.build_voice_tab),
        2: ("tab_char", _build_characters_tab),
        3: ("tab_appearance", _build_appearance_tab),
        4: ("tab_general", _build_general_tab),
        5: ("tab_ai", _build_ai_tab),
        6: ("tab_eye", _build_eye_tab),
    }
    for key in self.views.tab_keys[1:]:
        placeholder = QWidget(self.host)
        placeholder.setObjectName(f"lazySettings_{key}")
        self.views.tabs.addTab(placeholder, "")

    built_settings_tabs = set()
    building_settings_tabs = set()

    def _ensure_settings_tab(index):
        index = int(index)
        entry = lazy_tab_builders.get(index)
        if entry is None or index in built_settings_tabs or index in building_settings_tabs:
            return index in built_settings_tabs
        key, builder = entry
        tabs = self.views.tabs
        placeholder = tabs.widget(index)
        if placeholder is None:
            return False

        # A page builder appends a real page to this stack. Replacing its placeholder
        # changes tab indexes transiently; block currentChanged until the swap is complete
        # so a neighboring lazy page cannot start building re-entrantly.
        selected_widget = tabs.currentWidget()
        original_widgets = [tabs.widget(pos) for pos in range(tabs.count())]
        previous_signals_blocked = tabs.blockSignals(True)
        building_settings_tabs.add(index)
        page = None
        try:
            builder()
            new_pages = [
                tabs.widget(pos)
                for pos in range(tabs.count())
                if all(tabs.widget(pos) is not old_widget for old_widget in original_widgets)
            ]
            if len(new_pages) != 1:
                raise RuntimeError(
                    f"Settings page builder for {key} must create exactly one top-level page; "
                    f"created {len(new_pages)}"
                )
            page = new_pages[0]

            # Finalize the newly built page while the original placeholder is still intact.
            from .pages._pages_finalizer_entry import apply_all_page_finalizers
            page_fields = {
                "appearance": "appearance_page",
                "assistant": "assistant_page",
                "characters": "character_page",
                "help": "help_page",
                "preferences": "preferences_page",
                "skills": "skills_page",
                "voice": "voice_page",
            }
            from shiboken6 import isValid as is_qobject_valid
            pages = {}
            for name, field in page_fields.items():
                if not hasattr(self.views, field):
                    continue
                candidate = getattr(self.views, field)
                # A previous lazy-build rollback may have scheduled a widget for
                # deletion while its view alias still exists. Never finalize a dead Qt object.
                try:
                    if is_qobject_valid(candidate):
                        pages[name] = candidate
                except (RuntimeError, TypeError):
                    continue
            apply_all_page_finalizers(pages)
            session_controller.tidy_forms()
            session_controller.retranslate()

            placeholder_index = tabs.indexOf(placeholder)
            added_index = tabs.indexOf(page)
            if placeholder_index < 0 or added_index < 0:
                raise RuntimeError(f"Settings page {key} lost its placeholder or newly built page")
            tabs.removeTab(added_index)
            tabs.removeTab(placeholder_index)
            tabs.insertTab(index, page, session_controller.t(key))

            # Keep the same selected page; when the placeholder itself was selected,
            # select its replacement at the same stable index.
            target_widget = page if selected_widget is placeholder else selected_widget
            if target_widget is not None and tabs.indexOf(target_widget) >= 0:
                tabs.setCurrentWidget(target_widget)
            placeholder.deleteLater()
            built_settings_tabs.add(index)
            return True
        except Exception as exc:                                          # noqa: BLE001 - one settings page must not break the chat shell
            # Remove every page created by a failed builder, not just the last tab.
            for pos in reversed(range(tabs.count())):
                candidate = tabs.widget(pos)
                if candidate is not None and all(candidate is not old_widget for old_widget in original_widgets):
                    tabs.removeTab(pos)
                    candidate.deleteLater()
            if tabs.indexOf(placeholder) < 0:
                if page is not None and tabs.indexOf(page) >= 0:
                    tabs.removeTab(tabs.indexOf(page))
                tabs.insertTab(min(index, tabs.count()), placeholder, session_controller.t(key))
            placeholder.setToolTip(f"بارگذاری این بخش ناموفق بود: {exc}")
            logging.getLogger("kira.ui").exception("Could not build settings page %s", key)
            if selected_widget is not None and tabs.indexOf(selected_widget) >= 0:
                tabs.setCurrentWidget(selected_widget)
            return False
        finally:
            building_settings_tabs.discard(index)
            tabs.blockSignals(previous_signals_blocked)

    # Save may be requested from any settings section; build all sections on demand then.
    self.host._ensure_settings_tab = _ensure_settings_tab

    def create_attachment_worker(paths):
        # Defer importing the attachment worker until the user actually picks files.
        from .workers import AttachWorker

        return AttachWorker(paths)

    self.adapters.chat_attachment_controller = ChatAttachmentController(
        attach_strip=self.views.chat_composer.attach_strip,
        error_label=self.views.chat_composer.attach_err,
        error_widget=self.views.chat_composer.attach_err_widget,
        error_close_button=self.views.chat_composer.attach_err_close,
        send_button=self.views.send_btn,
        is_chat_busy=lambda: self.session.busy,
        tile_factory=AttachmentTile,
        worker_factory=create_attachment_worker,
        attachment_api=att,
        max_files=att.MAX_FILES,
        parent=self.host,
    )
    # Chat receives the independent attachment workflow explicitly; it no
    # longer reaches into the AttachmentsVision feature controller for it.
    self.controllers.require("chat").bind_attachment_controller(
        self.adapters.chat_attachment_controller
    )
    # Compatibility aliases remain while callers migrate to the controller contract.
    self.state._tiles = self.adapters.chat_attachment_controller.tiles
    self.state._load_tiles = self.adapters.chat_attachment_controller.loading_tiles
    if console_log_capture is not None:
        log_page = build_console_log_page(
            console_log_capture,
            self.host,
            title_text=self.controllers.require("session").t("log_title"),
            clear_text=self.controllers.require("session").t("log_clear"),
        )
        self.views.tabs.addTab(log_page, self.controllers.require("session").t("tab_logs"))
    self.views.save_btn = QPushButton()
    self.views.save_btn.setObjectName("save")
    self.views.save_btn.setIcon(make_icon("check", normal="#ffffff", hover="#ffffff"))
    self.views.save_btn.setIconSize(QSize(16, 16))
    self.views.save_btn.clicked.connect(self.controllers.require("lifecycle").apply_settings)
    self.controllers.require("session").reg(self.views.save_btn.setText, "save")
    if console_log_capture is not None:
        self.views.tab_keys.append("tab_logs")
    install_window_shortcuts(                                            # shortcuts are children of the window, nothing else to keep
        window,
        go_tab=lambda i: self.controllers.require("session").go_tab(i),
        focus_input=lambda: self.views.input.setFocus(),
        stop_generation=lambda: (self.views.gen_stop_btn.click()
                                 if self.views.gen_stop_btn.isVisible() and self.views.gen_stop_btn.isEnabled() else None),
        tab_count=len(self.views.tab_keys),
        settings_tab=self.views.tab_keys.index("tab_ai"),
    )
    # Only the chat page exists initially; each settings page is tidied when it is first built.
    for i, key in enumerate(self.views.tab_keys):
        self.controllers.require("session").reg(lambda s, i=i: self.views.tabs.setTabText(i, s), key)
    # Compact icon navigation. The QTabWidget stays as the page stack (its tab strip is hidden).
    self.views.tabs.tabBar().hide()
    # Dedicated icon navigation for every primary page. The overflow menu remains
    # available as an alternate route, but sections are now one tap away.
    # Indices follow tab_keys so removing or reordering a tab cannot shift the icons.
    nav_icons = {"tab_chat": "chat", "tab_voice": "mic", "tab_char": "user",
                 "tab_appearance": "palette", "tab_general": "settings", "tab_ai": "route"}
    self.state._nav_icon_map = [(nav_icons[key], self.views.tab_keys.index(key)) for key in nav_icons]
    if console_log_capture is not None:
        self.state._nav_icon_map.append(("terminal", self.views.tab_keys.index("tab_logs")))
    # Primary sections are accessed from the hamburger menu only.
    self.views.nav_buttons = []
    self.views.menu_btn = QToolButton()
    self.views.menu_btn.setObjectName("menuBtn")
    self.views.menu_btn.setProperty("kiraIconName", "menu")
    self.views.menu_btn.setIcon(make_icon("menu"))
    self.views.menu_btn.setIconSize(QSize(20, 20))
    self.views.menu_btn.setCursor(Qt.PointingHandCursor)
    self.controllers.require("session").reg(self.views.menu_btn.setToolTip, "nav_menu_tip")
    self.views.menu_btn.setPopupMode(QToolButton.InstantPopup)
    self.views.nav_menu = QMenu(self.host)
    self.views.menu_btn.setMenu(self.views.nav_menu)
    self.state._menu_actions = []
    for i, key in enumerate(self.views.tab_keys):
        icon_name = next((name for name, idx in self.state._nav_icon_map if idx == i), "help")
        action = self.views.nav_menu.addAction(make_icon(icon_name), self.controllers.require("session").t(key))
        action.triggered.connect(lambda checked=False, idx=i: self.controllers.require("session").go_tab(idx))
        self.state._menu_actions.append(action)

    # Eye Mode is explicit opt-in. Keep the compatibility setting disabled without
    # constructing the deferred Vision and desktop-capture services during composition.
    self.services.settings["desktop_vision_enabled"] = False

    def _selected_desktop_monitor_id():
        return str(self.services.settings.get("desktop_vision_monitor_id") or "").strip()
    self.views.nav_menu.addSeparator()
    # Eye Mode has exactly one on/off control in the chat composer. Keep only
    # monitor selection in navigation; the legacy second toggle is removed.
    self.views.desktop_vision_action = None
    self.views.desktop_vision_monitor_menu = self.views.nav_menu.addMenu("Eye Mode · انتخاب مانیتور")
    self.views.desktop_vision_monitor_actions = {}
    self.views.desktop_vision_auto_action = self.views.desktop_vision_monitor_menu.addAction(
        "خودکار · مانیتور پنجرهٔ فعال"
    )
    self.views.desktop_vision_auto_action.setCheckable(True)
    self.views.desktop_vision_auto_action.setChecked(not _selected_desktop_monitor_id())
    self.views.desktop_vision_auto_action.triggered.connect(
        lambda checked=False: self.controllers.require("attachments_vision").set_desktop_monitor("")
    )
    def _populate_desktop_monitor_menu():
        """Refresh hardware-dependent choices only when the user opens the menu."""
        menu = self.views.desktop_vision_monitor_menu
        for stale_action in tuple(menu.actions())[1:]:
            menu.removeAction(stale_action)
            stale_action.deleteLater()
        self.views.desktop_vision_monitor_actions.clear()
        for monitor in self.adapters.game_mode.capture_service.list_monitors():
            label = monitor.name + (" · اصلی" if monitor.primary else "")
            action = menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(monitor.id == _selected_desktop_monitor_id())
            action.triggered.connect(
                lambda checked=False, monitor_id=monitor.id:
                    self.controllers.require("attachments_vision").set_desktop_monitor(monitor_id)
            )
            self.views.desktop_vision_monitor_actions[monitor.id] = action

    self.views.desktop_vision_monitor_menu.aboutToShow.connect(
        _populate_desktop_monitor_menu
    )

    central = QWidget()
    central_layout = QVBoxLayout(central)
    central_layout.setContentsMargins(10, 8, 10, 10)
    central_layout.setSpacing(8)
    toolbar_frame = QFrame()
    toolbar_frame.setObjectName("neonToolbar")
    toolbar = QHBoxLayout(toolbar_frame)
    toolbar.setContentsMargins(7, 5, 7, 5)
    toolbar.setSpacing(5)
    toolbar.addWidget(self.views.menu_btn)
    self.views.new_chat_btn = QPushButton("چت جدید", self.host)
    self.views.new_chat_btn.setObjectName("newChatButton")
    self.views.new_chat_btn.setToolTip("شروع یک گفتگوی مستقل؛ تاریخچهٔ قبلی حفظ می‌شود.")
    self.views.new_chat_btn.clicked.connect(self.controllers.require("session").new_chat)
    toolbar.addWidget(self.views.new_chat_btn)
    self.views.news_feed_btn = QPushButton("خبرها", self.host)
    self.views.news_feed_btn.setObjectName("newsFeedButton")
    self.views.news_feed_btn.setToolTip("فید خبری مستقلِ شخصیت فعال؛ حافظهٔ خبری هفت روز اخیر")
    def _open_news_feed():
        from .dialogs.news_feed import NewsFeedDialog
        dialog = NewsFeedDialog(
            self.state.cur.cid,
            self.services.settings,
            self.host,
            chat_client=self.session.client,
        )
        dialog.exec()
    self.views.news_feed_btn.clicked.connect(_open_news_feed)
    toolbar.addWidget(self.views.news_feed_btn)
    toolbar.addStretch(1)
    toolbar.addWidget(self.views.save_btn)
    central_layout.addWidget(toolbar_frame)
    central_layout.addWidget(self.views.tabs, 1)
    self.host.setCentralWidget(central)
    from .news_feed_runtime import NewsFeedRuntime
    self.state._news_feed_runtime = NewsFeedRuntime(
        self.host,
        self.services.settings,
        self.state,
        chat_client=self.session.client,
    )
    self.views.tabs.currentChanged.connect(_ensure_settings_tab)
    self.views.tabs.currentChanged.connect(self.controllers.require("session")._sync_nav)

    def _maybe_refresh_provider_catalog(index):
        if index != self.views.tab_keys.index("tab_ai") or self.state._provider_catalog_auto_refresh_started:
            return
        self.state._provider_catalog_auto_refresh_started = True
        QTimer.singleShot(
            0,
            lambda: self.controllers.require("provider_settings").auto_refresh_model_catalogs(),
        )

    self.state._provider_catalog_auto_refresh_started = False
    self.views.tabs.currentChanged.connect(_maybe_refresh_provider_catalog)
    self.controllers.require("session")._sync_nav()
    self.state._mood_ui_timer = QTimer(self.host)                 # the neon mood chips follow the persisted emotional state
    self.state._mood_ui_timer.setInterval(1500)
    self.state._mood_ui_timer.timeout.connect(self.controllers.require("session").update_mood_indicator)
    self.state._mood_ui_timer.start()
    self.controllers.require("session").update_mood_indicator()
    self.adapters.animator.mood_changed.connect(self.controllers.require("runtime").on_mood_changed)
    self.adapters.companion.clicked.connect(self.controllers.require("runtime").on_region_clicked)
    self.views.avatar.clicked.connect(self.controllers.require("runtime").on_region_clicked)
    self.adapters.companion.visibility.connect(self.controllers.require("runtime").on_companion_visibility)
    self.adapters.animator.look_anchor = self.controllers.require("lifecycle").look_anchor
    self.adapters.appearance_runtime.apply_appearance(save=False)
    self.controllers.require("lifecycle").apply_runtime()
    self.controllers.require("session").retranslate()
    self.controllers.require("runtime").set_badge("idle", self.session.client.preview_route())
    self.controllers.require("session").sync_sessions()
    self.controllers.require("session").switch_session(self.services.character_service.active_id(self.services.settings), save=False)
    for note in self.state._db_notes:
        self.controllers.require("session").add_chat("error", note)
    for warning in LOAD_WARNINGS + self.adapters.director.library.warnings:
        self.controllers.require("session").add_chat("system", warning)
    self.controllers.require("lifecycle").check_status()
    self.state._news_feed_runtime.start()
    self.adapters.director.event("app_startup")

