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
    self = window
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
    self.memory_service = memory_service
    self.mood_service = mood_service
    self.character_service = character_service
    if not callable(chat_application_service_factory):
        raise TypeError("chat_application_service_factory must be callable")
    self.chat_application_service = chat_application_service_factory(create_chat_application_ports(self))
    self.web_search_service = web_search_service
    self.game_mode_application_service = game_mode_application_service
    self.settings = settings
    self.provider_application_service = provider_application_service
    self.runtime_settings_application_service = runtime_settings_application_service
    self.shared_skills_application_service = shared_skills_application_service
    self.runtime_settings_application_service.configure(self.settings)
    self.coding_agent_application_service = coding_agent_application_service
    self.vision_application_service = vision_application_service
    self._db_notes = self.chat_application_service.init_history()
    self.session_manager = session_manager
    self.chat_event_publisher = chat_event_publisher
    if not callable(session_application_service_factory):
        raise TypeError("session_application_service_factory must be callable")
    self.session_application_service = session_application_service_factory(
        self.session_manager, self.chat_application_service
    )
    self.session_manager.set_runtime_callbacks(
        has_pending_work=self._session_has_pending_chat_work,
        dispose_callback=self._release_chat_session_resources,
    )
    self.sessions = self.session_manager.sessions_by_character
    self.cur = self.session_application_service.create_active_session(
        self.character_service.active_id(self.settings)
    )
    self.front = self.cur
    self._ensure_session_conversation(self.cur)
    self._save_warned = False
    self._emotion_applied = False
    self._closing = False
    self.reactions = load_reactions()
    self._last_variant = {}
    self._clicks = {}
    self._plain_retry = False
    self._tr = []
    self._status = ("st_checking", {})
    self._search_token, self._search_worker, self._web_found = 0, None, None   # web search for the current message
    self._tiles = []                   # attachment cards above the input (files/images chosen for the next message)
    self._load_tiles = []              # cards of the batch currently being read
    self._upload_tiles = []            # cards shown while the message is being sent to the model
    self._upload_token, self._upload_done, self._att_seq = 0, False, 0
    self._chat_action_seq = 0                       # ids of the per-message action chips (copy / edit / speak)
    self._chat_action_texts = {}
    self._neon_animations = []
    self._mood_emotion_glow = None
    self._turn_extra = None            # full text + images of the message being answered (history keeps a short form)
    self._turn_attach_kinds = []       # kinds ("image"/"text") of what the user attached to the message being answered
    self._voice_next = False           # the next submit() comes from the microphone (the model is told it may contain mishearings)
    self._turn_voice = False
    self._stream_text, self._stream_pos, self._stream_dirty, self._stream_mood = "", None, False, None
    self._t_req = self._t_first = None
    self._route_info = None
    self._badge_phase = "idle"
    self._loading_route = False
    self._provider_editing = set()      # providers currently in Edit mode (their unsaved fields are never collected)
    self._bench_busy = False
    self._ollama_models = []
    self.client = self.provider_application_service.create_router(self.settings)
    self.game_mode = GameModeMonitor(self)
    self._game_mode_enabled = False
    self._game_mode_profile = self.game_mode_application_service.COMPETITIVE_SAFE_MODE
    self._latest_game_frame = None
    # Vision cadence, safety gating and deduplication are owned by the application service.
    self._vision_worker = None
    self._vision_session = None
    self.game_audio_listener = None
    self._game_prev_mic = False
    self._game_prev_wake = False
    self.tool_agent = tool_agent
    self._tool_plan = None             # tool plan of the message being answered (None = ordinary chat, nothing added to the prompt)
    self.ollama_client = self.provider_application_service.create_ollama_client(self.settings)
    self.director = EmotionDirector.from_default()        # emotion library + engine (kira/emotion, emotion_library/)
    self.animator = EmotionFaceAnimator(self, director=self.director)
    self.companion = CompanionWindow(self.animator)
    self.apply_character_art()
    self._install_chat_commands()
    self.bubble = CompanionBubble()
    self.bubble.submitted.connect(self.submit)
    self.bubble.imageSearchToggled.connect(self.toggle_image_search)
    self.bubble.set_image_search(bool(self.settings.get("image_search", False)))
    self.companion.geometry_changed.connect(self.update_bubble)
    self.companion.visibility.connect(lambda _=None: self.update_bubble())
    self.speaker = Speaker(self.settings, self)
    self.voice_listener_finished.connect(self._on_voice_listener_finished)
    if not callable(voice_application_service_factory):
        raise TypeError("voice_application_service_factory must be callable")
    self.voice_application_service = voice_application_service_factory(create_voice_application_ports(self, self.speaker))
    self.awake = False
    self.busy = False
    self._speech_live = False
    self.speaker.started.connect(self.on_speech_started)
    self.speaker.finished.connect(self.on_speech_finished)
    self.speaker.level.connect(self.animator.set_mouth_target)
    self.speaker.level.connect(self._on_kira_level)
    self.speaker.error.connect(self.on_voice_error)
    self._local_tts_test_active = False
    self.speaker.started.connect(self._on_local_tts_playback_started)
    self.speaker.finished.connect(self._on_local_tts_playback_finished)
    self.speaker.cancelled.connect(self._on_local_tts_playback_cancelled)
    self.speaker.error.connect(self._on_local_tts_playback_error)
    self.wake_timer = QTimer(self)
    self.wake_timer.setSingleShot(True)
    self.wake_timer.timeout.connect(self.go_sleep)
    self._game_poll_timer = QTimer(self)
    self._game_poll_timer.setInterval(2500)
    self._game_poll_timer.timeout.connect(self.game_mode.poll)
    self._game_poll_timer.start()
    self._game_capture_timer = QTimer(self)
    self._game_capture_timer.setInterval(int(self.vision_application_service.policy.interval_seconds * 1000))
    self._game_capture_timer.timeout.connect(self._capture_game_frame)
    self.game_mode.game_detected.connect(self.on_game_detected)
    self.resize(900, 720)
    self.setMinimumSize(520, 540)
    self.setAcceptDrops(True)                          # drop images / files anywhere on the window to attach them
    self._effect = winfx.active_effect(self.settings.get("window_effect"))
    if self._effect != "off":
        self.setAttribute(Qt.WA_TranslucentBackground, True)    # the DWM paints the glass behind the transparent window
    self.tabs = QTabWidget()
    self.build_chat_tab()
    self.attachment_controller = ChatAttachmentController(
        attach_strip=self.chat_composer.attach_strip,
        error_label=self.chat_composer.attach_err,
        error_widget=self.chat_composer.attach_err_widget,
        error_close_button=self.chat_composer.attach_err_close,
        send_button=self.send_btn,
        is_chat_busy=lambda: self.busy,
        tile_factory=AttachmentTile,
        worker_factory=AttachWorker,
        attachment_api=att,
        max_files=att.MAX_FILES,
    )
    # Compatibility aliases remain while callers migrate to the controller contract.
    self._tiles = self.attachment_controller.tiles
    self._load_tiles = self.attachment_controller.loading_tiles
    self.build_assistant_section()
    self.build_voice_tab()
    self.build_characters_tab()
    self.build_appearance_tab()
    self.build_general_tab()
    self.build_ai_tab()
    # Keep local STT/TTS model management on the Voice page.
    voice_page = self.tabs.widget(self.tab_keys.index("tab_voice")) if hasattr(self, "tab_keys") else self.tabs.widget(2)
    voice_layout = voice_page.widget().layout()
    # The Voice page uses a QGridLayout; append local model management below the device controls.
    voice_row = voice_layout.rowCount()
    if hasattr(self, "local_voice_box"):
        voice_layout.addWidget(self.local_voice_box, voice_row, 0, 1, 2)
        voice_row += 1
    self.refresh_local_voice_status()
    self.save_btn = QPushButton()
    self.save_btn.setObjectName("save")
    self.save_btn.setIcon(make_icon("check", normal="#ffffff", hover="#ffffff"))
    self.save_btn.setIconSize(QSize(16, 16))
    self.save_btn.clicked.connect(self.apply_settings)
    self.reg(self.save_btn.setText, "save")
    self.tab_keys = ["tab_chat", "tab_assistant", "tab_voice", "tab_char", "tab_appearance", "tab_general", "tab_ai"]
    self.tidy_forms()                      # field widths follow their content (done once every page exists)
    for i, key in enumerate(self.tab_keys):
        self.reg(lambda s, i=i: self.tabs.setTabText(i, s), key)
    # Compact icon navigation. The QTabWidget stays as the page stack (its tab strip is hidden).
    self.tabs.tabBar().hide()
    ai_index = self.tab_keys.index("tab_ai")
    # Dedicated icon navigation for every primary page. The overflow menu remains
    # available as an alternate route, but sections are now one tap away.
    self._nav_icon_map = [("chat", 0), ("brain", 1), ("mic", 2), ("user", 3),
                          ("palette", 4), ("settings", 5), ("route", ai_index)]
    # Primary sections are accessed from the hamburger menu only.
    self.nav_buttons = []
    self.menu_btn = QToolButton()
    self.menu_btn.setObjectName("menuBtn")
    self.menu_btn.setProperty("kiraIconName", "menu")
    self.menu_btn.setIcon(make_icon("menu"))
    self.menu_btn.setIconSize(QSize(20, 20))
    self.menu_btn.setCursor(Qt.PointingHandCursor)
    self.reg(self.menu_btn.setToolTip, "nav_menu_tip")
    self.menu_btn.setPopupMode(QToolButton.InstantPopup)
    self.nav_menu = QMenu(self)
    self.menu_btn.setMenu(self.nav_menu)
    self._menu_actions = []
    for i, key in enumerate(self.tab_keys):
        icon_name = next((name for name, idx in self._nav_icon_map if idx == i), "help")
        action = self.nav_menu.addAction(make_icon(icon_name), self.t(key))
        action.triggered.connect(lambda checked=False, idx=i: self.go_tab(idx))
        self._menu_actions.append(action)
    central = QWidget()
    central_layout = QVBoxLayout(central)
    central_layout.setContentsMargins(10, 8, 10, 10)
    central_layout.setSpacing(8)
    toolbar_frame = QFrame()
    toolbar_frame.setObjectName("neonToolbar")
    toolbar = QHBoxLayout(toolbar_frame)
    toolbar.setContentsMargins(7, 5, 7, 5)
    toolbar.setSpacing(5)
    self.menu_btn.setFixedSize(38, 38)
    toolbar.addWidget(self.menu_btn)
    toolbar.addStretch(1)
    toolbar.addWidget(self.save_btn)
    central_layout.addWidget(toolbar_frame)
    central_layout.addWidget(self.tabs, 1)
    self.setCentralWidget(central)
    self.tabs.currentChanged.connect(self._sync_nav)
    self._sync_nav()
    self._mood_ui_timer = QTimer(self)                 # the neon mood chips follow the persisted emotional state
    self._mood_ui_timer.setInterval(1500)
    self._mood_ui_timer.timeout.connect(self.update_mood_indicator)
    self._mood_ui_timer.start()
    self.update_mood_indicator()
    self.animator.mood_changed.connect(self.on_mood_changed)
    self.companion.clicked.connect(self.on_region_clicked)
    self.avatar.clicked.connect(self.on_region_clicked)
    self.companion.visibility.connect(self.on_companion_visibility)
    self.animator.look_anchor = self.look_anchor
    self.apply_appearance(save=False)
    self.apply_runtime()
    self.retranslate()
    self.set_badge("idle", self.client.preview_route())
    self.sync_sessions()
    self.switch_session(self.character_service.active_id(self.settings), save=False)
    for note in self._db_notes:
        self.add_chat("error", note)
    for warning in LOAD_WARNINGS + self.director.library.warnings:
        self.add_chat("system", warning)
    self.check_status()
    self.director.event("app_startup")

