"""Composition of the desktop window and its UI feature adapters.

This module owns widget/service assembly. MainWindow is the Qt shell and controller registry; application services
receive typed ports, never the window.
"""
from __future__ import annotations

from .main_window_root_support import (
    AttachWorker,
    AttachmentTile,
    ChatAttachmentController,
    CompanionBubble,
    CompanionWindow,
    EmotionDirector,
    EmotionFaceAnimator,
    GameModeMonitor,
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
    Speaker,
    att,
    load_reactions,
    make_icon,
    winfx,
)
from .application_adapters import (
    create_chat_application_ports,
    create_voice_application_ports,
)


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
    runtime_settings_application_service=None,
    shared_skills_application_service=None,
):
    """Build UI widgets and bind injected services to typed Qt callback adapters."""
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
        "runtime_settings_application_service": runtime_settings_application_service,
        "shared_skills_application_service": shared_skills_application_service,
        "tool_agent": tool_agent,
    }
    missing = tuple(name for name, value in required.items() if value is None)
    if missing:
        raise TypeError("MainWindow composition requires Bootstrap dependencies: " + ", ".join(missing))
    self.services.memory_service = memory_service
    self.services.mood_service = mood_service
    self.services.character_service = character_service
    if not callable(chat_application_service_factory):
        raise TypeError("chat_application_service_factory must be callable")
    self.services.chat_application_service = chat_application_service_factory(create_chat_application_ports(self))
    self.services.web_search_service = web_search_service
    self.services.game_mode_application_service = game_mode_application_service
    self.services.settings = settings
    self.services.provider_application_service = provider_application_service
    self.services.runtime_settings_application_service = runtime_settings_application_service
    self.services.shared_skills_application_service = shared_skills_application_service
    self.services.runtime_settings_application_service.configure(self.services.settings)
    self.services.coding_agent_application_service = coding_agent_application_service
    self.services.vision_application_service = vision_application_service
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
    self.session._turn_voice = False
    self.session._stream_text, self.session._stream_pos, self.session._stream_dirty, self.session._stream_mood = "", None, False, None
    self.session._t_req = self.session._t_first = None
    self.session._route_info = None
    self.session._badge_phase = "idle"
    self.state._loading_route = False
    self.state._provider_editing = set()      # providers currently in Edit mode (their unsaved fields are never collected)
    self.state._bench_busy = False
    self.state._ollama_models = []
    self.session.client = self.services.provider_application_service.create_router(self.services.settings)
    self.adapters.game_mode = GameModeMonitor(self.host)
    self.state._game_mode_enabled = False
    self.state._game_mode_profile = self.services.game_mode_application_service.COMPETITIVE_SAFE_MODE
    self.state._latest_game_frame = None
    # Vision cadence, safety gating and deduplication are owned by the application service.
    self.session._vision_worker = None
    self.session._vision_session = None
    self.adapters.game_audio_listener = None
    self.state._game_prev_mic = False
    self.state._game_prev_wake = False
    self.services.tool_agent = tool_agent
    self.session._tool_plan = None             # tool plan of the message being answered (None = ordinary chat, nothing added to the prompt)
    self.services.ollama_client = self.services.provider_application_service.create_ollama_client(self.services.settings)
    self.adapters.director = EmotionDirector.from_default()        # emotion library + engine (kira/emotion, emotion_library/)
    self.adapters.animator = EmotionFaceAnimator(self.host, director=self.adapters.director)
    self.adapters.companion = CompanionWindow(self.adapters.animator)
    self.controllers.require("character_settings").apply_character_art()
    self.controllers.require("chat")._install_chat_commands()
    self.adapters.bubble = CompanionBubble()
    self.adapters.bubble.submitted.connect(self.controllers.require("chat").submit)
    self.adapters.bubble.imageSearchToggled.connect(self.controllers.require("chat").toggle_image_search)
    self.adapters.bubble.set_image_search(bool(self.services.settings.get("image_search", False)))
    self.adapters.companion.geometry_changed.connect(self.controllers.require("lifecycle").update_bubble)
    self.adapters.companion.visibility.connect(lambda _=None: self.controllers.require("lifecycle").update_bubble())
    self.adapters.speaker = Speaker(self.services.settings, self.host)
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
    self.state._game_capture_timer.setInterval(int(self.services.vision_application_service.policy.interval_seconds * 1000))
    self.state._game_capture_timer.timeout.connect(self.controllers.require("attachments_vision")._capture_game_frame)
    self.adapters.game_mode.game_detected.connect(self.controllers.require("attachments_vision").on_game_detected)
    self.host.resize(900, 720)
    self.host.setMinimumSize(520, 540)
    self.host.setAcceptDrops(True)                          # drop images / files anywhere on the window to attach them
    self.state._effect = winfx.active_effect(self.services.settings.get("window_effect"))
    if self.state._effect != "off":
        self.host.setAttribute(Qt.WA_TranslucentBackground, True)    # the DWM paints the glass behind the transparent window
    self.views.tabs = QTabWidget()
    self.controllers.require("voice_settings").build_chat_tab()
    self.adapters.chat_attachment_controller = ChatAttachmentController(
        attach_strip=self.views.chat_composer.attach_strip,
        error_label=self.views.chat_composer.attach_err,
        error_widget=self.views.chat_composer.attach_err_widget,
        error_close_button=self.views.chat_composer.attach_err_close,
        send_button=self.views.send_btn,
        is_chat_busy=lambda: self.session.busy,
        tile_factory=AttachmentTile,
        worker_factory=AttachWorker,
        attachment_api=att,
        max_files=att.MAX_FILES,
    )
    # Chat receives the independent attachment workflow explicitly; it no
    # longer reaches into the AttachmentsVision feature controller for it.
    self.controllers.require("chat").bind_attachment_controller(
        self.adapters.chat_attachment_controller
    )
    # Compatibility aliases remain while callers migrate to the controller contract.
    self.state._tiles = self.adapters.chat_attachment_controller.tiles
    self.state._load_tiles = self.adapters.chat_attachment_controller.loading_tiles
    self.controllers.require("voice_settings").build_assistant_section()
    self.controllers.require("voice_settings").build_voice_tab()
    self.controllers.require("character_settings").build_characters_tab()
    self.controllers.require("character_settings").build_appearance_tab()
    self.controllers.require("character_settings").build_general_tab()
    self.controllers.require("provider_settings").build_ai_tab()
    # Keep local STT/TTS model management on the Voice page.
    voice_page = self.views.tabs.widget(self.views.tab_keys.index("tab_voice")) if hasattr(self, "tab_keys") else self.views.tabs.widget(2)
    voice_layout = voice_page.widget().layout()
    # The Voice page uses a QGridLayout; append local model management below the device controls.
    voice_row = voice_layout.rowCount()
    if hasattr(self, "local_voice_box"):
        voice_layout.addWidget(self.views.local_voice_box, voice_row, 0, 1, 2)
        voice_row += 1
    self.controllers.require("voice_settings").refresh_local_voice_status()
    self.views.save_btn = QPushButton()
    self.views.save_btn.setObjectName("save")
    self.views.save_btn.setIcon(make_icon("check", normal="#ffffff", hover="#ffffff"))
    self.views.save_btn.setIconSize(QSize(16, 16))
    self.views.save_btn.clicked.connect(self.controllers.require("lifecycle").apply_settings)
    self.controllers.require("session").reg(self.views.save_btn.setText, "save")
    self.views.tab_keys = ["tab_chat", "tab_assistant", "tab_voice", "tab_char", "tab_appearance", "tab_general", "tab_ai"]
    self.controllers.require("session").tidy_forms()                      # field widths follow their content (done once every page exists)
    for i, key in enumerate(self.views.tab_keys):
        self.controllers.require("session").reg(lambda s, i=i: self.views.tabs.setTabText(i, s), key)
    # Compact icon navigation. The QTabWidget stays as the page stack (its tab strip is hidden).
    self.views.tabs.tabBar().hide()
    ai_index = self.views.tab_keys.index("tab_ai")
    # Dedicated icon navigation for every primary page. The overflow menu remains
    # available as an alternate route, but sections are now one tap away.
    self.state._nav_icon_map = [("chat", 0), ("brain", 1), ("mic", 2), ("user", 3),
                          ("palette", 4), ("settings", 5), ("route", ai_index)]
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
    central = QWidget()
    central_layout = QVBoxLayout(central)
    central_layout.setContentsMargins(10, 8, 10, 10)
    central_layout.setSpacing(8)
    toolbar_frame = QFrame()
    toolbar_frame.setObjectName("neonToolbar")
    toolbar = QHBoxLayout(toolbar_frame)
    toolbar.setContentsMargins(7, 5, 7, 5)
    toolbar.setSpacing(5)
    self.views.menu_btn.setFixedSize(38, 38)
    toolbar.addWidget(self.views.menu_btn)
    toolbar.addStretch(1)
    toolbar.addWidget(self.views.save_btn)
    central_layout.addWidget(toolbar_frame)
    central_layout.addWidget(self.views.tabs, 1)
    self.host.setCentralWidget(central)
    self.views.tabs.currentChanged.connect(self.controllers.require("session")._sync_nav)
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
    self.controllers.require("character_settings").apply_appearance(save=False)
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
    self.adapters.director.event("app_startup")

