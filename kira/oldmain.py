"""Temporary legacy Kira window and orchestration implementation.

This module is a migration reference. Move feature ownership into independent
modules and remove this file when no application behavior depends on it.
"""

import contextlib
import base64
import json
import random
import time
import uuid
import shutil
import subprocess
from pathlib import Path
import re
import sys
from PySide6.QtCore import Qt, QTimer, QRectF, QUrl, QSize
from PySide6.QtGui import QAction, QIcon, QDesktopServices, QTextCursor, QColor, QBrush, QImage, QTextDocument, QPixmap
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit, QTextBrowser, QLineEdit,
    QPushButton, QMessageBox, QComboBox, QFormLayout, QSpinBox, QTabWidget, QGroupBox, QCheckBox,
    QSlider, QScrollArea, QToolButton, QMenu, QListWidget, QListWidgetItem, QAbstractItemView, QDialog,
    QDialogButtonBox, QFrame, QFileDialog, QSizePolicy, QSystemTrayIcon, QTableWidget, QTableWidgetItem, QHeaderView, QInputDialog,
    QStackedWidget, QDoubleSpinBox, QGridLayout, QButtonGroup, QGraphicsDropShadowEffect, QColorDialog, QProgressBar
)
from .app.session_controller import SessionWindowMixin
from .app.session_relay import front_onlyfrom .config import (load_settings, save_settings, ROOT, VERSION, LOAD_WARNINGS, DATA_DIR,
                     APP_NAME, PROJECT_URL, RELEASES_URL)
from . import about
from . import storage
from .core.exceptions import ChatHistoryError
from .ollama_client import OllamaClient, model_installed, parse_keep_alive, clamp_num_ctx, clamp_num_predict, DEFAULT_NUM_PREDICT, DEFAULT_NUM_CTX, DEFAULT_KEEP_ALIVE
from .hybrid_ai import HybridRouter, probe_provider
from . import routes as route_model
from . import discovery
from . import api_manager
from . import websearch
from .chat import attachments as att
from .actions import match_safe_action, run_safe_action
from .tools import ToolAgent
from .leak_guard import scrub_lines
from .companion import CompanionWindow, CompanionBubble
from .chat_render import sources_html, message_html, detect_direction, bubble_accent
from .face import AvatarView
from .vrm_avatar import KiraAvatar
from .emotion.backend_png import EmotionFaceAnimator
from .emotion.director import EmotionDirector
from .voice import Speaker
from .listener import Listener
from .game_audio import GameAudioListener, is_important_game_audio
from . import modes
from .speech_fixes import SpeechFixes
from .strings import STR
from .personality import build_system_prompt
from . import evidence_memory
from . import brain
from . import usage
from . import mood
from .characters.kira import PROFILE as KIRA_PROFILE
from .character.traits import BASE_TRAITS
from . import avatar_art
from . import body as body_ctl
from .rig import MOODS
from .ui_icons import make_icon, set_glow_intensity
from .ui_widgets import ChatInput, RouteChip, AttachmentTile
from .theme import build_style, STYLE
from . import theme as theme_mod
from .chat_sessions import ChatSession, NOOP, SESSION_FIELDS, session_property, front_only_property
from .chat.application_service import ChatApplicationService, ApplicationEventKind, RequestStatus
from .chat.session_manager import SessionManager
from .chat.commands import PermissionDecision
from .chat.command_adapters import create_default_command_registry
from .tools.tasks import parse_control as parse_tool_task_control
from . import winfx
from .game_mode import GameModeMonitor, CAPTURE_JPEG_QUALITY
from .vision_pipeline import FrameGate, policy_for
from .game_mode_policy import (STORY_MODE, COMPETITIVE_SAFE_MODE, game_mode_permissions, normalize_game_mode_profile)
from .chat_code_ui import CodeChat
from .ui.components import ApiAddPanel, ChatHeader, McpRegistryPanel, ModelCombo, OllamaProviderPanel, RouteEditor, ChatComposer
from .ui.controllers import ChatAttachmentController
from .ui.dialogs import MemoryDialog, ModelPickerDialog
from .ui.pages import AssistantPage, AppearancePage, CharactersPage, HelpPage, PreferencesPage, VoicePage
from .ui.workers import (
    AttachWorker,
    BenchWorker,
    OllamaTaskWorker,
    ProviderTestWorker,
    SearchWorker,
    StreamWorker,
    TaskWorker,
    VisionAnalysisWorker,
)

WAKE_RE = re.compile(r"(?:(?:هی|سلام|hey|hi)[\s\u200c]*)?(?:کی[\s\u200c]?را|کایرا|کیرآ|کیارا|kira|keira|kyra|kiera)", re.I)
STOP_RE = re.compile(r"^\W*(?:بس\s*کن|بسه|ساکت(?:\s*شو)?|صبر\s*کن|وایسا|وایستا|stop|be\s*quiet)\W*$", re.I)       # "just be quiet" is not a chat message
SLEEP_RE = re.compile(r"بخواب|خداحافظ|شب بخیر|good\s*night", re.I)
SOUNDS_DIR = ROOT / "assets" / "sounds"

def load_reactions():
    try:
        return json.loads((ROOT / "reactions.json").read_text(encoding="utf-8"))
    except Exception:
        return {}


class MainWindow(SessionWindowMixin, QMainWindow):
    # Per-chat state: one ChatSession per character; these names read/write the session that is current (see chat_sessions.py).
    busy = session_property("busy")
    worker = session_property("worker")
    _stream_text = session_property("_stream_text")
    _stream_pos = session_property("_stream_pos")
    _stream_dirty = session_property("_stream_dirty")
    _stream_mood = session_property("_stream_mood")
    _emotion_applied = session_property("_emotion_applied")
    _body_done = session_property("_body_done")
    _t_req = session_property("_t_req")
    _t_first = session_property("_t_first")
    _speech_live = session_property("_speech_live")
    _turn_extra = session_property("_turn_extra")
    _turn_attach_kinds = session_property("_turn_attach_kinds")
    _turn_voice = session_property("_turn_voice")
    _turn_mode = session_property("_turn_mode")
    _tool_plan = session_property("_tool_plan")
    _brain = session_property("_brain")
    _brain_user_text = session_property("_brain_user_text")
    _brain_mode_name = session_property("_brain_mode_name")
    _plain_retry = session_property("_plain_retry")
    _web_found = session_property("_web_found")
    _image_search_turn = session_property("_image_search_turn")
    _search_token = session_property("_search_token")
    _search_worker = session_property("_search_worker")
    _search_base = session_property("_search_base")
    _route_info = session_property("_route_info")
    _badge_phase = session_property("_badge_phase")
    client = session_property("client")                 # every chat has its own router (own Stop flag); health/cooldowns are shared
    chat = property(lambda self: self.cur.view)
    _stream_timer = property(lambda self: self.cur.timer)
    # One-per-computer things belong to the chat in front; a background chat gets silent stand-ins.
    speaker = front_only_property("speaker")
    director = front_only_property("director", ("parse_reply", "format_hint", "library"))
    animator = front_only_property("animator")
    bubble = front_only_property("bubble")
    status = front_only_property("status")
    gen_stop_btn = front_only_property("gen_stop_btn")
    send_btn = front_only_property("send_btn")
    input = front_only_property("input")
    voice_btn = front_only_property("voice_btn")
    @property
    def _attach_worker(self):
        controller = getattr(self, "attachment_controller", None)
        return controller.worker if controller is not None else None


    def __init__(self, memory_service=None, mood_service=None, character_service=None, chat_history_service=None,
                 session_manager=None, chat_event_publisher=None, chat_application_service_factory=None):
        super().__init__()
        # Direct MainWindow construction remains supported for existing callers;
        # normal application startup injects these services from app.bootstrap.
        if memory_service is None:
            from .services.memory_service import PersonaMemoryService
            memory_service = PersonaMemoryService()
        if mood_service is None:
            from .services.mood_service import MoodStateService
            mood_service = MoodStateService()
        self.memory_service = memory_service
        self.mood_service = mood_service
        if character_service is None:
            from .services.character_service import CharacterProfileService
            character_service = CharacterProfileService()
        self.character_service = character_service
        if chat_history_service is None:
            from .services.chat_history_service import SqliteChatHistoryService
            chat_history_service = SqliteChatHistoryService()
        if chat_application_service_factory is not None:
            if not callable(chat_application_service_factory):
                raise TypeError("chat_application_service_factory must be callable")
            self.chat_application_service = chat_application_service_factory(self)
        else:
            # Compatibility path for callers that instantiate MainWindow directly.
            self.chat_application_service = ChatApplicationService(
                persistence=chat_history_service,
                system_prompt_builder=build_system_prompt,
                prompt_enricher=lambda value: brain.extend_prompt(value, self._brain, self.settings, self.client),
                worker_factory=StreamWorker,
                on_dispatch=self._dispatch_application_request,
                on_event=self._on_chat_application_event,
                event_publisher=chat_event_publisher,
                schedule=lambda callback: QTimer.singleShot(0, callback),
                cancel_provider=self._cancel_application_provider,
            )
        self.settings = load_settings()
        self._db_notes = self.chat_application_service.init_history()
        self.session_manager = session_manager or SessionManager(ChatSession)
        self.session_manager.set_runtime_callbacks(
            has_pending_work=self._session_has_pending_chat_work,
            dispose_callback=self._release_chat_session_resources,
        )
        self.chat_event_publisher = chat_event_publisher
        self._session_event_unsubscribe = self.session_manager.subscribe(
            self._publish_session_state_event
        )
        self.sessions = self.session_manager.sessions_by_character
        self.cur = self.session_manager.create_session(
            self.character_service.active_id(self.settings)
        )
        self.session_manager.activate_session(self.cur.session_id)
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
        self.client = HybridRouter(self.settings)
        self.game_mode = GameModeMonitor(self)
        self._game_mode_enabled = False
        self._game_mode_profile = COMPETITIVE_SAFE_MODE
        self._latest_game_frame = None
        self._vision_gate = FrameGate(policy_for(self.settings.get('vision_mode', 'economic')))
        self._vision_worker = None
        self._vision_session = None
        self._vision_last_note = ''
        self.game_audio_listener = None
        self._game_audio_alerts = {}
        self._game_prev_mic = False
        self._game_prev_wake = False
        self.tool_agent = ToolAgent(self.settings, DATA_DIR, ROOT)      # Computer Awareness + Unified Tool System (kira/tools)
        usage.install(self.settings)                                    # usage ledger + limits (kira/usage.py); never blocks start-up
        evidence_memory.configure(self.settings)                        # facts with provenance (kira/evidence_memory.py); never blocks start-up
        self._tool_plan = None             # tool plan of the message being answered (None = ordinary chat, nothing added to the prompt)
        self.ollama_client = OllamaClient.from_settings(self.settings)
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
        self.listener = None
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
        self._game_capture_timer.setInterval(int(self._vision_gate.policy.interval_seconds * 1000))
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

    # ---------- i18n helpers ----------
    def t(self, key, **kw):
        s = STR.get(self.settings.get("ui_lang", "fa"), STR["fa"]).get(key, key)
        return s.format(**kw) if kw else s

    def reg(self, setter, key):
        self._tr.append((setter, key))

    def retranslate(self):
        lang = self.settings.get("ui_lang", "fa")
        QApplication.setLayoutDirection(Qt.RightToLeft if lang == "fa" else Qt.LeftToRight)
        for setter, key in self._tr:
            setter(self.t(key))
        self.input.setPlaceholderText(self.t("input_ph"))
        if hasattr(self, "_menu_actions"):
            for action, key in zip(self._menu_actions, self.tab_keys):
                action.setText(self.t(key))
        self.setWindowTitle(f"Project {self.settings['assistant_name']}  {VERSION}")
        self.title.setText(f"Project {self.settings['assistant_name']}")
        self.set_status(*self._status[:1], **self._status[1])
        self.update_companion_btn()
        self.update_engine_label()
        self.refresh_tab_buttons()
        if hasattr(self, "help_page"):
            self.help_page.retranslate()
        if hasattr(self, "assistant_page"):
            self.assistant_page.retranslate()
        if hasattr(self, "preferences_page"):
            self.preferences_page.retranslate()
        if hasattr(self, "voice_page"):
            self.voice_page.retranslate()
        if hasattr(self, "appearance_page"):
            self.appearance_page.retranslate()
        if hasattr(self, "character_page"):
            self.character_page.retranslate()
        if hasattr(self, "_menu_actions"):
            for action, key in zip(self._menu_actions, self.tab_keys):
                action.setText(self.t(key))
    def on_voice_error(self, message):
        """Local voice failures are rate-limited so a broken model does not flood the chat."""
        now = time.monotonic()
        if now - getattr(self, "_voice_err_at", -1e9) < 600:
            return
        self._voice_err_at = now
        self.add_chat("error", message + "\n" + self.t("voice_err_hint"))

    # ---------- chat sessions (one independent conversation per character) ----------
    def apply_chat_theme(self):
        """Glass + neon colours of the chat in front (same glass, the character's own colours)."""
        theme = self.front.theme or self.theme_for_character(self.front.cid)
        self.chat_page.setStyleSheet(theme_mod.character_style(theme, getattr(self, "_effect", "off"), self.settings.get("appearance", {})))
        r, g, b = (int(theme["main"].lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
        for glow in self.glow_effects:
            appearance = self.settings.get("appearance", {})
            intensity = max(0, min(100, int(appearance.get("glow", 34))))
            glow.setBlurRadius(14 + intensity * 0.38)
            glow.setColor(QColor(r, g, b, round(54 + intensity * 0.92)))
        self._apply_neon_glow_effects(self.settings.get("appearance", {}))

    def greeting_text(self):
        profile = self.character_service.active(self.settings)
        if profile["id"] == "kira":
            return self.t("greeting")
        name = profile.get("name_fa") if self.settings.get("ui_lang", "fa") == "fa" else profile.get("name")
        if self.settings.get("ui_lang", "fa") == "fa":
            return f"سلام! من {name} هستم. {profile.get('description', '')}"
        return f"Hi! I'm {name}. {profile.get('description', '')}"

    def restore_history(self, limit=40):
        """Show the saved conversation of the CURRENT chat again after a restart (it is already used as model context)."""
        try:
            self._ensure_session_conversation(self.cur)
            history = self.chat_application_service.recent_messages(
                limit, character_id=self.cur.cid, conversation_id=self.cur.conversation_id
            )
        except Exception:
            history = []
        shown = 0
        for item in history:
            role = item.get("role")
            if role == "assistant":
                text = self.director.parse_reply(item.get("content", "")).text      # emotion tags never shown
            elif role == "user":
                text = item.get("content", "")
            else:
                continue
            if text.strip():
                self.add_chat(role, text)
                shown += 1
        if shown:
            self.add_chat("system", self.t("history_restored"))
        else:
            self.add_chat("assistant", self.greeting_text())

    def add_chat(self, kind, text, name=None, images=None):
        """Append one message bubble; direction is decided per line so Persian reads right-to-left.
        images: attachment dicts whose thumbnails are shown at the top of the bubble."""
        if name is None:
            name = {"user": self.t("you"), "assistant": self.active_character().get("name", "Character"),
                    "error": self.t("error"), "system": ""}.get(kind, "")
        ui_dir = "rtl" if self.settings.get("ui_lang", "fa") == "fa" else "ltr"
        extra = self.thumbnail_html(images)
        footer = self.chat_actions_html(kind, text)
        with bubble_accent(self.accent()):
            self.chat.append(message_html(kind, name, text, ui_dir, extra, footer))
        if getattr(self, "bubble", None) is not None:
            self.bubble.push(kind, name, text, ui_dir)
        bar = self.chat.verticalScrollBar()
        bar.setValue(bar.maximum())

    def update_mood_indicator(self):
        """Render the active character's current emotion as a custom neon face; chat-message emoji are untouched."""
        label = getattr(self, "mood_indicator", None)
        face_label = getattr(self, "mood_emotion_icon", None)
        if label is None or face_label is None:
            return
        self._sync_mood_character()

        face_map = {
            "neutral": "neutral", "happy": "happy", "sad": "sad", "angry": "angry",
            "fearful": "fearful", "disgusted": "disgusted", "surprised": "surprised",
            "curious": "curious", "proud": "proud", "arrogant": "smug", "smug": "smug",
            "playful": "playful", "teasing": "teasing", "tsundere": "angry", "bored": "bored",
            "frustrated": "angry", "affectionate": "affectionate", "flirty": "flirty",
            "shy": "shy", "embarrassed": "shy", "jealous": "jealous", "laughing": "laughing",
            "annoyed": "angry", "protective": "protective", "excited": "excited",
            "thinking": "curious", "calm": "calm", "hopeful": "hopeful",
            "disappointed": "sad", "lonely": "sad", "guilty": "sad", "grateful": "affectionate",
            "nostalgic": "soft", "confident": "proud", "confused": "surprised",
            "relieved": "relieved", "content": "calm",
        }
        emotion_colors = {
            "neutral": "#B9D4F5", "calm": "#8FE8F2", "content": "#8FE8F2",
            "happy": "#FFD36E", "excited": "#FFC45E", "laughing": "#FFE078",
            "hopeful": "#A9F0C2", "grateful": "#FF9CE5",
            "sad": "#72B9FF", "disappointed": "#72B9FF", "lonely": "#78A8EE",
            "guilty": "#9AAFEF", "nostalgic": "#B4A8FF",
            "angry": "#FF668C", "frustrated": "#FF718A", "annoyed": "#FF7A91",
            "tsundere": "#FF8AAE", "jealous": "#FF79B8",
            "fearful": "#B59BFF", "disgusted": "#A4D77D",
            "surprised": "#64E7FF", "confused": "#73DFFF", "curious": "#67DFFF",
            "thinking": "#75DDF8", "proud": "#C7A0FF", "arrogant": "#C7A0FF",
            "smug": "#C7A0FF", "confident": "#C7A0FF",
            "playful": "#FFAE78", "teasing": "#FF9CCB",
            "affectionate": "#FF87D2", "flirty": "#FF78C5",
            "shy": "#FF9FCB", "embarrassed": "#FFA0C8",
            "protective": "#80D9C2", "relieved": "#9BEAD7",
            "bored": "#A9B7D2",
        }

        try:
            state = mood.current()
            emotion = str(state.get("emotion", "neutral") or "neutral").lower()
            icon_name = face_map.get(emotion, "neutral")
            neon = emotion_colors.get(emotion, "#69E5FF")
            face_icon = make_icon(
                f"emotion_{icon_name}", normal=neon, hover=neon,
                checked=neon, disabled="#52617B",
            )
            face_label.setPixmap(face_icon.pixmap(QSize(30, 30)))
            face_label.setStyleSheet(
                "QLabel#moodEmotionIcon { background: rgba(12, 20, 43, 0.96); "
                f"border: 1px solid {neon}; border-radius: 11px; padding: 2px; }}"
            )
            glow = getattr(self, "_mood_emotion_glow", None)
            if glow is not None:
                glow_colour = QColor(neon)
                glow_colour.setAlpha(215)
                glow.setColor(glow_colour)

            # Behaviour and energy are represented by vector neon glyphs only.
            # Never place a plain Unicode emoji beside the neon emotion face.
            behaviour = str(state.get("behavior", "balanced"))
            energy = str(state.get("energy_label", "normal"))
            show_bolt = energy in {"active", "hyper"} or behaviour == "energetic"
            if show_bolt:
                bolt_colour = "#FFE36B" if energy == "hyper" else "#72F4FF"
                bolt = make_icon(
                    "energy_bolt", normal=bolt_colour, hover="#FFFFFF",
                    checked=bolt_colour, disabled="#52617B",
                )
                label.setPixmap(bolt.pixmap(QSize(23, 23)))
                label.setStyleSheet(
                    "QLabel#moodIndicator { background: rgba(22, 28, 65, 0.62); "
                    f"border: 1px solid {bolt_colour}; border-radius: 10px; padding: 2px; }}"
                )
                label.setVisible(True)
            else:
                label.clear()
                label.setVisible(False)
            intensity = int(state.get("intensity", 0))
            secondary = ", ".join(name for name, _ in state.get("secondary_emotions", [])[:2])
            tooltip = (
                f"احساس: {emotion} ({intensity}/100)\n"
                f"رفتار: {behaviour}\n"
                f"انرژی: {energy}"
            )
            if secondary:
                tooltip += f"\nاحساسات همراه: {secondary}"
            face_label.setToolTip(tooltip)
            label.setToolTip(tooltip)
        except Exception:                                    # noqa: BLE001 - the indicator must never break the window
            fallback = make_icon("emotion_neutral", normal="#B9D4F5", hover="#B9D4F5",
                                 checked="#B9D4F5", disabled="#52617B")
            face_label.setPixmap(fallback.pixmap(QSize(30, 30)))
            label.setText("")
            face_label.setToolTip("حال‌وهوای شخصیت فعال")

    def chat_actions_html(self, kind, text):
        """Neon icon chips with generous separation; labels stay in tooltips to keep the chat compact."""
        if kind not in ("assistant", "user") or not str(text or "").strip():
            return ""
        self._chat_action_seq += 1
        key = str(self._chat_action_seq)
        self._chat_action_texts[key] = str(text)
        # Keep action targets for all messages currently present in the chat view.
        actions = [
            ("copy", "⧉", "#8CF5FF", "#103A52", "#39DFFF", "کپی"),
            ("edit", "✎", "#E0C8FF", "#30214F", "#B18AFF", "ویرایش"),
        ]
        if kind == "assistant":
            actions.append(("speak", "♫", "#FFC0E9", "#4B2044", "#FF83D0", "خواندن"))
        cells = []
        for action, glyph, colour, background, border, tooltip in actions:
            cells.append(
                f'<td bgcolor="{background}" style="border:1px solid {border};border-radius:10px;'
                f'padding:4px 11px;">'
                f'<a href="kira-action://{action}/{key}" title="{tooltip}" '
                f'style="color:{colour};text-decoration:none;font-size:13pt;font-weight:700;">{glyph}</a>'
                f'</td>'
            )
        links = "".join(cells)
        return (
            '<table dir="rtl" align="right" border="0" cellspacing="9" cellpadding="0" '
            'style="margin-top:10px;border-top:1px solid #314968;padding-top:7px;">'
            f'<tr>{links}</tr></table>'
        )

    def handle_chat_link(self, url):
        """Handle local message actions while preserving normal external links."""
        if url.scheme() == "kira-action":
            action = url.host()
            key = url.path().strip("/")
            text = self._chat_action_texts.get(key)
            if text is None:
                return
            if action == "copy":
                QApplication.clipboard().setText(text)
                self.set_status("st_ready")
            elif action == "edit":
                self.input.setText(text)
                self.input.setFocus()
                self.input.moveCursor(QTextCursor.End)
            elif action == "speak":
                # Speaker.speak() owns cancellation/replacement of the previous session.
                self.speaker.speak(text)
            return
        if url.scheme() in ("http", "https", "mailto"):
            QDesktopServices.openUrl(url)

    def thumbnail_html(self, images):
        parts = []
        for a in images or []:
            if a.get("kind") != "image":
                continue
            img = QImage()
            if not img.loadFromData(base64.b64decode(a["b64"])):
                continue
            img = img.scaledToWidth(min(220, img.width()), Qt.SmoothTransformation)
            self._att_seq += 1
            key = f"kira-att://{self._att_seq}"
            self.chat.document().addResource(QTextDocument.ImageResource, QUrl(key), img)
            parts.append(f'<p style="margin:0 0 6px 0;"><img src="{key}" width="{img.width()}" height="{img.height()}"></p>')
        return "".join(parts)

    def on_input_changed(self, text):
        """Typed text flows in its own direction (Persian right-to-left, English left-to-right)."""
        ui_dir = "rtl" if self.settings.get("ui_lang", "fa") == "fa" else "ltr"
        d = detect_direction(text, ui_dir)
        self.input.setLayoutDirection(Qt.RightToLeft if d == "rtl" else Qt.LeftToRight)

    @front_only
    def set_status(self, key, **kw):
        self._status = (key, kw)
        self.status.setText(self.t(key, **kw))

    # ---------- navigation / responsive layout ----------
    def go_tab(self, index):
        self.tabs.setCurrentIndex(index)
        self._sync_nav()

    def _sync_nav(self, _index=None):
        i = self.tabs.currentIndex()
        for index, button in enumerate(getattr(self, "nav_buttons", [])):
            button.setChecked(i == self._nav_icon_map[index][1])
        self.save_btn.setVisible(i != 0)            # the chat page needs no Save button
        if hasattr(self, "voice_page") and i == self.tab_keys.index("tab_voice"):
            self.refresh_voice_caps()               # Refresh local-only speech status

    def resizeEvent(self, event):
        super().resizeEvent(event)
        card = getattr(self, "avatar_card", None)
        if card is not None:                         # narrow window: give the whole width to the conversation
            card.setVisible(self.width() >= 640)
            card.setFixedWidth(max(200, min(300, int(self.width() * 0.30))))

    # ---------- UI building ----------
    def row(self, form, key, widget):
        lab = QLabel()
        self.reg(lab.setText, key)
        form.addRow(lab, widget)
        return widget

    def group(self, key):
        box = QGroupBox()
        self.reg(box.setTitle, key)
        form = QFormLayout(box)
        form.setLabelAlignment(Qt.AlignLeading)
        form.setHorizontalSpacing(8)
        form.setVerticalSpacing(5)
        return box, form

    def page(self, *boxes):
        host = QWidget()
        lay = QVBoxLayout(host)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(6)
        for b in boxes:
            lay.addWidget(b)
        lay.addStretch()
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setWidget(host)
        return sc

    FIELD_LIMITS = {"spin": 110, "slider": 280, "combo": 240, "combo_edit": 340, "line": 520}

    def tidy_forms(self):
        """Short fields (numbers, choices, sliders) keep a size that fits their content; long text fields keep the room they need.
        Nothing stretches to the end of the window for no reason."""
        lim = self.FIELD_LIMITS
        for i in range(1, self.tabs.count()):                          # page 0 is the chat: left as it is
            page = self.tabs.widget(i)
            for w in page.findChildren(QSpinBox) + page.findChildren(QDoubleSpinBox):
                w.setMaximumWidth(lim["spin"])
            for w in page.findChildren(QSlider):
                w.setMaximumWidth(lim["slider"])
            for w in page.findChildren(QComboBox):
                w.setMaximumWidth(lim["combo_edit"] if w.isEditable() else lim["combo"])
            for form in page.findChildren(QFormLayout):
                form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
                for r in range(form.rowCount()):
                    item = form.itemAt(r, QFormLayout.FieldRole)
                    widget = item.widget() if item is not None else None
                    if isinstance(widget, QLineEdit):
                        widget.setMaximumWidth(lim["line"])

    def icon_button(self, name, checkable=False):
        """Small neon icon button using the active character's own accent colours."""
        b = QToolButton()
        cid = self.character_service.active_id(self.settings)
        profile = self.character_service.all_profiles(self.settings).get(cid, {})
        palette = self.theme_for_character(cid, profile)
        b.setProperty("kiraIconName", name)
        b.setIcon(make_icon(name, normal=palette["second"], hover="#FFFFFF",
                            checked=palette["main"], disabled="#52617B"))
        b.setIconSize(QSize(20, 20))
        b.setCheckable(checkable)
        b.setCursor(Qt.PointingHandCursor)
        b.setFocusPolicy(Qt.NoFocus)
        return b

    def refresh_navigation_icons(self):
        """Keep shared navigation glyphs in sync when the active character changes."""
        cid = self.character_service.active_id(self.settings)
        profile = self.character_service.all_profiles(self.settings).get(cid, {})
        palette = self.theme_for_character(cid, profile)
        for button, (name, _tab_index) in zip(getattr(self, "nav_buttons", []), getattr(self, "_nav_icon_map", [])):
            button.setIcon(make_icon(name, normal=palette["second"], hover="#FFFFFF",
                                     checked=palette["main"], disabled="#52617B"))
        menu_button = getattr(self, "menu_btn", None)
        if menu_button is not None:
            menu_button.setIcon(make_icon("menu", normal=palette["second"], hover="#FFFFFF",
                                          checked=palette["main"], disabled="#52617B"))
        for action, (name, _tab_index) in zip(getattr(self, "_menu_actions", []), getattr(self, "_nav_icon_map", [])):
            action.setIcon(make_icon(name, normal=palette["second"], hover="#FFFFFF",
                                     checked=palette["main"], disabled="#52617B"))
        badge = getattr(self, "route_badge", None)
        if badge is not None:
            badge.setIcon(make_icon("chevron_up", normal=palette["second"], hover="#FFFFFF",
                                    checked=palette["main"], disabled="#52617B"))
        if hasattr(self, "_refresh_icon_glow"):
            self._refresh_icon_glow()

    def build_chat_tab(self):
        page = QWidget()
        self.chat_page = page
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(8)
        # --- character tabs: one tab (= one independent conversation) per character
        self.char_tabs = QFrame()
        self.char_tabs.setObjectName("charTabs")
        self.char_tabs_row = QHBoxLayout(self.char_tabs)
        self.char_tabs_row.setContentsMargins(2, 0, 2, 0)
        self.char_tabs_row.setSpacing(8)
        self.char_tab_group = QButtonGroup(self)
        self.char_tab_group.setExclusive(True)
        self.char_tab_buttons = {}
        outer.addWidget(self.char_tabs)
        body = QHBoxLayout()
        body.setSpacing(10)
        outer.addLayout(body, 1)
        root = body
        # --- dedicated avatar area (same PNG and loader; the view keeps the image's aspect ratio)
        self.avatar_card = QFrame()
        self.avatar_card.setObjectName("avatarCard")
        av = QVBoxLayout(self.avatar_card)
        av.setContentsMargins(8, 8, 8, 10)
        av.setSpacing(4)
        self.avatar = KiraAvatar(self.animator, view="card")
        self.avatar.setMinimumSize(150, 190)
        self.avatar.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        av.addWidget(self.avatar, 1)
        self.tagline = QLabel()
        self.tagline.setObjectName("hint")
        self.tagline.setAlignment(Qt.AlignCenter)
        self.reg(self.tagline.setText, "tagline")
        self.status = QLabel()
        self.status.setObjectName("status")
        self.status.setAlignment(Qt.AlignCenter)
        self.status.setWordWrap(True)
        av.addWidget(self.tagline)
        av.addWidget(self.status)
        self.avatar_card.setFixedWidth(250)
        root.addWidget(self.avatar_card)
        # --- chat card: compact header, conversation, composer
        chat_card = QFrame()
        chat_card.setObjectName("chatCard")
        cv = QVBoxLayout(chat_card)
        cv.setContentsMargins(12, 8, 12, 10)
        cv.setSpacing(6)
        self.chat_header = ChatHeader(self.icon_button("user", True), parent=chat_card)
        self.title = self.chat_header.title
        self.mood_emotion_icon = self.chat_header.mood_emotion_icon
        self.mood_indicator = self.chat_header.mood_indicator
        self.companion_btn = self.chat_header.companion_btn
        self.companion_btn.clicked.connect(self.toggle_companion)
        cv.addWidget(self.chat_header)
        self.chat_stack = QStackedWidget()                 # one read-only chat view per character (created in make_session_view)
        cv.addWidget(self.chat_stack, 1)
        self.chat_composer = ChatComposer(
            self,
            chat_input_factory=ChatInput,
            route_chip_factory=RouteChip,
            code_chat_factory=CodeChat,
            make_icon=make_icon,
            story_mode=STORY_MODE,
            competitive_safe_mode=COMPETITIVE_SAFE_MODE,
            parent=chat_card,
        )
        composer = self.chat_composer
        cv.addWidget(self.chat_composer)
        root.addWidget(chat_card, 1)
        self.glow_effects = []                             # neon glow around the composer (colour follows the character); not on the animated avatar: an effect would re-render it every frame
        for widget in (composer,):
            glow = QGraphicsDropShadowEffect(widget)
            glow.setBlurRadius(30)
            glow.setOffset(0, 0)
            glow.setColor(QColor(143, 107, 255, 150))
            widget.setGraphicsEffect(glow)
            self.glow_effects.append(glow)
        self.tabs.addTab(page, "")

    def build_assistant_section(self):
        """Host the independent assistant settings page and bind application actions."""
        ollama = self.settings.get("providers", {}).get("ollama", {})
        self.assistant_page = AssistantPage(
            self.settings,
            self.t,
            model_combo_factory=ModelCombo,
            num_ctx=clamp_num_ctx(ollama.get("num_ctx", DEFAULT_NUM_CTX)),
            num_predict=clamp_num_predict(ollama.get("num_predict", DEFAULT_NUM_PREDICT)),
            keep_alive=str(ollama.get("keep_alive", DEFAULT_KEEP_ALIVE)),
            parent=self,
        )
        # Compatibility aliases keep existing persistence/controller code stable while
        # the remaining settings orchestration is extracted in later steps.
        for name in (
            "name", "persona", "modes_chk", "temp", "model", "url", "use_qwen_btn",
            "num_ctx", "num_predict", "keep_alive", "conn_btn", "load_btn",
            "unload_btn", "speed_btn", "conn_lbl",
        ):
            setattr(self, name, getattr(self.assistant_page, name))

        self.assistant_page.test_connection_requested.connect(self.test_connection)
        self.assistant_page.load_model_requested.connect(self.load_local_model)
        self.assistant_page.unload_model_requested.connect(self.unload_local_model)
        self.assistant_page.speed_test_requested.connect(self.speed_test)
        self.tabs.addTab(self.assistant_page, "")

    def build_voice_tab(self):
        """Compose the independent Voice page and connect its intent signals."""
        self.voice_page = VoicePage(self.settings, self.t, parent=self)
        self.voice_page.voice_enabled_requested.connect(self.set_voice_enabled)
        self.voice_page.choose_whisper_folder_requested.connect(self.choose_local_whisper_folder)
        self.voice_page.download_whisper_requested.connect(self.download_local_whisper_model)
        self.voice_page.autosave_requested.connect(self.autosave_voice)
        self.tabs.addTab(self.voice_page, "")
        self.fill_mic_devices(str(self.settings.get("mic_device") or ""))
        self.fill_output_devices(str(self.settings.get("output_device") or ""))
        self.refresh_voice_caps()

    def set_local_voice_option(self, key, enabled):
        self.settings[key] = bool(enabled)
        self.save_now()

    def choose_local_asr_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "پوشه‌ی مدل STT را انتخاب کن", str(Path.home()))
        if not folder:
            return
        self.local_asr_path_edit.setText(folder)
        self.settings["local_voice_asr_model"] = folder
        self.save_now()
        self.refresh_local_voice_status()

    def download_local_qwen_model(self):
        model_id = str(self.local_asr_path_edit.text() or "").strip() or "Qwen/Qwen3-ASR-0.6B"
        if Path(model_id).expanduser().is_dir():
            self.local_voice_status.setText("این مدل از قبل روی سیستم وجود دارد.")
            self.refresh_local_voice_status()
            return
        if "/" not in model_id:
            self.local_voice_status.setText("شناسه مخزن Hugging Face را به شکل owner/repository وارد کن.")
            return
        self.local_voice_status.setText("در حال آماده‌سازی موتور Qwen و دانلود مدل از Hugging Face؛ ممکن است چند گیگابایت باشد…")
        from . import local_voice
        self._run_local_voice_task(lambda: local_voice.install_and_download_qwen_asr(model_id),
                                   self.local_asr_download_btn, self._on_local_qwen_downloaded)

    def _on_local_qwen_downloaded(self, result):
        ok, value = result
        if not ok:
            self.local_voice_status.setText(f"دانلود مدل Qwen ناموفق بود: {value}")
            return
        model_id = str(self.local_asr_path_edit.text() or "").strip() or "Qwen/Qwen3-ASR-0.6B"
        self.settings["local_voice_asr_model"] = model_id
        self.local_asr_path_edit.setText(model_id)
        self.save_now()
        self.refresh_local_voice_status()
        from . import local_voice
        self.local_voice_status.setText(
            f"Qwen نصب و فعال شد.\nمسیر مدل: {value}\nمحل ذخیره مدل‌ها: {local_voice.cache_directory()}"
        )

    def choose_local_whisper_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "پوشه مدل Whisper را انتخاب کن", str(Path.home()))
        if not folder:
            return
        self.voice_page.whisper.setCurrentText(folder)
        self.settings["whisper_model"] = folder
        self.save_now()
        self.local_voice_status.setText(f"مدل Whisper از سیستم انتخاب شد: {folder}")

    def download_local_whisper_model(self):
        value = str(self.voice_page.whisper.currentText() or "").strip()
        if value.casefold() == "qwen/qwen3-asr-0.6b":
            self.local_asr_path_edit.setText(value)
            self.local_voice_status.setText("در حال نصب موتور Qwen ASR و دانلود مدل محلی…")
            from . import local_voice
            self._run_local_voice_task(
                lambda: local_voice.install_and_download_qwen_asr(value),
                self.voice_page.whisper_download_btn, self._on_local_qwen_downloaded
            )
            return
        if Path(value).expanduser().is_dir():
            self.local_voice_status.setText("این مدل Whisper از قبل روی سیستم وجود دارد.")
            return
        aliases = {
            "tiny": "Systran/faster-whisper-tiny",
            "base": "Systran/faster-whisper-base",
            "small": "Systran/faster-whisper-small",
            "medium": "Systran/faster-whisper-medium",
            "large-v3": "Systran/faster-whisper-large-v3",
            "large-v3-turbo": "mobiuslabsgmbh/faster-whisper-large-v3-turbo",
        }
        repo_id = aliases.get(value, value)
        if "/" not in repo_id:
            self.local_voice_status.setText("برای دانلود، یک شناسه Hugging Face معتبر انتخاب کن.")
            return
        from . import local_voice
        self.local_voice_status.setText("در حال نصب موتور faster-whisper و دانلود مدل…")
        self._run_local_voice_task(lambda: local_voice.install_and_download_whisper(repo_id),
                                   self.voice_page.whisper_download_btn, self._on_whisper_downloaded)

    def _on_whisper_downloaded(self, result):
        ok, value = result
        if not ok:
            self.local_voice_status.setText(f"دانلود مدل STT ناموفق بود: {value}")
            return
        self.settings["whisper_model"] = str(value)
        self.voice_page.whisper.setCurrentText(str(value))
        self.save_now()
        from . import local_voice
        self.local_voice_status.setText(
            f"Whisper نصب و فعال شد.\nمسیر مدل: {value}\nمحل ذخیره مدل‌ها: {local_voice.cache_directory()}"
        )

    def download_local_tts_model(self):
        repo_id = str(self.local_tts_model_path.text() or "").strip()
        if "/" not in repo_id or "\\" in repo_id:
            self.local_voice_status.setText("شناسه مخزن Piper در Hugging Face را در کادر مدل TTS وارد کن.")
            return
        from . import local_voice
        self.local_voice_status.setText("در حال نصب Piper و دانلود صدای انتخاب‌شده…")
        self._run_local_voice_task(lambda: local_voice.install_and_download_piper_voice(repo_id),
                                   self.local_tts_download_btn, self._on_local_tts_downloaded)

    def _on_local_tts_downloaded(self, result):
        ok, value = result
        if not ok:
            self.local_voice_status.setText(f"دانلود مدل TTS ناموفق بود: {value}")
            return
        try:
            candidates = sorted(Path(value).rglob("*.onnx"))
            if not candidates:
                raise RuntimeError("در مخزن دانلودشده فایل Piper ONNX پیدا نشد.")
            self._install_piper_voice(candidates[0])
            from . import local_voice
            self.local_voice_status.setText(
                f"Piper نصب شد و صدا فعال شد: {candidates[0].name}\n"
                f"مسیر فایل: {candidates[0]}\nمحل ذخیره مدل‌ها: {local_voice.cache_directory()}"
            )
        except Exception as exc:
            self.local_voice_status.setText(f"نصب مدل TTS ناموفق بود: {type(exc).__name__}: {exc}")

    def apply_local_whisper_model(self):
        value = self.local_whisper_path.text().strip() or "small"
        self.settings["whisper_model"] = value
        if hasattr(self, "whisper"):
            if self.voice_page.whisper.findText(value) < 0:
                self.voice_page.whisper.addItem(value)
            self.voice_page.whisper.setCurrentText(value)
        self.save_now()
        self.add_chat("system", "مدل STT محلی به‌روزرسانی شد.")

    def choose_local_tts_model(self):
        path, _ = QFileDialog.getOpenFileName(self, "مدل Piper ONNX", str(Path.home()), "Piper ONNX (*.onnx)")
        if path:
            self._install_piper_voice(Path(path))

    def _install_piper_voice(self, source):
        source = Path(source).expanduser().resolve()
        if not source.is_file() or source.suffix.lower() != ".onnx":
            QMessageBox.warning(self, "مدل TTS", "فایل انتخاب‌شده باید Piper ONNX باشد.")
            return
        metadata = Path(str(source) + ".json")
        if not metadata.is_file():
            sibling = source.with_suffix(".json")
            metadata = sibling if sibling.is_file() else metadata
        if not metadata.is_file():
            QMessageBox.warning(self, "مدل TTS", "فایل پیکربندی کنار مدل (.onnx.json یا .json) پیدا نشد.")
            return
        try:
            target_dir = DATA_DIR / "voice_models"
            target_dir.mkdir(parents=True, exist_ok=True)
            target = target_dir / source.name
            if source.resolve() != target.resolve():
                shutil.copy2(source, target)
            target_meta = Path(str(target) + ".json")
            if metadata.resolve() != target_meta.resolve():
                shutil.copy2(metadata, target_meta)
            self.settings["local_voice_tts_model"] = str(target)
            self.local_tts_model_path.setText(str(target))
            self.save_now()
            self.refresh_local_voice_status()
            self.api_add_status.setText("مدل Piper به پوشه‌ی داده‌ی Kira کپی شد و برای TTS انتخاب شد.")
        except OSError as exc:
            QMessageBox.warning(self, "مدل TTS", str(exc))

    def import_local_model(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "معرفی مدل به Kira", str(Path.home()),
            "Model files (*.gguf *.onnx *.bin *.safetensors *.pt *.pth *.json);;All files (*)"
        )
        if not path:
            path = QFileDialog.getExistingDirectory(self, "یا پوشه‌ی مدل را انتخاب کن", str(Path.home()))
        if not path:
            return
        self._import_local_model_path(Path(path))

    def _import_local_model_path(self, source):
        source = Path(source).expanduser().resolve()
        if source.is_dir():
            gguf = sorted(source.glob("*.gguf"))
            onnx = sorted(source.glob("*.onnx"))
            if gguf:
                source = gguf[0]
            elif onnx:
                self._install_piper_voice(onnx[0])
                return
            elif (source / "model.bin").is_file():
                self.local_whisper_path.setText(str(source))
                self.apply_local_whisper_model()
                return
            elif (source / "config.json").is_file():
                try:
                    config_text = (source / "config.json").read_text(encoding="utf-8", errors="replace").lower()
                except OSError:
                    config_text = ""
                try:
                    config_data = json.loads((source / "config.json").read_text(encoding="utf-8", errors="replace"))
                except (OSError, ValueError, TypeError):
                    config_data = {}
                model_type = str(config_data.get("model_type") or "").lower()
                architectures = " ".join(str(x) for x in (config_data.get("architectures") or [])).lower()
                signature = " ".join((model_type, architectures, source.name.lower()))
                if any(token in signature for token in ("whisper", "qwen3asr", "qwen_asr", "speechrecognition", "speech_to_text", "audioencoderdecoder")):
                    self.local_asr_path_edit.setText(str(source))
                    self.settings["local_voice_asr_model"] = str(source)
                    self.save_now()
                    self.refresh_local_voice_status()
                    return
                if any(token in signature for token in ("causallm", "forcausallm", "textgeneration", "llama", "qwen3for")):
                    QMessageBox.information(self, "مدل Chat شناسایی شد",
                        "این پوشه یک مدل متنی Hugging Face است، اما Ollama مستقیماً پوشه‌ی Transformers را وارد نمی‌کند. نسخه‌ی GGUF همین مدل را انتخاب کن.")
                    return
                category, ok = QInputDialog.getItem(
                    self, "نوع مدل", "معماری مدل از روی فایل‌هایش قطعی نبود؛ نوع واقعی را انتخاب کن.",
                    ["STT · Qwen3-ASR", "STT · Whisper", "TTS · Piper ONNX", "Chat · GGUF"], 0, False)
                if not ok:
                    return
                if category.startswith("STT · Qwen"):
                    self.local_asr_path_edit.setText(str(source))
                    self.settings["local_voice_asr_model"] = str(source)
                    self.save_now()
                    self.refresh_local_voice_status()
                    return
                if category.startswith("STT · Whisper"):
                    self.local_whisper_path.setText(str(source))
                    self.apply_local_whisper_model()
                    return
                QMessageBox.information(self, "معرفی مدل", "برای TTS فایل Piper ONNX و برای Chat فایل GGUF را انتخاب کن.")
                return
            else:
                QMessageBox.warning(self, "مدل شناسایی نشد", "در پوشه، فایل GGUF، Piper ONNX، model.bin یا config.json پیدا نشد.")
                return

        if source.name.lower().endswith(".onnx.json"):
            candidate = Path(str(source)[:-5])
            if candidate.is_file():
                source = candidate
        if source.suffix.lower() == ".gguf":
            self._create_ollama_model(source)
        elif source.suffix.lower() == ".onnx":
            self._install_piper_voice(source)
        elif source.name.lower() == "model.bin":
            self.local_whisper_path.setText(str(source.parent))
            self.apply_local_whisper_model()
        elif source.suffix.lower() in (".json", ".safetensors", ".pt", ".pth"):
            self._import_local_model_path(source.parent)
        else:
            QMessageBox.warning(self, "مدل شناسایی نشد", "پسوند فایل پشتیبانی نمی‌شود. GGUF برای Chat، Piper ONNX برای TTS و پوشه‌ی مدل برای STT را انتخاب کن.")

    def _create_ollama_model(self, source):
        if not shutil.which("ollama"):
            QMessageBox.warning(self, "Ollama", "Ollama روی سیستم پیدا نشد.")
            return
        name = re.sub(r"[^a-zA-Z0-9._-]+", "-", source.stem.lower()).strip("-._")[:48] or "imported-model"
        self.import_model_btn.setEnabled(False)
        self.api_add_status.setText(f"در حال وارد کردن {source.name} به Ollama…")

        def work():
            target = DATA_DIR / "ollama_import"
            target.mkdir(parents=True, exist_ok=True)
            modelfile = target / f"{name}.Modelfile"
            escaped = source.as_posix().replace('"', '\\"')
            modelfile.write_text(f'FROM "{escaped}"\n', encoding="utf-8")
            result = subprocess.run(["ollama", "create", name, "-f", str(modelfile)],
                                    capture_output=True, text=True, timeout=1800, check=False)
            if result.returncode:
                raise RuntimeError((result.stderr or result.stdout or "ollama create failed")[-3000:])
            return name

        self._model_import_worker = TaskWorker(work)
        self._model_import_worker.done.connect(self.on_local_model_imported)
        self._model_import_worker.finished.connect(lambda: setattr(self, "_model_import_worker", None))
        self._model_import_worker.start()

    def on_local_model_imported(self, result):
        self.import_model_btn.setEnabled(True)
        ok, value = result
        if not ok:
            self.api_add_status.setText("✕ واردکردن مدل ناموفق بود: " + str(value))
            return
        model = str(value)
        if hasattr(self, "model"):
            if self.model.findText(model) < 0:
                self.model.addItem(model)
            self.model.setCurrentText(model)
        self.settings["model"] = model
        self.settings.setdefault("providers", {}).setdefault("ollama", {})["model"] = model
        route_model.ensure_routes(self.settings)
        route_model.add_ollama_models(self.settings, [model])
        self.save_now()
        self.refresh_route_list()
        self.refresh_unified_models()
        self.api_add_status.setText(f"✓ مدل «{model}» به Ollama اضافه شد.")

    def select_local_asr_model(self, index):
        combo = getattr(self, "local_asr_model_list", None)
        if combo is None or index < 0:
            return
        value = str(combo.itemData(index) or "").strip()
        if not value:
            return
        self.local_asr_path_edit.setText(value)
        self.settings["local_voice_asr_model"] = value
        self.save_now()
        self.refresh_local_voice_status()

    def select_local_tts_model(self, index):
        combo = getattr(self, "local_tts_model_list", None)
        if combo is None or index < 0:
            return
        value = str(combo.itemData(index) or "").strip()
        self.local_tts_model_path.setText(value)
        self.settings["local_voice_tts_model"] = value
        self.save_now()
        self.refresh_local_voice_status()

    def refresh_local_voice_status(self):
        try:
            from . import local_voice
            asr_model = str(self.settings.get("local_voice_asr_model") or "Qwen/Qwen3-ASR-0.6B")
            tts_model = str(self.settings.get("local_voice_tts_model") or "")
            discovered = local_voice.discover_cached_models()

            asr_combo = getattr(self, "local_asr_model_list", None)
            if asr_combo is not None:
                asr_combo.blockSignals(True)
                asr_combo.clear()
                asr_entries = discovered.get("asr", [])
                if not any(item.get("id") == asr_model for item in asr_entries):
                    asr_combo.addItem(f"{asr_model} · هنوز در کش پیدا نشد", asr_model)
                for item in asr_entries:
                    asr_combo.addItem(f"{item['id']} · دانلودشده", item["id"])
                selected = next((i for i in range(asr_combo.count())
                                 if str(asr_combo.itemData(i)) == asr_model), 0)
                asr_combo.setCurrentIndex(selected)
                asr_combo.blockSignals(False)

            tts_combo = getattr(self, "local_tts_model_list", None)
            if tts_combo is not None:
                tts_combo.blockSignals(True)
                tts_combo.clear()
                tts_combo.addItem("Mana Persian Piper · صدای پیش‌فرض", "")
                for item in discovered.get("tts", []):
                    tts_combo.addItem(f"{item['name']} · دانلودشده", item["path"])
                selected = next((i for i in range(tts_combo.count())
                                 if str(tts_combo.itemData(i) or "") == tts_model), 0)
                tts_combo.setCurrentIndex(selected)
                tts_combo.blockSignals(False)

            state = local_voice.status(tts_model)
            asr_loaded = bool(state["asr_loaded"] and state.get("asr_model") == asr_model)
            tts_loaded = bool(state["tts_loaded"] and (
                (tts_model and state.get("tts_model") and Path(state["tts_model"]).resolve() == Path(tts_model).expanduser().resolve())
                or (not tts_model and state.get("tts_model") == "bundled")
            ))
            asr_cached = any(item.get("id") == asr_model for item in discovered.get("asr", []))
            asr = "پکیج Python نصب است" if state["asr_installed"] else "پکیج Python نصب نیست"
            asr += " · فایل‌های مدل در کش موجود است" if asr_cached else " · فایل‌های مدل هنوز دانلود نشده"
            asr += " · همین مدل در حافظه است" if asr_loaded else " · مدل هنوز بارگذاری نشده"
            if state.get("asr_error"):
                asr += " · " + state["asr_error"]
            tts = "Piper در دسترس است" if state["tts_installed"] else "Piper نصب نیست"
            tts += " · همین صدا بارگذاری شده" if tts_loaded else " · صدای انتخابی هنوز بارگذاری نشده"
            if state.get("tts_error"):
                tts += " · " + state["tts_error"]
            selected_tts = tts_model or "Mana Persian Piper · صدای فارسی پیش‌فرض"
            self.local_voice_status.setText(
                f"STT · Qwen3-ASR: {asr}\nمدل STT: {asr_model}\n"
                f"TTS · Piper: {tts}\nمدل TTS: {selected_tts}\n"
                f"مدل‌های Piper مستقل: {len(discovered.get('tts', []))}\n"
                f"کش مدل‌ها: {local_voice.cache_directory()}"
            )
        except Exception as exc:
            self.local_voice_status.setText(f"بررسی موتورهای صوتی ناموفق بود: {type(exc).__name__}: {exc}")

    def _run_local_voice_task(self, fn, button, callback):
        worker = getattr(self, "_local_voice_worker", None)
        if worker is not None and worker.isRunning():
            return
        button.setEnabled(False)
        if hasattr(self, "local_voice_progress"):
            self.local_voice_progress.show()
        worker = TaskWorker(fn)
        self._local_voice_worker = worker
        def completed(result):
            button.setEnabled(True)
            if hasattr(self, "local_voice_progress"):
                self.local_voice_progress.hide()
            callback(result)

        def worker_finished():
            if self._local_voice_worker is worker:
                self._local_voice_worker = None
            if getattr(self, "_close_after_local_voice", False):
                self._close_after_local_voice = False
                QTimer.singleShot(0, self.close)

        worker.done.connect(completed)
        worker.finished.connect(worker_finished)
        worker.start()

    def load_local_asr(self):
        from . import local_voice
        model_name = str(self.settings.get("local_voice_asr_model") or "Qwen/Qwen3-ASR-0.6B")
        self._run_local_voice_task(lambda: local_voice.load_asr(model_name), self.local_asr_load_btn, self._on_local_asr_loaded)

    def _on_local_asr_loaded(self, result):
        ok, value = result
        if ok:
            self.local_voice_status.setText("Qwen3-ASR با موفقیت بارگذاری شد. تشخیص گفتار محلی آماده است.")
        else:
            self.local_voice_status.setText(f"بارگذاری Qwen3-ASR ناموفق بود: {value}")
        self.refresh_local_voice_status()

    def copy_local_voice_log(self):
        text = self.local_voice_status.text().strip()
        if text:
            QApplication.clipboard().setText(text)

    def test_local_tts(self):
        from . import local_voice
        self._run_local_voice_task(
            lambda: local_voice.synthesize_persian(
                "سلام، من کیرا هستم. این صدای فارسی محلی من است.",
                self.settings.get("local_voice_tts_model", "")
            ),
            self.local_tts_test_btn, self._on_local_tts_tested
        )

    def test_local_stt(self):
        listener = getattr(self, "_local_stt_test_listener", None)
        if listener is not None and listener.isRunning():
            listener.stop()
            self.local_stt_test_btn.setText("تست STT")
            self.local_voice_status.setText("آزمایش STT متوقف شد.")
            return

        from .listener import Listener
        model_name = str(self.settings.get("whisper_model") or "small")
        language = str(self.settings.get("stt_language") or "fa")
        listener = Listener(
            model_name, language, self,
            sensitivity=int(self.settings.get("mic_sensitivity", 100)),
            barge_in=False, settings=self.settings,
        )
        self._local_stt_test_listener = listener
        listener.heard.connect(self._on_local_stt_test_heard)
        listener.error.connect(self._on_local_stt_test_error)
        listener.state.connect(self._on_local_stt_test_state)
        listener.finished.connect(lambda current=listener: self._on_local_stt_test_finished(current))
        self.local_stt_test_btn.setText("توقف تست STT")
        self.local_voice_status.setText("در حال آماده‌سازی میکروفن؛ صحبت کن تا متن تشخیص‌داده‌شده نمایش داده شود.")
        listener.start()

    def _on_local_stt_test_state(self, state):
        labels = {
            "loading": "در حال آماده‌سازی موتور STT…",
            "listening": "میکروفن آماده است؛ صحبت کن…",
            "hearing": "صدایت دریافت شد؛ در حال ضبط…",
            "transcribing": "در حال تبدیل گفتار به متن…",
        }
        if state in labels:
            self.local_voice_status.setText(labels[state])

    def _on_local_stt_test_heard(self, text):
        listener = getattr(self, "_local_stt_test_listener", None)
        if listener is not None:
            listener.stop()
        self.local_voice_status.setText(f"نتیجه تست STT: {text}")

    def _on_local_stt_test_error(self, message):
        self.local_voice_status.setText(f"تست STT ناموفق بود: {message}")
        listener = getattr(self, "_local_stt_test_listener", None)
        if listener is not None:
            listener.stop()

    def _on_local_stt_test_finished(self, listener):
        if getattr(self, "_local_stt_test_listener", None) is listener:
            self._local_stt_test_listener = None
        if hasattr(self, "local_stt_test_btn"):
            self.local_stt_test_btn.setText("تست STT")

    def _on_local_tts_tested(self, result):
        ok, value = result
        if not ok:
            # Keep the actionable synthesis error visible; a status refresh here used
            # to overwrite it immediately with the generic installed/not-loaded text.
            self.local_voice_status.setText(f"تولید صدای Piper ناموفق بود: {value}")
            return
        try:
            if not isinstance(value, (bytes, bytearray)) or not value.startswith(b"RIFF"):
                raise RuntimeError("موتور TTS خروجی WAV معتبر تولید نکرد.")
            test_path = DATA_DIR / "voice_cache" / "local_persian_test.wav"
            test_path.parent.mkdir(parents=True, exist_ok=True)
            test_path.write_bytes(value)
            self._local_tts_test_active = False
            self.speaker.play_file(str(test_path))
            self._local_tts_test_active = True
            model = str(self.settings.get("local_voice_tts_model") or "Mana Persian Piper · صدای پیش‌فرض")
            self.local_voice_status.setText(
                f"تولید WAV موفق بود · مدل: {model} · حجم: {len(value):,} بایت\nدر انتظار شروع پخش از دستگاه خروجی…"
            )
        except Exception as exc:
            self._local_tts_test_active = False
            self.local_voice_status.setText(f"ساخت یا پخش فایل آزمایشی ناموفق بود: {type(exc).__name__}: {exc}")

    def _on_local_tts_playback_started(self):
        if self._local_tts_test_active:
            self.local_voice_status.setText("تولید WAV موفق بود · پخش TTS شروع شد.")

    def _on_local_tts_playback_finished(self):
        if self._local_tts_test_active:
            self._local_tts_test_active = False
            self.local_voice_status.setText("تست TTS موفق بود: صدا کامل پخش شد.")

    def _on_local_tts_playback_error(self, message):
        if self._local_tts_test_active:
            self._local_tts_test_active = False
            self.local_voice_status.setText(f"تولید صدا موفق بود، اما پخش شکست خورد: {message}")

    def _on_local_tts_playback_cancelled(self):
        if self._local_tts_test_active:
            self._local_tts_test_active = False
            self.local_voice_status.setText("تست TTS متوقف شد؛ پخش کامل نشد.")

    # ---- voice: devices, supported controls, autosave ----
    def fill_output_devices(self, current):
        self.voice_page.out_device.clear()
        self.voice_page.out_device.addItem(self.t("dev_default"), "")
        try:
            from PySide6.QtMultimedia import QMediaDevices
            seen = set()
            for dev in QMediaDevices.audioOutputs():
                name = dev.description()
                if name and name not in seen:
                    seen.add(name)
                    self.voice_page.out_device.addItem(name, name)
        except Exception:                                      # noqa: BLE001 - no audio backend: only the default entry
            pass
        i = self.voice_page.out_device.findData(current)
        self.voice_page.out_device.setCurrentIndex(i if i >= 0 else 0)

    def fill_mic_devices(self, current):
        self.voice_page.mic_device.clear()
        self.voice_page.mic_device.addItem(self.t("dev_default"), "")
        try:
            import sounddevice as sd
            seen = set()
            for dev in sd.query_devices():
                name = str(dev.get("name") or "")
                if dev.get("max_input_channels", 0) > 0 and name and name not in seen:
                    seen.add(name)
                    self.voice_page.mic_device.addItem(name, name)
        except Exception:                                      # noqa: BLE001 - sounddevice missing: only the default entry
            pass
        i = self.voice_page.mic_device.findData(current)
        self.voice_page.mic_device.setCurrentIndex(i if i >= 0 else 0)

    def refresh_voice_caps(self):
        """State the local-only speech policy in the Voice page."""
        self.voice_page.voice_caps_note.setText("میکروفن و بلندگو با STT/TTS محلی کار می‌کنند؛ هیچ صدای ابری یا آنلاین استفاده نمی‌شود.")

    def collect_voice_settings(self):
        s = self.settings
        s.update({"voice_rate": self.voice_page.rate.value(), "voice_volume": self.voice_page.volume.value() / 100.0,
                  "output_device": self.voice_page.out_device.currentData() or "", "mic_device": self.voice_page.mic_device.currentData() or "",
                  "mic_gain": self.voice_page.mic_gain.value(), "mic_sensitivity": self.voice_page.mic_sens.value()})

    def autosave_voice(self):
        """Voice sliders / devices are saved as soon as they are changed (the Save button is not needed for them)."""
        self.collect_voice_settings()
        self.apply_character_voice_settings()
        self.save_now()

    def show_voice_routes(self):
        """Open the local STT model controls in Connections."""
        self.go_tab(self.tab_keys.index("tab_ai"))
        if hasattr(self, "local_model_tabs"):
            self.local_model_tabs.setCurrentIndex(1)

    def set_route_view(self, index):
        if hasattr(self, "local_model_tabs") and int(index) in (1, 2):
            self.local_model_tabs.setCurrentIndex(int(index))

    def on_voice_note(self, message):
        """Show local ASR fallback and warmup notes without flooding the conversation."""
        now = time.monotonic()
        last = getattr(self, "_voice_note_at", {})
        if now - last.get(message, -999) > 60:
            last[message] = now
            self._voice_note_at = last
            self.add_chat("system", "🎙️ " + message)

    def build_characters_tab(self):
        """Compose the independent Characters page and delegate actions to the host."""
        self.character_page = CharactersPage(
            self.settings,
            self.t,
            base_traits=BASE_TRAITS,
            moods=MOODS,
            parent=self,
        )
        page = self.character_page
        page.character_selected.connect(self.select_character)
        page.add_character_requested.connect(self.add_character)
        page.edit_character_requested.connect(self.edit_character)
        page.delete_character_requested.connect(self.delete_character)
        page.choose_theme_color_requested.connect(self.choose_character_theme_color)
        page.reset_theme_color_requested.connect(self.reset_character_theme_color)
        page.preview_requested.connect(
            lambda mood: self.animator.set_expression(mood, hold=8)
        )
        page.open_sounds_requested.connect(self.open_sounds)
        page.save_requested.connect(lambda: self.save_character_settings(silent=True))
        page.save_personality_requested.connect(self.save_personality_profile)
        self.tabs.addTab(page, "")
        self.refresh_character_choices()
        self.refresh_character_card()
        self.refresh_personality_controls()
    def build_personality_tab(self):
        """Compatibility entry point; personality controls are owned by CharactersPage."""
        return self.character_page.character_subtabs.widget(1)
    def refresh_character_controls(self):
        cid = self.character_service.active_id(self.settings)
        voice = (self.settings.get("character_voice") or {}).get(cid) or {}
        self.character_page.char_voice_rate.blockSignals(True)
        self.character_page.char_voice_rate.setValue(int(voice.get("voice_rate", self.settings.get("voice_rate", 0))))
        self.character_page.char_voice_rate.blockSignals(False)
        self.character_page.char_voice_volume.blockSignals(True)
        self.character_page.char_voice_volume.setValue(round(float(voice.get("voice_volume", self.settings.get("voice_volume", 0.9))) * 100))
        self.character_page.char_voice_volume.blockSignals(False)
        resources = (self.settings.get("character_resources") or {}).get(cid) or {}
        for widget, key in ((self.character_page.char_skills_edit, "skills"), (self.character_page.char_mcp_edit, "mcp"),
                            (self.character_page.char_connectors_edit, "connectors")):
            widget.blockSignals(True)
            value = resources.get(key) or []
            widget.setText(", ".join(value) if isinstance(value, (list, tuple)) else str(value))
            widget.blockSignals(False)
        notes = (self.settings.get("character_notes") or {}).get(cid) or ""
        if hasattr(self.character_page, "character_notes_edit"):
            self.character_page.character_notes_edit.blockSignals(True)
            self.character_page.character_notes_edit.setPlainText(str(notes))
            self.character_page.character_notes_edit.blockSignals(False)
        self.apply_character_voice_settings()

    def _flush_character_autosave(self):
        timer = getattr(self, "_character_save_timer", None)
        if timer is not None and timer.isActive():
            timer.stop()
            self.save_character_settings(silent=True)

    def save_character_settings(self, silent=False):
        cid = self.character_service.active_id(self.settings)
        self.settings.setdefault("character_voice", {})[cid] = {
            "voice_rate": self.character_page.char_voice_rate.value(),
            "voice_volume": self.character_page.char_voice_volume.value() / 100.0,
        }
        def split(value):
            return [part.strip() for part in re.split(r"[,;\\n]+", value or "") if part.strip()]
        self.settings.setdefault("character_resources", {})[cid] = {
            "skills": split(self.character_page.char_skills_edit.text()),
            "mcp": split(self.character_page.char_mcp_edit.text()),
            "connectors": split(self.character_page.char_connectors_edit.text()),
        }
        if hasattr(self.character_page, "character_notes_edit"):
            self.settings.setdefault("character_notes", {})[cid] = self.character_page.character_notes_edit.toPlainText().strip()
        self.apply_character_voice_settings()
        self.save_now()

    def apply_character_voice_settings(self):
        """Give the speaker an isolated settings snapshot for the active character."""
        cid = self.character_service.active_id(self.settings)
        override = (self.settings.get("character_voice") or {}).get(cid) or {}
        effective = dict(self.settings)
        effective.update({k: v for k, v in override.items() if k in ("voice_rate", "voice_volume")})
        if getattr(self, "speaker", None) is not None:
            self.speaker.settings = effective

    def refresh_personality_controls(self):
        if not getattr(getattr(self, "character_page", None), "personality_sliders", None):
            return
        self.refresh_character_controls()
        traits = self.character_traits(self.active_character().get("id", "kira")) or BASE_TRAITS
        for key, slider in self.character_page.personality_sliders.items():
            slider.blockSignals(True)
            slider.setValue(int(round(float(traits.get(key, BASE_TRAITS.get(key, 0.5))) * 100)))
            slider.blockSignals(False)

    def save_personality_profile(self, silent=False):
        profile = self.active_character()
        cid = profile.get("id", "kira")
        traits = {key: slider.value() / 100.0 for key, slider in self.character_page.personality_sliders.items()}
        try:
            self.settings.setdefault("character_traits", {})[cid] = traits
            mood.set_active_character(cid, traits)
            if hasattr(self.character_page, "character_notes_edit"):
                self.settings.setdefault("character_notes", {})[cid] = self.character_page.character_notes_edit.toPlainText().strip()
            self.save_character_settings(silent=True)
            self.refresh_personality_controls()
            if not silent:
                self.save_now()
                self.add_chat("system", self.t("character_traits_saved", name=profile.get("name", cid)))
            return True
        except Exception as exc:                            # noqa: BLE001
            if not silent:
                QMessageBox.warning(self, self.t("character_error_title"), str(exc))
            return False

    def refresh_character_choices(self):
        current = self.character_service.active_id(self.settings)
        self.character_page.character_combo.blockSignals(True)
        self.character_page.character_combo.clear()
        profiles = self.character_service.all_profiles(self.settings)
        for cid in ("kira", "ren", "mika"):
            if cid in profiles:
                p = profiles[cid]
                self.character_page.character_combo.addItem(p.get("name_fa", p["name"]) + " · " + p["name"], cid)
        for cid, p in profiles.items():
            if cid not in ("kira", "ren", "mika"):
                self.character_page.character_combo.addItem(p.get("name_fa", p["name"]) + " · " + p["name"], cid)
        self.character_page.character_combo.setCurrentIndex(max(0, self.character_page.character_combo.findData(current)))
        self.character_page.character_combo.blockSignals(False)
        self.character_page.character_edit_btn.setEnabled(current != "kira")
        self.character_page.character_delete_btn.setEnabled(current != "kira")
        self._refresh_character_theme_preview()

    def _refresh_character_theme_preview(self):
        if not hasattr(self.character_page, "character_theme_color_preview"):
            return
        cid = self.character_service.active_id(self.settings)
        colour = self.theme_for_character(cid)["main"]
        self.character_page.character_theme_color_preview.setText(colour)
        self.character_page.character_theme_color_preview.setStyleSheet(
            f"QLabel {{ background: {colour}; color: white; border: 1px solid rgba(255,255,255,0.5); "
            "border-radius: 7px; padding: 5px; }"
        )

    def choose_character_theme_color(self):
        cid = self.character_service.active_id(self.settings)
        current = QColor(self.theme_for_character(cid)["main"])
        selected = QColorDialog.getColor(current, self, "رنگ تم شخصیت")
        if not selected.isValid():
            return
        self.settings.setdefault("character_theme_colors", {})[cid] = selected.name()
        for session in self.sessions.values():
            session.theme = self.theme_for_character(session.cid)
        self._refresh_character_theme_preview()
        self.apply_chat_theme()
        self.refresh_navigation_icons()
        self._refresh_icon_glow()
        self.save_now()

    def reset_character_theme_color(self):
        cid = self.character_service.active_id(self.settings)
        self.settings.setdefault("character_theme_colors", {}).pop(cid, None)
        for session in self.sessions.values():
            session.theme = self.theme_for_character(session.cid)
        self._refresh_character_theme_preview()
        self.apply_chat_theme()
        self.refresh_navigation_icons()
        self._refresh_icon_glow()
        self.save_now()

    def refresh_character_card(self, character_id=None):
        profile = self.character_service.all_profiles(self.settings).get(character_id or self.character_service.active_id(self.settings), self.character_service.all_profiles(self.settings).get("kira", {}))
        image_name = str(profile.get("image") or "").strip()
        pixmap = QPixmap()
        if image_name:
            image_path = ROOT / image_name
            try:
                if image_path.suffix == ".b64":
                    image_bytes = base64.b64decode(image_path.read_text(encoding="ascii").strip(), validate=True)
                    pixmap.loadFromData(image_bytes)
                else:
                    pixmap.load(str(image_path))
            except (OSError, ValueError):
                pixmap = QPixmap()
        pixmap = self._fit_portrait(pixmap)
        self.character_page.character_portrait.setPixmap(pixmap)
        self.character_page.character_description.setText(profile.get("description", ""))

    def _fit_portrait(self, pixmap):
        """Fill the portrait frame without stretching: pictures whose proportions differ from the frame are
        cropped (centred, biased toward the face). A picture that already fits (Kira's SVG) is left untouched."""
        if pixmap.isNull():
            return pixmap
        size = self.character_page.character_portrait.size()
        if abs(pixmap.width() / pixmap.height() - size.width() / size.height()) < 0.03:
            return pixmap
        x, y, w, h = avatar_art.cover_crop(pixmap.width(), pixmap.height(), size.width(), size.height())
        crop = pixmap.copy(int(round(x)), int(round(y)), int(round(w)), int(round(h)))
        return crop.scaled(size, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)

    def apply_character_art(self):
        """Chat page + floating companion show the active character: Kira's own animated PNG, or the character's
        full-body picture (a profile without one falls back to Kira's art). Called at start-up and on every change."""
        profile = self.character_service.active(self.settings)
        self.animator.set_character_art(self.character_service.avatar_file(profile, ROOT))
        self.animator.rig.intensity = float(self.settings.get("motion_strength", self.animator.rig.intensity)) * self.animator.motion_gain
        self.animator.touch()

    def select_character(self, index):
        character_id = self.character_page.character_combo.itemData(index)
        if not character_id:
            return
        if character_id != self.front.cid:
            self.switch_session(character_id)         # the character list in Settings and the tabs on the chat page are the same switch
            self.save_now()

    def add_character(self):
        name, ok = QInputDialog.getText(self, "شخصیت جدید", "نام:")
        if not ok or not name.strip():
            return
        description, ok = QInputDialog.getText(self, "شخصیت جدید", "توضیح کوتاه:")
        if not ok:
            return
        prompt, ok = QInputDialog.getMultiLineText(self, "شخصیت جدید", "دستور شخصیت و لحن:")
        if not ok:
            return
        cid = "custom_" + str(time.time_ns())
        profile = {"id": cid, "name": name.strip(), "name_fa": name.strip(), "gender": "unspecified",
                   "description": description.strip(), "image": "assets/characters/ren.svg", "prompt": prompt.strip()}
        self.settings.setdefault("characters", []).append(profile)
        self.settings.setdefault("character_voice", {}).setdefault(cid, {})
        self.settings.setdefault("character_notes", {}).setdefault(cid, "")
        self.settings.setdefault("character_resources", {}).setdefault(cid, {})
        self.sync_sessions()                           # a new tab with its own conversation
        self.switch_session(cid)
        self.save_now()

    def edit_character(self):
        cid = self.character_service.active_id(self.settings)
        if cid == "kira":
            return
        profile = dict(self.character_service.all_profiles(self.settings)[cid])
        name, ok = QInputDialog.getText(self, "ویرایش شخصیت", "نام:", QLineEdit.Normal, profile.get("name", ""))
        if not ok or not name.strip():
            return
        description, ok = QInputDialog.getText(self, "ویرایش شخصیت", "توضیح:", QLineEdit.Normal, profile.get("description", ""))
        if not ok:
            return
        prompt, ok = QInputDialog.getMultiLineText(self, "ویرایش شخصیت", "دستور شخصیت و لحن:", profile.get("prompt", ""))
        if not ok:
            return
        profile.update({"name": name.strip(), "name_fa": name.strip(), "description": description.strip(), "prompt": prompt.strip()})
        custom = self.settings.setdefault("characters", [])
        custom[:] = [x for x in custom if x.get("id") != cid]
        custom.append(profile)
        self.sync_sessions()
        self.apply_chat_theme()
        self.refresh_character_choices()
        self.refresh_character_card(cid)
        self.save_now()

    def delete_character(self):
        cid = self.character_service.active_id(self.settings)
        if cid == "kira":
            return
        if QMessageBox.question(self, "حذف شخصیت", "این شخصیت حذف شود؟") != QMessageBox.Yes:
            return
        if self.character_service.is_builtin(cid):
            hidden = self.settings.setdefault("deleted_character_ids", [])
            if cid not in hidden:
                hidden.append(cid)
        else:
            self.settings["characters"] = [x for x in self.settings.get("characters", []) if x.get("id") != cid]
        self.settings["active_character_id"] = "kira"
        for key in ("character_voice", "character_notes", "character_resources", "character_traits"):
            self.settings.get(key, {}).pop(cid, None)
        self.sync_sessions()                           # its tab (and conversation view) goes away
        self.switch_session("kira")
        self.save_now()

    def build_appearance_tab(self):
        """Compose the independent appearance page and connect controller actions."""
        self.appearance_page = AppearancePage(
            self.settings,
            self.t,
            glass_supported=winfx.supported(),
            parent=self,
        )
        self.appearance_page.appearance_apply_requested.connect(self.apply_appearance)
        self.appearance_page.choose_color_requested.connect(self.choose_appearance_color)
        self.appearance_page.reset_requested.connect(self.reset_appearance)
        self.tabs.addTab(self.appearance_page, "")
    def _set_appearance_color_preview(self, value):
        """Compatibility helper; AppearancePage owns its colour preview."""
        self.appearance_page.set_background_color(value)
    def choose_appearance_color(self):
        current = QColor(self.appearance_page.background_color)
        selected = QColorDialog.getColor(current, self, "رنگ پس‌زمینه")
        if selected.isValid():
            self.appearance_page.set_background_color(selected.name())
            self.schedule_appearance()
    def reset_appearance(self):
        page = self.appearance_page
        page.set_background_color("#0A0A1C")
        page.window_effect.setCurrentIndex(max(0, page.window_effect.findData("acrylic")))
        page.appearance_brightness.setValue(100)
        page.appearance_glow.setValue(58)
        page.appearance_transparency.setValue(28)
        page.schedule_appearance()
    def schedule_appearance(self, *_):
        page = getattr(self, "appearance_page", None)
        if page is not None:
            page.schedule_appearance()
    def apply_appearance(self, save=False):
        """Apply the current Appearance controls immediately; persist only after the short debounce."""
        if not hasattr(self, "appearance_page"):
            return
        previous = getattr(self, "_effect", "off")
        color = self.appearance_page.background_color or (self.settings.get("appearance") or {}).get("background_color", "#0A0A1C")
        appearance = {
            "background_color": color,
            "brightness": self.appearance_page.appearance_brightness.value(),
            "glow": self.appearance_page.appearance_glow.value(),
            "transparency": self.appearance_page.appearance_transparency.value(),
        }
        # Reduce the old high default once; subsequent values are entirely user-controlled.
        if not self.settings.get("appearance_glow_adjusted"):
            appearance["glow"] = min(int(appearance["glow"]), 18)
            self.appearance_page.appearance_glow.blockSignals(True)
            self.appearance_page.appearance_glow.setValue(appearance["glow"])
            self.appearance_page.appearance_glow.blockSignals(False)
            self.settings["appearance_glow_adjusted"] = True
        # One-time migration from the restrained glow to the Neon Shooter bloom level.
        # Preserve stronger user-selected values; only lift the old low default.
        if not self.settings.get("appearance_neon_shooter_v1"):
            if int(appearance["glow"]) < 42:
                appearance["glow"] = 58
            self.appearance_page.appearance_glow.blockSignals(True)
            self.appearance_page.appearance_glow.setValue(int(appearance["glow"]))
            self.appearance_page.appearance_glow.blockSignals(False)
            self.settings["appearance_neon_shooter_v1"] = True
        self.settings["appearance"] = appearance
        wanted = self.appearance_page.window_effect.currentData() or "acrylic"
        current = winfx.active_effect(wanted)
        self._effect = current
        set_glow_intensity(appearance["glow"] / 100.0)
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(build_style(current, appearance))
        if hasattr(self, "glow_effects"):
            self.apply_chat_theme()
        self._refresh_icon_glow()
        self._apply_neon_glow_effects(appearance)
        winfx.apply_effect(self.winId(), current)
        self.appearance_page.set_background_color(color)
        if (previous == "off") != (current == "off") and previous != current and getattr(self, "isVisible", lambda: False)():
            self.add_chat("system", "برای اعمال کامل حالت شیشه‌ای، برنامه را یک بار ببند و دوباره باز کن.")
        if save:
            save_settings(self.settings)

    def _apply_neon_glow_effects(self, appearance=None):
        """Bloom the glass panels and action controls without touching animated avatar widgets."""
        appearance = appearance if isinstance(appearance, dict) else (self.settings.get("appearance") or {})
        intensity = max(0, min(100, int(appearance.get("glow", 58))))
        cid = self.character_service.active_id(self.settings)
        palette = self.theme_for_character(cid, self.character_service.all_profiles(self.settings).get(cid, {}))
        if not hasattr(self, "_neon_widget_effects"):
            self._neon_widget_effects = {}

        # Panel borders are handled by the stylesheet; avoid effects on containers because
        # Qt may composite their child text and inputs into the shadow source.
        # Shadow effects on every settings button force Qt to re-render dozens of
        # controls. Keep the expensive bloom on the persistent primary actions only.
        targets = []
        for name in ("menu_btn", "mic_btn", "wake_btn", "voice_btn", "stop_btn",
                     "send_btn", "gen_stop_btn"):
            widget = getattr(self, name, None)
            if widget is not None:
                targets.append((widget, palette["second"], 10 + intensity * 0.12, 14 + intensity * 0.38))
        save_button = getattr(self, "save_btn", None)
        if save_button is not None:
            targets.append((save_button, palette["main"], 10 + intensity * 0.12, 14 + intensity * 0.34))

        for widget, colour, blur, alpha in targets:
            effect = self._neon_widget_effects.get(widget)
            if effect is None:
                effect = QGraphicsDropShadowEffect(widget)
                effect.setOffset(0, 0)
                widget.setGraphicsEffect(effect)
                self._neon_widget_effects[widget] = effect
            effect.setBlurRadius(blur)
            tint = QColor(colour)
            tint.setAlpha(round(alpha if widget.isEnabled() else alpha * 0.22))
            effect.setColor(tint)

    def _refresh_icon_glow(self):
        cid = self.character_service.active_id(self.settings)
        palette = self.theme_for_character(cid, self.character_service.all_profiles(self.settings).get(cid, {}))
        for button in self.findChildren(QToolButton):
            name = button.property("kiraIconName")
            if not name:
                continue
            button.setIcon(make_icon(name, normal=palette["second"], hover="#FFFFFF",
                                     checked=palette["main"], disabled="#52617B"))

    def build_general_tab(self):
        """Compose preferences and help pages; the preferences widget owns its controls."""
        self.preferences_page = PreferencesPage(
            self.settings,
            self.t,
            web_depths=tuple(websearch.DEPTHS.items()),
            about_rows=about.about_rows(VERSION),
            parent=self,
        )
        for name in (
            "ui_lang", "tavily_key", "web_depth", "web_fallback_chk", "web_test_btn",
            "restore_chat_btn", "memory_btn", "import_chat_btn", "about_labels",
        ):
            setattr(self, name, getattr(self.preferences_page, name))

        self.preferences_page.web_search_test_requested.connect(self.test_web_search)
        self.preferences_page.clear_history_requested.connect(self.clear_chat)
        self.preferences_page.restore_history_requested.connect(self.restore_cleared_chat)
        self.preferences_page.open_memory_requested.connect(self.open_memory_dialog)
        self.preferences_page.import_history_requested.connect(self.import_old_chat)

        subtabs = QTabWidget()
        subtabs.addTab(self.preferences_page, "")
        subtabs.addTab(self.build_help_tab(), "")
        self.general_subtabs = subtabs
        self.reg(lambda text: subtabs.setTabText(0, text), "tab_preferences")
        self.reg(lambda text: subtabs.setTabText(1, text), "tab_help")
        self.tabs.addTab(self.page(subtabs), "")

    def build_help_tab(self):
        """Build the standalone Help/About page; it owns its content and translations."""
        self.help_page = HelpPage(
            self.t,
            app_name=APP_NAME,
            version=VERSION,
            releases_url=RELEASES_URL,
            project_url=PROJECT_URL,
        )
        return self.help_page

    def build_mcp_registry_group(self, parent_layout):
        """Mount the independent MCP registry panel and connect application actions."""
        self.mcp_registry_panel = McpRegistryPanel(parent=self)
        self.mcp_registry_query = self.mcp_registry_panel.query_edit
        self.mcp_registry_search_btn = self.mcp_registry_panel.search_btn
        self.mcp_registry_list = self.mcp_registry_panel.results
        self.mcp_registry_add_btn = self.mcp_registry_panel.add_btn
        self.mcp_registry_refresh_btn = self.mcp_registry_panel.refresh_btn
        self.mcp_registry_status = self.mcp_registry_panel.status
        self.mcp_registry_panel.search_requested.connect(self.search_mcp_registry)
        self.mcp_registry_panel.add_requested.connect(self.add_mcp_registry_server)
        self.mcp_registry_panel.refresh_models_requested.connect(self.refresh_model_catalogs)
        parent_layout.addWidget(self.mcp_registry_panel)
        QTimer.singleShot(1200, self.search_mcp_registry)

    def search_mcp_registry(self):
        from .mcp.registry import RegistrySearchWorker
        worker = getattr(self, "_mcp_registry_worker", None)
        if worker is not None and worker.isRunning():
            return
        self.mcp_registry_panel.set_searching(True)
        self._mcp_registry_worker = RegistrySearchWorker(self.mcp_registry_panel.query(), self)
        self._mcp_registry_worker.completed.connect(self._on_mcp_registry_results)
        self._mcp_registry_worker.start()

    def _on_mcp_registry_results(self, records, error):
        self.mcp_registry_panel.show_results(records, error)

    def add_mcp_registry_server(self):
        record = self.mcp_registry_panel.selected_record()
        if record is None:
            self.mcp_registry_panel.set_status("اول یک سرور از فهرست انتخاب کن.")
            return
        from .mcp.registry import server_config
        try:
            name, cfg = server_config(record)
            path = DATA_DIR / "kira_mcp.json"
            raw = json.loads(path.read_text(encoding="utf-8-sig")) if path.is_file() else {}
            if not isinstance(raw, dict):
                raise ValueError("ساختار kira_mcp.json معتبر نیست")
            servers = raw.setdefault("servers", {})
            if name in servers:
                self.mcp_registry_panel.set_status(f"سرور «{name}» از قبل ثبت شده است.")
                return
            servers[name] = cfg
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
            hub = getattr(self.tool_agent, "mcp", None)
            if hub is not None:
                hub.refresh_async()
            self.mcp_registry_panel.set_status(f"سرور «{name}» ثبت شد؛ Kira در حال اتصال و کشف خودکار ابزارهاست.")
        except Exception as exc:
            self.mcp_registry_panel.set_status("افزودن سرور ناموفق بود: " + str(exc)[:240])

    def refresh_model_catalogs(self):
        if getattr(self, "_model_catalog_worker", None) is not None and self._model_catalog_worker.isRunning():
            return
        self.mcp_registry_panel.set_refreshing(True)
        self.mcp_registry_panel.set_status("در حال بررسی APIها و دریافت مدل‌های تازه…")
        try:
            providers = [
                (pid, dict(self.settings.get("providers", {}).get(pid, {})))
                for pid in api_manager.api_ids(self.settings)
                if self.settings.get("providers", {}).get(pid, {}).get("enabled", True)
            ]
            def refresh():
                results = []
                for pid, cfg in providers:
                    results.append((pid, api_manager.rediscover(pid, cfg, timeout=15)))
                return results
            self._model_catalog_worker = TaskWorker(refresh)
            self._model_catalog_worker.done.connect(self._on_model_catalog_refresh)
            self._model_catalog_worker.start()
            self.scan_ollama()
            self.refresh_local_voice_status()
        except Exception as exc:
            self.mcp_registry_panel.set_refreshing(False)
            self.mcp_registry_panel.set_status("تازه‌سازی کامل نشد: " + str(exc)[:200])

    def _on_model_catalog_refresh(self, result):
        self.mcp_registry_panel.set_refreshing(False)
        ok, value = result
        if not ok:
            self.mcp_registry_panel.set_status("دریافت مدل‌های API ناموفق بود: " + str(value)[:200])
            return
        updated = 0
        failed = []
        for pid, detection in value:
            if detection.ok:
                api_manager.apply_models(self.settings, pid, detection.models, detection.rate_limit)
                updated += len(detection.models)
            else:
                api_manager.apply_failure(self.settings, pid, detection)
                failed.append(pid)
        self.save_now()
        self.refresh_unified_models()
        self.refresh_api_table()
        suffix = ("؛ خطا در " + "، ".join(failed)) if failed else ""
        self.mcp_registry_panel.set_status(f"مدل‌های API تازه‌سازی شد: {updated} مدل از {len(value)} اتصال{suffix}.")

    def build_ai_tab(self):
        """Unified cloud/local model catalogue with advanced route and provider controls."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(7)

        # API keys in this section are checked for Chat capability only.
        add_box, list_box, det_box = self.build_api_boxes()
        layout.addWidget(add_box)

        import_row = QHBoxLayout()
        self.import_model_btn = QPushButton("＋ معرفی مدل از فایل یا پوشه‌ی سیستم")
        self.import_model_btn.setToolTip("فایل GGUF برای Chat، مدل CTranslate2/Qwen برای STT یا Piper ONNX برای TTS")
        self.import_model_btn.clicked.connect(self.import_local_model)
        import_row.addWidget(self.import_model_btn)
        import_row.addStretch(1)
        layout.addLayout(import_row)

        self.build_mcp_registry_group(layout)
        cloud_box, cloud_form = self.group("مدل‌های Chat Cloud")
        model_list = QListWidget()
        model_list.setAlternatingRowColors(True)
        model_list.setMinimumHeight(105)
        model_list.setMaximumHeight(170)
        model_list.itemChanged.connect(lambda item: self.on_cloud_model_item_changed("chat", item))
        self.cloud_model_lists = {"chat": model_list}
        cloud_form.addRow(model_list)
        layout.addWidget(cloud_box)

        local_box, local_form = self.group("مدل‌های Local")
        local_form.setContentsMargins(8, 6, 8, 6)
        local_form.setHorizontalSpacing(8)
        local_form.setVerticalSpacing(4)
        self.local_model_tabs = QTabWidget()
        self.local_model_tabs.setMaximumHeight(255)

        # Local Chat: Ollama remains the provider, but every installed model is listed here.
        local_chat = QWidget()
        local_chat_layout = QVBoxLayout(local_chat)
        local_chat_layout.setContentsMargins(3, 3, 3, 3)
        local_chat_layout.addWidget(self.build_ollama_group())
        self.local_model_list = QListWidget()
        self.local_model_list.setAlternatingRowColors(True)
        self.local_model_list.setMinimumHeight(90)
        self.local_model_list.setMaximumHeight(150)
        self.local_model_list.itemChanged.connect(self.on_local_chat_item_changed)
        local_chat_layout.addWidget(QLabel("مدل‌های چت نصب‌شده‌ی Ollama"))
        local_chat_layout.addWidget(self.local_model_list)
        self.route_scan_btn = QPushButton("یافتن مدل‌های نصب‌شده")
        self.route_scan_btn.clicked.connect(self.scan_ollama)
        local_chat_layout.addWidget(self.route_scan_btn)
        self.local_model_tabs.addTab(local_chat, "Chat")

        # Local STT: Qwen ASR and faster-whisper can use a downloaded local directory.
        local_stt = QWidget()
        local_stt_layout = QVBoxLayout(local_stt)
        local_stt_layout.setContentsMargins(2, 2, 2, 2)
        local_stt_layout.setSpacing(4)
        self.local_asr_chk = QCheckBox("استفاده از Qwen3-ASR محلی")
        self.local_asr_chk.setChecked(bool(self.settings.get("local_voice_asr", True)))
        self.local_asr_chk.toggled.connect(lambda on: self.set_local_voice_option("local_voice_asr", on))
        local_stt_layout.addWidget(self.local_asr_chk)
        self.local_asr_model_list = QComboBox()
        self.local_asr_model_list.setToolTip("مدل‌های STT موجود در کش Hugging Face")
        self.local_asr_model_list.setMaximumHeight(30)
        self.local_asr_model_list.currentIndexChanged.connect(self.select_local_asr_model)
        local_stt_layout.addWidget(QLabel("مدل‌های دانلودشده‌ی STT"))
        local_stt_layout.addWidget(self.local_asr_model_list)
        # Keep the optional custom path internally; the normal flow needs no manual path entry.
        self.local_asr_path_edit = QLineEdit(str(self.settings.get("local_voice_asr_model") or "Qwen/Qwen3-ASR-0.6B"))
        self.local_asr_path_edit.setVisible(False)
        self.local_asr_browse_btn = QPushButton("انتخاب پوشه")
        self.local_asr_browse_btn.clicked.connect(self.choose_local_asr_folder)
        asr_actions = QHBoxLayout()
        self.local_asr_download_btn = QPushButton("نصب خودکار Qwen + مدل")
        self.local_asr_download_btn.clicked.connect(self.download_local_qwen_model)
        self.local_asr_load_btn = QPushButton("بارگذاری مدل")
        self.local_asr_load_btn.clicked.connect(self.load_local_asr)
        asr_actions.addWidget(self.local_asr_download_btn)
        asr_actions.addWidget(self.local_asr_load_btn)
        local_stt_layout.addLayout(asr_actions)
        # Whisper selection and one-click installation are available in the main Voice settings above.
        self.local_whisper_path = QLineEdit(str(self.settings.get("whisper_model") or "small"))
        self.local_whisper_path.setVisible(False)
        self.local_model_tabs.addTab(local_stt, "STT")

        # Local TTS: bundled Persian Piper or a user-selected ONNX voice.
        local_tts = QWidget()
        local_tts_layout = QVBoxLayout(local_tts)
        local_tts_layout.setContentsMargins(2, 2, 2, 2)
        local_tts_layout.setSpacing(4)
        self.local_tts_chk = QCheckBox("استفاده از Piper محلی")
        self.local_tts_chk.setChecked(bool(self.settings.get("local_voice_tts", True)))
        self.local_tts_chk.toggled.connect(lambda on: self.set_local_voice_option("local_voice_tts", on))
        local_tts_layout.addWidget(self.local_tts_chk)
        self.local_tts_model_list = QComboBox()
        self.local_tts_model_list.setToolTip("صداهای Piper دانلودشده و صدای فارسی پیش‌فرض")
        self.local_tts_model_list.setMaximumHeight(30)
        self.local_tts_model_list.currentIndexChanged.connect(self.select_local_tts_model)
        local_tts_layout.addWidget(QLabel("مدل‌های دانلودشده‌ی TTS"))
        local_tts_layout.addWidget(self.local_tts_model_list)
        self.local_tts_model_path = QLineEdit(str(self.settings.get("local_voice_tts_model") or ""))
        self.local_tts_model_path.setPlaceholderText("مسیر فایل Piper ONNX یا شناسه مخزن Hugging Face؛ خالی = صدای پیش‌فرض")
        self.local_tts_model_path.setLayoutDirection(Qt.LeftToRight)
        tts_path_row = QHBoxLayout()
        tts_path_row.addWidget(self.local_tts_model_path, 1)
        self.local_tts_browse_btn = QPushButton("انتخاب ONNX")
        self.local_tts_browse_btn.clicked.connect(self.choose_local_tts_model)
        tts_path_row.addWidget(self.local_tts_browse_btn)
        self.local_tts_download_btn = QPushButton("نصب خودکار Piper + صدا")
        self.local_tts_download_btn.clicked.connect(self.download_local_tts_model)
        tts_path_row.addWidget(self.local_tts_download_btn)
        local_tts_layout.addLayout(tts_path_row)
        self.local_tts_test_btn = QPushButton("تست TTS")
        self.local_tts_test_btn.clicked.connect(self.test_local_tts)
        local_tts_layout.addWidget(self.local_tts_test_btn)
        self.local_model_tabs.addTab(local_tts, "TTS")

        self.local_voice_status = QLabel()
        self.local_voice_status.setWordWrap(True)
        self.local_voice_status.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.local_voice_status.setMaximumHeight(96)
        self.local_voice_status.setObjectName("hint")
        self.local_voice_copy_btn = QPushButton("کپی لاگ")
        self.local_voice_copy_btn.setMaximumWidth(90)
        self.local_voice_copy_btn.clicked.connect(self.copy_local_voice_log)
        self.local_voice_progress = QProgressBar()
        self.local_voice_progress.setRange(0, 0)
        self.local_voice_progress.setTextVisible(False)
        self.local_voice_progress.setMaximumHeight(7)
        self.local_voice_progress.hide()
        local_form.addRow(self.local_model_tabs)
        local_status_row = QHBoxLayout()
        local_status_row.addWidget(self.local_voice_status, 1)
        local_status_row.addWidget(self.local_voice_copy_btn)
        local_form.addRow(local_status_row)
        local_form.addRow(self.local_voice_progress)
        self.local_voice_box = local_box
        local_test_row = QHBoxLayout()
        self.local_stt_test_btn = QPushButton("تست STT")
        self.local_stt_test_btn.clicked.connect(self.test_local_stt)
        local_test_row.addWidget(self.local_stt_test_btn)
        local_test_row.addStretch(1)
        local_form.addRow(local_test_row)
        layout.addWidget(local_box)

        # Advanced controls remain available but are collapsed by default.
        self.connections_advanced_btn = QToolButton()
        self.connections_advanced_btn.setText("تنظیمات پیشرفته و مدیریت Providerها")
        self.connections_advanced_btn.setCheckable(True)
        self.connections_advanced_btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.connections_advanced_btn.setArrowType(Qt.RightArrow)
        self.connections_advanced_body = QWidget()
        advanced_layout = QVBoxLayout(self.connections_advanced_body)
        advanced_layout.setContentsMargins(0, 0, 0, 0)
        advanced_layout.addWidget(list_box)
        advanced_layout.addWidget(det_box)

        # RouteEditor owns route/failover controls; MainWindow only handles intents.
        self.route_editor = RouteEditor(
            self.settings,
            model_combo_factory=ModelCombo,
            parent=self,
        )
        for name in (
            "route_list", "route_manual_lbl", "failover_chk", "route_up_btn",
            "route_down_btn", "route_add_btn", "route_del_btn", "route_default_btn",
            "route_use_btn", "route_auto_btn", "route_provider_lbl", "route_model_edit",
            "route_enabled_chk", "route_timeout", "route_cooldown", "route_ctx",
            "route_predict", "route_status", "route_test_btn", "route_bench_btn",
            "route_bench_all_btn", "bench_out",
        ):
            setattr(self, name, getattr(self.route_editor, name))

        self.route_editor.selection_changed.connect(self.on_route_selected)
        self.route_editor.order_changed.connect(self.on_routes_reordered)
        self.route_editor.failover_changed.connect(self.on_failover_toggled)
        self.route_editor.move_requested.connect(self.move_selected)
        self.route_editor.add_requested.connect(self.add_route_dialog)
        self.route_editor.delete_requested.connect(self.delete_selected_route)
        self.route_editor.default_requested.connect(self.default_selected_route)
        self.route_editor.select_manual_requested.connect(
            lambda: self.select_route(self._selected_route_id() or "")
        )
        self.route_editor.select_auto_requested.connect(lambda: self.select_route(""))
        self.route_editor.test_requested.connect(self.test_selected_route)
        self.route_editor.benchmark_requested.connect(self.run_benchmark)
        self.route_editor.details_changed.connect(self.route_edit_changed)
        advanced_layout.addWidget(self.route_editor)

        self.connections_advanced_body.setVisible(False)
        self.connections_advanced_btn.toggled.connect(self.connections_advanced_body.setVisible)
        self.connections_advanced_btn.toggled.connect(
            lambda on: self.connections_advanced_btn.setArrowType(Qt.DownArrow if on else Qt.RightArrow)
        )
        layout.addWidget(self.connections_advanced_btn)
        layout.addWidget(self.connections_advanced_body)
        layout.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(page)
        self.tabs.addTab(scroll, "")
        self.refresh_route_list()
        self.refresh_api_table()
        self.refresh_unified_models()
        self.refresh_local_voice_status()

    def _make_model_list(self, kind, cloud=True):
        model_list = QListWidget()
        model_list.setAlternatingRowColors(True)
        model_list.setMinimumHeight(105)
        model_list.setMaximumHeight(170)
        model_list.setSelectionMode(QAbstractItemView.SingleSelection)
        if cloud:
            model_list.itemChanged.connect(lambda item, category=kind: self.on_cloud_model_item_changed(category, item))
        else:
            model_list.itemChanged.connect(self.on_local_chat_item_changed)
        return model_list

    def refresh_unified_models(self):
        """Populate the three cloud capability lists and the three local model lists."""
        if not hasattr(self, "cloud_model_lists"):
            return
        for widget in self.cloud_model_lists.values():
            widget.blockSignals(True)
            widget.clear()
        api_manager.ensure_registry(self.settings)
        free_only = str(self.settings.get("model_filter_mode") or "all") == "free"
        for pid, entry in api_manager.registry(self.settings).items():
            cfg = self.settings.get("providers", {}).get(pid, {})
            label = route_model.provider_label(pid, cfg)
            for mid, meta in (entry.get("models") or {}).items():
                if meta.get("status") == "unavailable" or meta.get("text") == "No":
                    continue
                low = str(mid).lower()
                if any(token in low for token in ("tts", "text-to-speech", "embedding", "whisper", "speech-to-text",
                                                   "speech", "transcription", "audio", "asr")):
                    continue
                if free_only and meta.get("free") is not True:
                    continue
                item = QListWidgetItem(f"{label}  ·  {mid}" + ("  · رایگان" if meta.get("free") is True else ""))
                item.setData(Qt.UserRole, {"provider": pid, "model": mid})
                item.setToolTip(f"Text: {meta.get('text') or 'Unknown'} | Vision: {meta.get('vision') or 'Unknown'} | Tools: {meta.get('tools') or 'Unknown'}")
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                enabled = any(r.get("provider") == pid and r.get("model") == mid and r.get("enabled")
                              for r in route_model.get_routes(self.settings))
                item.setCheckState(Qt.Checked if enabled else Qt.Unchecked)
                self.cloud_model_lists["chat"].addItem(item)
        for kind, widget in self.cloud_model_lists.items():
            if widget.count() == 0:
                if free_only:
                    message = "مدل رایگانِ تأییدشده‌ای پیدا نشد."
                else:
                    message = "برای نمایش مدل‌ها ابتدا API مربوط را اضافه و شناسایی کن."
                empty = QListWidgetItem(message)
                empty.setFlags(Qt.NoItemFlags)
                widget.addItem(empty)
            widget.blockSignals(False)

        if hasattr(self, "local_model_list"):
            self.local_model_list.blockSignals(True)
            self.local_model_list.clear()
            for route in route_model.get_routes(self.settings):
                if route.get("provider") != "ollama" or not route.get("model"):
                    continue
                item = QListWidgetItem(route["model"])
                item.setData(Qt.UserRole, route.get("id"))
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(Qt.Checked if route.get("enabled") else Qt.Unchecked)
                self.local_model_list.addItem(item)
            self.local_model_list.blockSignals(False)

    def on_cloud_model_item_changed(self, kind, item):
        if kind != "chat":
            return
        data = item.data(Qt.UserRole) or {}
        provider, model = data.get("provider"), data.get("model")
        if not provider or not model:
            return
        checked = item.checkState() == Qt.Checked
        try:
            api_manager.set_model_enabled(self.settings, provider, model, checked)
        except Exception as exc:
            self.api_add_status.setText("✕ " + str(exc))
        self._api_changed(provider)
        self.refresh_unified_models()

    def on_local_chat_item_changed(self, item):
        route_id = item.data(Qt.UserRole)
        if not route_id:
            return
        route_model.update_route(self.settings, route_id, enabled=item.checkState() == Qt.Checked)
        self.save_now()
        self.refresh_route_list()
        self.refresh_unified_models()

    def _discover_unified_api_key(self, key, account=""):
        """Detect chat-model capability only; audio never uses remote APIs."""
        return api_manager.detect(key, account)

    def api_add(self):
        if self._api_busy():
            return
        key = self.api_key_edit.text().strip()
        problem = api_manager.key_problem(key)
        if problem:
            self.api_add_status.setText("✕ " + problem)
            return
        self.api_add_btn.setEnabled(False)
        self.api_add_status.setText("در حال شناسایی مدل‌های Chat از API…")
        self._api_worker = TaskWorker(lambda: self._discover_unified_api_key(key))
        self._api_worker.done.connect(lambda result, k=key: self.on_api_detected(result, k))
        self._api_worker.start()

    def on_api_detected(self, result, key, account=""):
        self.api_add_btn.setEnabled(True)
        ok, detection = result
        if not ok:
            self.api_add_status.setText("✕ " + str(detection))
            return
        if detection and detection.state == "needs_account" and not account:
            account_id, accepted = QInputDialog.getText(self, "Cloudflare", "Account ID:")
            if accepted and account_id.strip():
                self.api_add_btn.setEnabled(False)
                self.api_add_status.setText("در حال تکمیل شناسایی Cloudflare…")
                self._api_worker = TaskWorker(lambda: self._discover_unified_api_key(key, account_id.strip()))
                self._api_worker.done.connect(lambda res, k=key, a=account_id.strip(): self.on_api_detected(res, k, a))
                self._api_worker.start()
            return

        chat_added = ""
        if detection and detection.ok:
            duplicate = api_manager.find_duplicate(self.settings, key)
            if not duplicate:
                try:
                    chat_added = api_manager.register(self.settings, detection, key)
                except ValueError as exc:
                    self.api_add_status.setText("✕ " + str(exc))
            else:
                chat_added = duplicate
        if chat_added:
            self._api_changed(chat_added)
            self.api_key_edit.clear()
            label = route_model.provider_label(chat_added, self.settings["providers"][chat_added])
            self.api_add_status.setText("✓ اتصال Chat ثبت شد: " + label)
        else:
            message = api_manager.describe_failure(detection) if detection else "هیچ مدل Chat قابل استفاده‌ای از این API شناسایی نشد."
            self.api_add_status.setText("✕ " + message + "؛ کلید ثبت نشد.")
        self.refresh_unified_models()

    def build_local_model_group(self):
        """Backwards-compatible name for the Route local-provider group."""
        return self.build_ollama_group()

    def build_ollama_group(self):
        """Host the Ollama settings widget and delegate its intents to the app controller."""
        self.ollama_panel = OllamaProviderPanel(self.settings, parent=self)
        self.route_ollama_enabled = self.ollama_panel.enabled
        self.ollama_url_edit = self.ollama_panel.url_edit
        self.ollama_edit_btn = self.ollama_panel.edit_btn
        self.ollama_save_btn = self.ollama_panel.save_btn
        self.ollama_cancel_btn = self.ollama_panel.cancel_btn
        self.ollama_panel.enabled_changed.connect(lambda *_: self.provider_changed())
        self.ollama_panel.cancel_requested.connect(lambda: self.ollama_edit_mode(False))
        self.ollama_panel.save_requested.connect(self.save_ollama_edit)
        return self.ollama_panel

    def collect_provider_settings(self):
        """Only the local Ollama switch lives in the form now; API keys / enabled flags are changed by the API Manager actions directly."""
        self.settings.setdefault("providers", {}).setdefault("ollama", {})["enabled"] = self.route_ollama_enabled.isChecked()
        route_model.ensure_routes(self.settings)

    def ollama_edit_mode(self, on):
        self.ollama_panel.set_edit_mode(bool(on), self.settings.get("ollama_url") if not on else None)

    def save_ollama_edit(self):
        url = self.ollama_url_edit.text().strip().rstrip("/")
        if not re.match(r"^https?://\S+$", url, re.I):
            self.route_status.setText("✕ آدرس Ollama باید با http:// یا https:// شروع شود.")
            return
        self.settings["ollama_url"] = url
        self.settings.setdefault("providers", {}).setdefault("ollama", {})["base_url"] = url
        self.url.setText(url)                                # same address as the Assistant tab
        self.save_now()
        self.ollama_edit_mode(False)
        self.route_status.setText("✓ آدرس Ollama ذخیره شد.")

    # ---------- API Manager ----------
    API_COLUMNS = ["Provider", "API Status", "مدل‌های قابل‌دسترسی", "مدل‌های فعال", "آخرین اعتبارسنجی", "اولویت", "فعال"]
    MODEL_COLUMNS = ["فعال", "Model ID", "Status", "Context Window", "Max Output", "Text", "Vision", "Tool Calling", "روی API دیگر هم"]
    STATUS_FA = {"valid": "✓ معتبر", "invalid": "✕ نامعتبر", "error": "⚠ خطا (بعداً دوباره امتحان کن)", "disabled": "غیرفعال",
                 "no key": "بدون کلید", "not validated yet": "هنوز اعتبارسنجی نشده"}

    def build_api_boxes(self):
        """Compose independent API credential form with the registered API/detail tables."""
        self.api_add_panel = ApiAddPanel(
            self.settings,
            filter_options=(
                ("all", "همه‌ی مدل‌ها"),
                ("free", "فقط مدل‌های رایگانِ تأییدشده"),
            ),
            parent=self,
        )
        self.api_key_edit = self.api_add_panel.key_edit
        self.api_account_edit = self.api_add_panel.account_edit
        self.api_add_btn = self.api_add_panel.add_btn
        self.model_filter = self.api_add_panel.model_filter
        self.api_add_status = self.api_add_panel.status
        self.api_add_panel.add_requested.connect(self.api_add)
        self.api_add_panel.filter_changed.connect(self.on_model_filter_changed)
        add_box = self.api_add_panel
        list_box, lf = self.group("Registered APIs")
        self.api_table = QTableWidget(0, len(self.API_COLUMNS))
        self.api_table.setHorizontalHeaderLabels(self.API_COLUMNS)
        self.api_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.api_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.api_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.api_table.verticalHeader().setVisible(False)
        self.api_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.api_table.setMinimumHeight(150)
        self.api_table.itemSelectionChanged.connect(self.show_api_details)
        lf.addRow(self.api_table)
        buttons = QHBoxLayout()
        self.api_btns = {}
        for key, text, fn in (("details", "View Details", self.show_api_details), ("refresh", "Refresh / Rediscover Models", lambda: self.api_refresh(self._api_selected())),
                              ("edit", "Edit", lambda: self.api_edit(self._api_selected())), ("toggle", "Enable / Disable", lambda: self.api_toggle(self._api_selected())),
                              ("delete", "Delete", lambda: self.api_delete(self._api_selected())), ("up", "▲", lambda: self.api_move(self._api_selected(), -1)),
                              ("down", "▼", lambda: self.api_move(self._api_selected(), 1))):
            btn = QPushButton(text)
            btn.clicked.connect(lambda checked=False, f=fn: f())
            self.api_btns[key] = btn
            buttons.addWidget(btn)
        lf.addRow(buttons)
        adv = QPushButton("افزودن Provider سفارشی / سرور محلی سازگار با OpenAI (پیشرفته)")
        adv.clicked.connect(self.add_provider_dialog)
        lf.addRow(adv)
        self.api_status = QLabel("")
        self.api_status.setWordWrap(True)
        lf.addRow(self.api_status)

        det_box, df = self.group("API Details")
        self.api_det_info = QLabel("یک API را از فهرست بالا انتخاب کن.")
        self.api_det_info.setWordWrap(True)
        self.api_det_info.setTextInteractionFlags(Qt.TextSelectableByMouse)
        df.addRow(self.api_det_info)
        self.api_models = QTableWidget(0, len(self.MODEL_COLUMNS))
        self.api_models.setHorizontalHeaderLabels(self.MODEL_COLUMNS)
        self.api_models.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.api_models.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.api_models.verticalHeader().setVisible(False)
        self.api_models.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.api_models.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.api_models.setMinimumHeight(200)
        self.api_models.itemChanged.connect(self.on_api_model_toggled)
        df.addRow(self.api_models)
        note = QLabel("هر چیزی که Provider گزارش نکرده «Unknown» یا «Not Available» نمایش داده می‌شود؛ هیچ عدد یا قابلیتی حدس زده نمی‌شود. "
                      "اولویت مدل‌ها همان ترتیب فهرست Route پایین صفحه است. بودن مدل در فهرست به معنی تضمین سهمیه نیست.")
        note.setObjectName("hint")
        note.setWordWrap(True)
        df.addRow(note)
        self._api_loading = False
        self._api_worker = None
        return add_box, list_box, det_box

    def on_model_filter_changed(self, *_):
        self.settings["model_filter_mode"] = self.model_filter.currentData() or "all"
        self.save_now()
        self.refresh_unified_models()

    def _api_selected(self):
        row = self.api_table.currentRow()
        item = self.api_table.item(row, 0) if row >= 0 else None
        return item.data(Qt.UserRole) if item else None

    def _api_busy(self):
        worker = getattr(self, "_api_worker", None)
        if worker is not None and worker.isRunning():
            self.api_status.setText("صبر کن؛ عملیات قبلی هنوز تمام نشده است.")
            return True
        return False

    def _api_changed(self, select=None, refresh_details=True):
        """After any change: reset cooldowns (a fixed key gets another chance), save, redraw."""
        self.client.reset_cooldowns()
        self.save_now()
        self.refresh_api_table(select)
        if hasattr(self, "cloud_model_lists"):
            self.refresh_unified_models()
        self.refresh_route_list()
        if not self.busy:
            self.set_badge("idle", self.client.preview_route())

    def refresh_api_table(self, select=None):
        api_manager.ensure_registry(self.settings)
        keep = select or self._api_selected()
        rows = api_manager.api_rows(self.settings)
        self._api_loading = True
        self.api_table.blockSignals(True)
        self.api_table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            service = "" if r["service"] in ("custom",) else f" · {r['service']}"
            cells = [f"{r['label']}  ({r['key']})" if r["key"] else r["label"], self.STATUS_FA.get(r["status"], r["status"]),
                     "Unknown" if r["accessible"] is None else str(r["accessible"]), str(r["active"]), api_manager.fmt_time(r["checked_at"]),
                     str(r["priority"]), "✓" if r["enabled"] else "—"]
            for c, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setData(Qt.UserRole, r["id"])
                if c == 1 and r["error"]:
                    item.setToolTip(r["error"])
                self.api_table.setItem(i, c, item)
        self.api_table.blockSignals(False)
        self._api_loading = False
        target = next((i for i, r in enumerate(rows) if r["id"] == keep), 0 if rows else -1)
        if target >= 0:
            self.api_table.selectRow(target)
        self.show_api_details()

    def show_api_details(self):
        pid = self._api_selected()
        self._api_loading = True
        self.api_models.blockSignals(True)
        self.api_models.setRowCount(0)
        have = bool(pid) and pid in self.settings.get("providers", {})
        for key, btn in self.api_btns.items():
            btn.setEnabled(have or key == "details")
        if not have:
            self.api_det_info.setText("یک API را از فهرست بالا انتخاب کن.")
            self.api_models.blockSignals(False)
            self._api_loading = False
            return
        d = api_manager.api_details(self.settings, pid)
        rl = d["rate_limit"]
        rl_text = ("\n    " + "\n    ".join(f"{k}: {v}" for k, v in sorted(rl.items())) + f"\n    (زمان گزارش: {api_manager.fmt_time(d['rate_limit_as_of'])})") if rl else "Not Available"
        self.api_det_info.setText(
            f"Provider: {d['label']}  ·  سرویس: {d['service']}  ·  کلید: {d['key'] or '—'}\n"
            f"Status: {self.STATUS_FA.get(d['status'], d['status'])}  ·  آخرین بررسی: {api_manager.fmt_time(d['checked_at'])}"
            + (f"\nآخرین خطا: {d['error']}" if d["error"] else "") +
            f"\nToken Usage: Not Available  ·  Remaining Quota: Not Available\nRate Limit: {rl_text}")
        self.api_models.setRowCount(len(d["models"]))
        for i, m in enumerate(d["models"]):
            check = QTableWidgetItem()
            check.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            check.setCheckState(Qt.Checked if m["enabled"] else Qt.Unchecked)
            check.setData(Qt.UserRole, m["id"])
            self.api_models.setItem(i, 0, check)
            status = {"available": "✓ در دسترس", "unavailable": "✕ دیگر در دسترس نیست", "unknown": "Unknown (هنوز بررسی نشده)"}.get(m["status"], m["status"])
            cells = [m["id"], status, "Not Available" if m["context"] is None else f"{m['context']:,}",
                     "Not Available" if m["max_output"] is None else f"{m['max_output']:,}", m["text"], m["vision"], m["tools"],
                     "، ".join(m["also_on"]) if m["also_on"] else "—"]
            for c, text in enumerate(cells, start=1):
                self.api_models.setItem(i, c, QTableWidgetItem(text))
        self.api_models.blockSignals(False)
        self._api_loading = False

    def on_api_model_toggled(self, item):
        if self._api_loading or item.column() != 0:
            return
        pid = self._api_selected()
        if not pid:
            return
        try:
            api_manager.set_model_enabled(self.settings, pid, item.data(Qt.UserRole), item.checkState() == Qt.Checked)
        except ValueError as exc:
            self.api_status.setText("✕ " + str(exc))
        QTimer.singleShot(0, lambda p=pid: self._api_changed(p))          # redraw after this signal has finished (the table is rebuilt)

    # ---- Add ----
    # ---- Refresh / Rediscover ----
    def api_refresh(self, pid, quiet=False):
        if not pid or pid not in self.settings.get("providers", {}) or self._api_busy():
            return
        cfg = dict(self.settings["providers"][pid])
        self.api_status.setText("در حال اعتبارسنجی و دریافت دوباره‌ی مدل‌ها…")
        self._api_worker = TaskWorker(lambda: api_manager.rediscover(pid, cfg))
        self._api_worker.done.connect(lambda result, p=pid, q=quiet: self.on_api_refreshed(p, result, q))
        self._api_worker.start()

    def on_api_refreshed(self, pid, result, quiet=False):
        if pid not in self.settings.get("providers", {}):
            return
        ok, det = result
        label = route_model.provider_label(pid, self.settings["providers"][pid])
        if not ok:
            det = api_manager.Detection("error", "", str(det))
        if det.ok:
            diff = api_manager.apply_models(self.settings, pid, det.models, det.rate_limit)
            msg = f"✓ {label}: {len(det.models)} مدل در دسترس"
            if diff["new"]:
                msg += f" · {len(diff['new'])} مدل جدید"
            if diff["gone"]:
                msg += f" · {len(diff['gone'])} مدل دیگر در دسترس نیست"
            self.api_status.setText(msg)
        else:
            api_manager.apply_failure(self.settings, pid, det)
            self.api_status.setText(f"{label}: " + api_manager.describe_failure(det))
        self._api_changed(pid)

    # ---- Edit ----
    def api_edit(self, pid):
        if not pid or pid not in self.settings.get("providers", {}) or self._api_busy():
            return
        cfg = self.settings["providers"][pid]
        service = api_manager.service_of(pid, cfg)
        custom = pid not in route_model.BUILTIN
        dlg = QDialog(self)
        dlg.setWindowTitle("Edit API")
        form = QFormLayout(dlg)
        name = QLineEdit(route_model.provider_label(pid, cfg))
        key = QLineEdit()
        key.setEchoMode(QLineEdit.Password)
        key.setPlaceholderText("کلید جدید (اختیاری) — خالی = کلید فعلی حفظ می‌شود")
        account = QLineEdit(str(cfg.get("account_id", "")))
        base = QLineEdit(str(cfg.get("base_url", "")))
        if custom:
            form.addRow("نام", name)
        form.addRow(f"API Key (فعلی: {api_manager.mask_key(cfg.get('api_key')) or '—'})", key)
        if service == "cloudflare":
            form.addRow("Account ID", account)
        if custom and service == "custom":
            form.addRow("Base URL", base)
        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.accepted.connect(dlg.accept)
        box.rejected.connect(dlg.reject)
        form.addRow(box)
        if dlg.exec() != QDialog.Accepted:
            return
        new_key = key.text().strip()
        fields = {"label": name.text() if custom else None, "account_id": (account.text() or None) if service == "cloudflare" else None,
                  "base_url": base.text() if (custom and service == "custom") else None}
        if not new_key:
            self.apply_api_edit(pid, fields, None, None)
            return
        problem = api_manager.key_problem(new_key)
        dup = api_manager.find_duplicate(self.settings, new_key)
        if problem or (dup and dup != pid):
            self.api_status.setText("✕ " + (problem or "این کلید قبلاً برای API دیگری ثبت شده است."))
            return
        test_cfg = {**cfg, "api_key": new_key}
        if fields["account_id"]:
            test_cfg["account_id"] = fields["account_id"].strip()
        self.api_status.setText("در حال اعتبارسنجی کلید جدید…")
        self._api_worker = TaskWorker(lambda: api_manager.rediscover(pid, test_cfg))
        self._api_worker.done.connect(lambda result, p=pid, f=fields, k=new_key: self.on_api_edit_validated(p, f, k, result))
        self._api_worker.start()

    def on_api_edit_validated(self, pid, fields, new_key, result):
        ok, det = result
        if not ok or not det.ok:                                  # the old key stays untouched
            self.api_status.setText("✕ کلید جدید ذخیره نشد. " + (api_manager.describe_failure(det) if ok else str(det)))
            return
        self.apply_api_edit(pid, fields, new_key, det)

    def apply_api_edit(self, pid, fields, new_key, det):
        try:
            route_model.update_provider(self.settings, pid, label=fields["label"], base_url=fields["base_url"],
                                        account_id=fields["account_id"], api_key=new_key)
        except ValueError as exc:
            self.api_status.setText("✕ " + str(exc))
            return
        if det is not None:
            api_manager.apply_models(self.settings, pid, det.models, det.rate_limit)
        route_model.ensure_routes(self.settings)
        self.api_status.setText("✓ تغییرات ذخیره شد." + (" کلید جدید معتبر بود و مدل‌ها دوباره خوانده شدند." if det is not None else ""))
        self._api_changed(pid)

    # ---- Enable / Disable, Delete, Priority ----
    def api_toggle(self, pid):
        if not pid or pid not in self.settings.get("providers", {}):
            return
        on = not bool(self.settings["providers"][pid].get("enabled"))
        api_manager.set_api_enabled(self.settings, pid, on)
        self.api_status.setText("✓ API فعال شد." if on else "API غیرفعال شد (کلید و مدل‌ها حفظ شدند).")
        self._api_changed(pid)

    def api_delete(self, pid):
        if not pid or pid not in self.settings.get("providers", {}):
            return
        cfg = self.settings["providers"][pid]
        n = sum(1 for r in route_model.get_routes(self.settings) if r["provider"] == pid)
        builtin_note = "\n(کلید پاک و Routeهای این API غیرفعال می‌شوند.)" if pid in route_model.BUILTIN else f"\n({n} Route آن هم حذف می‌شود.)"
        if QMessageBox.question(self, "حذف API", f"«{route_model.provider_label(pid, cfg)}» حذف شود؟{builtin_note}") != QMessageBox.Yes:
            return
        api_manager.delete_api(self.settings, pid)
        self.api_status.setText("✓ API حذف شد.")
        self._api_changed()

    def api_move(self, pid, delta):
        if not pid:
            return
        try:
            api_manager.move_api(self.settings, pid, delta)
        except KeyError:
            self.api_status.setText("این API هنوز Route ندارد؛ اول یک مدل برایش فعال کن.")
            return
        self._api_changed(pid)

    # ---------- Route Manager ----------
    HEALTH_TXT = {"unknown": "— بدون تست", "healthy": "● سالم", "degraded": "◐ مشکل موقت", "down": "✕ خراب"}

    def _selected_route_id(self):
        item = self.route_list.currentItem()
        return item.data(Qt.UserRole) if item else None

    @front_only
    def refresh_route_list(self):
        if not hasattr(self, "route_list"):
            return
        keep = self._selected_route_id()
        status = {x["name"]: x for x in self.client.status()}
        manual, default = self.settings.get("manual_route_id", ""), self.settings.get("default_route_id", "")
        providers = self.settings.get("providers", {})
        self.route_list.blockSignals(True)
        self.route_list.clear()
        for i, r in enumerate(route_model.get_routes(self.settings)):
            st = status.get(r["id"], {})
            label = route_model.provider_label(r["provider"], providers.get(r["provider"]))
            icon = "☁" if st.get("kind", route_model.provider_kind(r["provider"], providers.get(r["provider"]))) == "cloud" else "⌂"
            marks = ("★ دستی  " if r["id"] == manual else "") + ("⚑ پیش‌فرض  " if r["id"] == default else "")
            health = self.HEALTH_TXT.get(st.get("health", "unknown"), "")
            extra = (f" {st['last_ms']}ms" if st.get("last_ms") is not None else "") + \
                    (f" · استراحت {st['cooldown']}s" if st.get("cooldown") else "")
            reason = "" if st.get("enabled") or st.get("cooldown") else {"disabled": " · غیرفعال", "no_key": " · بدون کلید",
                                                                          "provider_off": " · Provider غیرفعال"}.get(st.get("reason"), " · غیرفعال")
            item = QListWidgetItem(f"{i + 1}.  {icon} {label} / {r['model'] or '(بدون مدل)'}   {marks}{health}{extra}{reason}")
            item.setData(Qt.UserRole, r["id"])
            if reason:
                item.setForeground(QBrush(QColor("#8d93ab")))
            self.route_list.addItem(item)
        for i in range(self.route_list.count()):
            if self.route_list.item(i).data(Qt.UserRole) == keep:
                self.route_list.setCurrentRow(i)
                break
        else:
            if self.route_list.count():
                self.route_list.setCurrentRow(0)
        self.route_list.blockSignals(False)
        self.route_manual_lbl.setText("انتخاب دستی: " + (manual or "خودکار (بر اساس اولویت)") +
                                      ("" if self.settings.get("failover_enabled", True) else " · Failover خاموش است"))
        self.on_route_selected()

    def on_route_selected(self):
        rid = self._selected_route_id()
        route = route_model.find_route(self.settings, rid) if rid else None
        self._loading_route = True
        try:
            for w in (self.route_model_edit, self.route_enabled_chk, self.route_timeout, self.route_cooldown, self.route_ctx,
                      self.route_predict, self.route_test_btn, self.route_del_btn, self.route_default_btn, self.route_use_btn,
                      self.route_up_btn, self.route_down_btn, self.route_bench_btn):
                w.setEnabled(route is not None)
            if not route:
                self.route_provider_lbl.setText("-")
                self.route_status.setText("Route‌ای انتخاب نشده.")
                return
            cfg = self.settings.get("providers", {}).get(route["provider"], {})
            local = route_model.provider_kind(route["provider"], cfg) == "local"
            self.route_provider_lbl.setText(f"{route_model.provider_label(route['provider'], cfg)}  ({'Local' if local else 'Cloud'})  ·  {route['id']}")
            if route["provider"] == "ollama" and self._ollama_models:
                self.route_model_edit.set_models(self._ollama_models)
            self.route_model_edit.setText(route["model"])
            self.route_enabled_chk.setChecked(bool(route.get("enabled", True)))
            lo, hi = route_model.LOCAL_TIMEOUT if local else route_model.CLOUD_TIMEOUT
            self.route_timeout.setRange(lo, hi)
            self.route_timeout.setValue(int(route.get("timeout", 18)))
            self.route_cooldown.setValue(int(route.get("cooldown", 45)))
            is_ollama = route["provider"] == "ollama"
            self.route_ctx.setEnabled(is_ollama)
            self.route_predict.setEnabled(is_ollama)
            self.route_ctx.setValue(int(route.get("num_ctx", 0)))
            self.route_predict.setValue(int(route.get("num_predict", 0)))
            st = next((x for x in self.client.status() if x["name"] == rid), {})
            parts = [self.HEALTH_TXT.get(st.get("health", "unknown"), "")]
            if st.get("last_ms") is not None:
                parts.append(f"آخرین پاسخ {st['last_ms']} ms")
            if st.get("cooldown"):
                parts.append(f"استراحت {st['cooldown']}s")
            if st.get("last_error"):
                parts.append("آخرین خطا: " + st["last_error"])
            self.route_status.setText("  ·  ".join(p for p in parts if p))
        finally:
            self._loading_route = False

    def after_route_change(self, select=None):
        self.sync_ollama_primary()
        self.save_now()
        self.refresh_route_list()
        if select:
            for i in range(self.route_list.count()):
                if self.route_list.item(i).data(Qt.UserRole) == select:
                    self.route_list.setCurrentRow(i)
        if not self.busy:
            self.set_badge("idle", self.client.preview_route())

    def sync_ollama_primary(self):
        """Route 'ollama' is the model of the Assistant tab: keep the two in step both ways."""
        r = route_model.find_route(self.settings, "ollama")
        if r and r["model"] and r["model"] != self.settings.get("model"):
            self.settings["model"] = r["model"]
            self.settings.setdefault("providers", {}).setdefault("ollama", {})["model"] = r["model"]
            self.model.setText(r["model"])

    def route_edit_changed(self):
        if self._loading_route:
            return
        rid = self._selected_route_id()
        if not rid:
            return
        try:
            route_model.update_route(self.settings, rid, model=self.route_model_edit.text(), enabled=self.route_enabled_chk.isChecked(),
                                     timeout=self.route_timeout.value(), cooldown=self.route_cooldown.value(),
                                     num_ctx=self.route_ctx.value(), num_predict=self.route_predict.value())
        except ValueError as exc:
            self.route_status.setText("✕ " + str(exc))
            return
        self.client.reset_cooldowns(rid)
        self.after_route_change()

    def on_routes_reordered(self):
        """Drag & drop finished: the new visual order becomes the priority / failover order."""
        if self._loading_route:
            return
        ids = [self.route_list.item(i).data(Qt.UserRole) for i in range(self.route_list.count())]
        route_model.reorder(self.settings, ids)
        self.save_now()
        QTimer.singleShot(0, self.refresh_route_list)           # renumber labels after the drop has fully finished
        QTimer.singleShot(0, lambda: None if self.busy else self.set_badge("idle", self.client.preview_route()))

    def move_selected(self, delta):
        rid = self._selected_route_id()
        if not rid:
            return
        ids = [r["id"] for r in route_model.get_routes(self.settings)]
        route_model.move_route(self.settings, rid, ids.index(rid) + delta)
        self.after_route_change(select=rid)

    def default_selected_route(self):
        rid = self._selected_route_id()
        if rid:
            route_model.set_default(self.settings, rid)
            self.after_route_change(select=rid)

    def delete_selected_route(self):
        rid = self._selected_route_id()
        if not rid:
            return
        if QMessageBox.question(self, "حذف Route", "این Route حذف شود؟ (Provider و API Key آن دست‌نخورده می‌مانند.)") != QMessageBox.Yes:
            return
        route_model.remove_route(self.settings, rid)
        self.client.reset_cooldowns(rid)
        self.after_route_change()

    def on_failover_toggled(self, on):
        self.settings["failover_enabled"] = bool(on)
        self.save_now()
        self.refresh_route_list()

    def add_route_from_values(self, provider, model, enabled=True):
        try:
            route = route_model.add_route(self.settings, provider, model, enabled=enabled)
        except ValueError as exc:
            self.route_status.setText("✕ " + str(exc))
            return None
        self.after_route_change(select=route["id"])
        return route

    def add_route_dialog(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("افزودن Route")
        form = QFormLayout(dlg)
        prov = QComboBox()
        providers = self.settings.get("providers", {})
        for name in providers:
            prov.addItem(route_model.provider_label(name, providers[name]), name)
        model = ModelCombo("")
        def fill():
            if prov.currentData() == "ollama":
                model.set_models(self._ollama_models)
        prov.currentIndexChanged.connect(lambda *_: fill())
        form.addRow("Provider", prov)
        form.addRow("Model ID", model)
        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.accepted.connect(dlg.accept)
        box.rejected.connect(dlg.reject)
        form.addRow(box)
        if dlg.exec() == QDialog.Accepted:
            self.add_route_from_values(prov.currentData(), model.text())

    def add_provider_from_values(self, label, base_url, api_key="", local=False, first_model=""):
        try:
            pid = route_model.add_provider(self.settings, label, base_url, api_key, local)
            if first_model.strip():
                route_model.add_route(self.settings, pid, first_model)
        except ValueError as exc:
            self.route_status.setText("✕ " + str(exc))
            return None
        route_model.ensure_routes(self.settings)
        self.save_now()
        self.refresh_api_table(pid)
        self.refresh_route_list()
        return pid

    def add_provider_dialog(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("افزودن Provider")
        form = QFormLayout(dlg)
        name, url, key, model = QLineEdit(), QLineEdit("https://"), QLineEdit(), QLineEdit()
        key.setEchoMode(QLineEdit.Password)
        local = QCheckBox("سرور محلی (بدون API Key، مثل LM Studio)")
        form.addRow("نام", name)
        form.addRow("Base URL (تا /v1)", url)
        form.addRow("API Key", key)
        form.addRow(local)
        form.addRow("اولین Model ID", model)
        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.accepted.connect(dlg.accept)
        box.rejected.connect(dlg.reject)
        form.addRow(box)
        if dlg.exec() == QDialog.Accepted:
            pid = self.add_provider_from_values(name.text(), url.text(), key.text(), local.isChecked(), model.text())
            if pid and key.text().strip():
                self.api_refresh(pid, quiet=True)

    def remove_provider_ui(self, pid):
        n = sum(1 for r in route_model.get_routes(self.settings) if r["provider"] == pid)
        if QMessageBox.question(self, "حذف Provider", f"این Provider و {n} Route آن حذف شوند؟") != QMessageBox.Yes:
            return
        route_model.remove_provider(self.settings, pid)
        api_manager.registry(self.settings).pop(pid, None)
        self.client.reset_cooldowns()
        self.save_now()
        self.refresh_api_table()
        self.refresh_route_list()

    def provider_changed(self):
        """Key / enable / URL edited in a provider box: autosave (an empty key field keeps the saved key)."""
        if getattr(self, "_loading_route", False) or not hasattr(self, "route_ollama_enabled"):
            return
        self.collect_provider_settings()
        self.client.reset_cooldowns()
        self.save_now()
        self.refresh_route_list()
        if not self.busy:
            self.set_badge("idle", self.client.preview_route())

    def test_selected_route(self):
        rid = self._selected_route_id()
        if not rid:
            return
        self.route_test_btn.setEnabled(False)
        self.route_status.setText("در حال تست…")
        self._route_worker = TaskWorker(lambda: self.client.test_route(rid))
        self._route_worker.done.connect(self.on_route_test_done)
        self._route_worker.start()

    def on_route_test_done(self, result):
        ok, value = result
        self.route_test_btn.setEnabled(True)
        self.refresh_route_list()
        if ok:
            good, msg, ms = value
            self.route_status.setText(("✓ " if good else "✕ ") + msg + (f"  ({ms} ms)" if ms is not None else ""))
        else:
            self.route_status.setText("✕ " + value)

    def scan_ollama(self):
        self.route_scan_btn.setEnabled(False)
        self.route_status.setText("در حال جست‌وجوی مدل‌های نصب‌شده‌ی Ollama…")
        client = OllamaClient.from_settings(self.settings)
        def task():
            ok, models = client.status()
            if not ok:
                raise RuntimeError(models)
            return models
        self._scan_worker = TaskWorker(task)
        self._scan_worker.done.connect(self.on_scan_done)
        self._scan_worker.start()

    def on_scan_done(self, result):
        ok, value = result
        self.route_scan_btn.setEnabled(True)
        if not ok:
            self.route_status.setText("✕ " + value)
            return
        self._ollama_models = list(value)
        self.model.set_models(value)
        added = route_model.add_ollama_models(self.settings, value)
        self.save_now()
        self.refresh_route_list()
        self.route_status.setText(f"✓ {len(value)} مدل نصب‌شده پیدا شد؛ {len(added)} Route جدید اضافه شد (به‌صورت غیرفعال تا خودت فعال کنی).")
        self.refresh_unified_models()

    def run_benchmark(self, all_enabled):
        if self.busy:
            self.route_status.setText("✕ یک پاسخ در حال تولید است؛ بعد از پایان آن Benchmark بگیر.")
            return
        if all_enabled:
            ids = [i["route_id"] for i in self.client.available_routes()]
        else:
            ids = [self._selected_route_id()] if self._selected_route_id() else []
        if not ids:
            self.route_status.setText("✕ Route فعالی برای Benchmark نیست.")
            return
        cloud = [i for i in ids if route_model.provider_kind((route_model.find_route(self.settings, i) or {}).get("provider", ""),
                 self.settings.get("providers", {}).get((route_model.find_route(self.settings, i) or {}).get("provider", ""))) == "cloud"]
        if cloud and QMessageBox.question(self, "Benchmark", f"{len(cloud)} Route ابری هرکدام یک درخواست کوتاه (حدود ۴۸ توکن) از سهمیه‌ی API مصرف می‌کند. ادامه بدهم؟\n"
                                                           "Routeها یکی‌یکی تست می‌شوند، نه هم‌زمان.") != QMessageBox.Yes:
            return
        self.busy = True
        self._bench_busy = True
        self.bench_out.setPlainText("در حال اجرا…")
        self._bench_lines = []
        self._bench_worker = BenchWorker(self.client, ids)
        self._bench_worker.progress.connect(self.on_bench_progress)
        self._bench_worker.done.connect(self.on_bench_done)
        self._bench_worker.start()

    def on_bench_progress(self, e):
        if e.get("phase") == "running":
            self.bench_out.setPlainText("\n".join(self._bench_lines + [f"… {e['label']} / {e['model']}"]))
        else:
            self._bench_lines.append(self.format_bench_row(e))
            self.bench_out.setPlainText("\n".join(self._bench_lines))

    @staticmethod
    def format_bench_row(r):
        fmt = lambda v: "-" if v is None else f"{v}"                              # noqa: E731
        if not r.get("ok"):
            return f"✕ {r['label']} / {r['model']}: {r.get('error') or 'ناموفق'}"
        return (f"✓ {r['label']} / {r['model']} [{'Local' if r['kind'] == 'local' else 'Cloud'}]  connect {fmt(r['connect_ms'])} ms · "
                f"first token {fmt(r['first_token_ms'])} ms · total {fmt(r['total_ms'])} ms · {fmt(r['speed'])} {r['unit']}"
                + (f" · load {r['load_ms']} ms" if r.get("load_ms") else "")
                + (f" · {r['model_gb']}GB, GPU {r['gpu_pct']}%" if r.get("gpu_pct") is not None else ""))

    def on_bench_done(self, result):
        self.busy = False
        self._speech_live = False
        self._bench_busy = False
        ok, value = result
        if not ok:
            self.bench_out.setPlainText("✕ " + value)
        else:
            ranked = sorted([r for r in value if r["ok"] and r["first_token_ms"] is not None], key=lambda r: r["first_token_ms"])
            lines = [self.format_bench_row(r) for r in value]
            if ranked:
                lines.append(f"\nسریع‌ترین اولین Token: {ranked[0]['label']} / {ranked[0]['model']} ({ranked[0]['first_token_ms']} ms)")
            self.bench_out.setPlainText("\n".join(lines))
        self.refresh_route_list()
        self._send_next_pending()

    # ---------- settings ----------
    # ---- Windows 11 glass ----
    def showEvent(self, event):
        super().showEvent(event)
        winfx.apply_effect(self.winId(), self._effect)
        QTimer.singleShot(0, self.update_bubble)

    def update_window_effect(self, wanted):
        """Settings changed: restyle now. Switching glass on/off at runtime needs a restart to be fully clean."""
        new = winfx.active_effect(wanted)
        old, self._effect = self._effect, new
        QApplication.instance().setStyleSheet(build_style(new, self.settings.get("appearance", {})))
        self.apply_chat_theme()
        winfx.apply_effect(self.winId(), new)
        if (old == "off") != (new == "off"):
            self.add_chat("system", "برای اعمال کامل حالت شیشه‌ای، برنامه را یک بار ببند و دوباره باز کن.")

    def apply_settings(self):
        s = self.settings
        s.update({
            "assistant_name": self.name.text().strip() or "Kira",
            "model": self.model.text().strip() or "qwen2.5:3b",
            "ollama_url": self.url.text().strip() or "http://localhost:11434",
            "persona": self.persona.toPlainText().strip(), "active_modes": self.modes_chk.isChecked(),
            "temperature": float(self.temp.currentText()),
            "speak_replies": self.voice_page.speak_chk.isChecked(), "stream_speech": self.voice_page.stream_chk.isChecked(),
            "voice_rate": self.voice_page.rate.value(),
            "voice_volume": self.voice_page.volume.value() / 100.0,
            "output_device": self.voice_page.out_device.currentData() or "", "mic_device": self.voice_page.mic_device.currentData() or "",
            "mic_gain": self.voice_page.mic_gain.value(),
            "stt_language": self.voice_page.stt_lang.currentText(), "whisper_model": self.voice_page.whisper.currentText().strip() or "small",
            "wake_timeout": self.voice_page.wake_timeout.value(),
            "mic_sensitivity": self.voice_page.mic_sens.value(), "barge_in": self.voice_page.barge_chk.isChecked(),
            "companion_height": self.character_page.size_sl.value(),
            "follow_strength": self.character_page.follow_sl.value() / 100.0,
            "motion_strength": self.character_page.motion_sl.value() / 100.0,
            "click_reactions": self.character_page.react_chk.isChecked(), "idle_talk": self.character_page.idle_chk.isChecked(), "always_on_top": self.character_page.top_chk.isChecked(),
            "minimize_to_tray": self.character_page.tray_min_chk.isChecked(), "close_to_tray": self.character_page.tray_close_chk.isChecked(),
            "ui_lang": self.ui_lang.currentData(),
            "window_effect": self.appearance_page.window_effect.currentData(),
            "tavily_api_key": self.tavily_key.text().strip(),
            "web_depth": self.web_depth.currentData(),
            "web_fallback": self.web_fallback_chk.isChecked(),
        })
        # Qwen3-ASR enablement is controlled independently in Local Models;
        # this picker only selects the offline faster-whisper fallback.
        self.collect_provider_settings()
        route_model.ensure_routes(s)
        primary = route_model.find_route(s, "ollama")
        if primary and primary["model"] != s["model"]:
            route_model.update_route(s, "ollama", model=s["model"])          # the Assistant-tab model is the primary local route
        ocfg = s.setdefault("providers", {}).setdefault("ollama", {})
        keep_value, keep_ok = parse_keep_alive(self.keep_alive.currentText())
        if not keep_ok:
            self.add_chat("system", self.t("o_keep_bad"))
        ocfg.update({"enabled": self.route_ollama_enabled.isChecked(), "num_ctx": clamp_num_ctx(self.num_ctx.value()),
                     "num_predict": clamp_num_predict(self.num_predict.value()),
                     "keep_alive": str(keep_value), "model": s["model"], "base_url": s["ollama_url"]})
        s["providers"]["ollama"]["enabled"] = self.route_ollama_enabled.isChecked()
        try:
            save_settings(s)
        except Exception as exc:
            QMessageBox.critical(self, "خطا در ذخیره تنظیمات", f"تنظیمات ذخیره نشدند:\n{exc}")
            return
        old_states = self.client.states
        shared_cooldowns = {}                              # fresh cooldowns after saving (a fixed key/model gets another chance)
        for sess in self.sessions.values():               # every character's chat gets a new router (a running answer keeps its old one)
            router = HybridRouter(s)
            router.states, router.cooldowns = old_states, shared_cooldowns
            sess.client = router
        self.tool_agent.set_settings(s)
        evidence_memory.configure(s)
        usage.install(s)
        self.ollama_client = OllamaClient.from_settings(s)
        self.refresh_route_list()
        self.set_badge("idle", self.client.preview_route())
        self.apply_runtime()
        self.apply_character_voice_settings()
        self.apply_appearance(save=False)
        self.retranslate()
        self.check_status()
        if self.mic_btn.isChecked():
            self.start_listener()
        self.add_chat("system", self.t("saved"))

    # ---- System Tray ----
    def update_tray(self):
        """Create / remove the tray icon to match the two tray settings. Safe to call repeatedly."""
        s = self.settings
        wanted = bool(s.get("minimize_to_tray") or s.get("close_to_tray")) and QSystemTrayIcon.isSystemTrayAvailable()
        tray = getattr(self, "tray", None)
        self.tray = tray                                             # always defined (no system tray = None)
        if wanted and tray is None:
            icon = QIcon(str(ROOT / "assets" / "kira_character.png"))
            tray = QSystemTrayIcon(icon, self)
            tray.setToolTip("Kira")
            menu = QMenu()
            menu.aboutToShow.connect(self.refresh_tray_menu)          # filled when it opens, so states are current
            tray.setContextMenu(menu)
            tray.activated.connect(lambda reason: self.toggle_main_window()
                                   if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick) else None)
            self._tray_menu = menu                                   # keep alive
            self.tray = tray
            tray.show()
        elif not wanted and tray is not None:
            tray.hide()
            tray.deleteLater()
            self.tray = None
        app = QApplication.instance()
        if app is not None:
            app.setQuitOnLastWindowClosed(self.tray is None)         # with a tray icon the app lives on while hidden

    def refresh_tray_menu(self):
        """Rebuilt every time the menu opens, so model / web / mic states are always current."""
        menu = self._tray_menu
        menu.clear()
        menu.addAction("نمایش / مخفی کردن Kira", self.toggle_main_window)
        menu.addAction("نمایش / مخفی کردن شخصیت", self.toggle_companion)
        menu.addSeparator()
        models = menu.addMenu("تعویض مدل")
        models.setStyleSheet("QMenu { menu-scrollable: 1; }")
        manual = self.settings.get("manual_route_id", "")
        auto = models.addAction("خودکار (بر اساس اولویت)")
        auto.setCheckable(True)
        auto.setChecked(not manual)
        auto.triggered.connect(lambda checked=False: self.select_route(""))
        routes = self.client.available_routes()
        shown = routes[: self.MENU_ROUTES]
        chosen = next((r for r in routes if r["route_id"] == manual), None)
        if chosen is not None and chosen not in shown:
            shown = shown[:-1] + [chosen]
        for info in shown:
            model = info["model"] if len(info["model"]) <= 34 else info["model"][:33] + "…"
            act = models.addAction(f"{'☁' if info['kind'] == 'cloud' else '⌂'}  {info['label']} / {model}")
            act.setCheckable(True)
            act.setChecked(info["route_id"] == manual)
            act.triggered.connect(lambda checked=False, rid=info["route_id"]: self.select_route(rid))
        if not routes:
            models.addAction("هیچ Route فعالی نیست").setEnabled(False)
        web = menu.addAction("جست‌وجوی وب")
        web.setCheckable(True)
        web.setChecked(self.web_btn.isChecked())
        web.triggered.connect(lambda checked=False: self.web_btn.setChecked(not self.web_btn.isChecked()))
        mic = menu.addAction("میکروفن")
        mic.setCheckable(True)
        mic.setChecked(self.mic_btn.isChecked())
        mic.triggered.connect(self.tray_toggle_mic)
        menu.addSeparator()
        menu.addAction("خروج", self.quit_app)

    def tray_toggle_mic(self, checked=False):
        self.mic_btn.setChecked(not self.mic_btn.isChecked())
        self.toggle_mic()

    def update_bubble(self):
        """The chat bubble is shown beside Kira only while the main window is out of the way (in the tray)."""
        bubble = getattr(self, "bubble", None)
        if bubble is None:
            return
        away = getattr(self, "tray", None) is not None and (not self.isVisible() or self.isMinimized())
        if away and self.companion.isVisible() and not self._closing:
            bubble.place_beside(self.companion)
            if not bubble.isVisible():
                bubble.show()
        else:
            bubble.hide()

    def hideEvent(self, event):
        super().hideEvent(event)
        QTimer.singleShot(0, self.update_bubble)

    def hide_to_tray(self):
        self.hide()
        if not self.companion.isVisible():
            self.companion.show()                                    # she stays on the desktop while the window is hidden
        self.update_bubble()
        if getattr(self, "tray", None) is not None and not getattr(self, "_tray_hinted", False):
            self._tray_hinted = True
            self.tray.showMessage("Kira", "Kira هنوز در System Tray فعال است. برای باز کردن روی آیکون کلیک کن.",
                                  QSystemTrayIcon.Information, 3500)

    def toggle_main_window(self):
        if self.isVisible() and not self.isMinimized():
            self.hide()
        else:
            self.showNormal()
            self.raise_()
            self.activateWindow()

    def quit_app(self):
        self._quitting = True
        self.close()
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def changeEvent(self, event):
        super().changeEvent(event)
        if (event.type() == event.Type.WindowStateChange and self.isMinimized()
                and getattr(self, "tray", None) is not None and self.settings.get("minimize_to_tray")):
            QTimer.singleShot(0, self.hide_to_tray)

    def apply_runtime(self):
        s = self.settings
        self.update_tray()
        self.animator.rig.intensity = float(s["motion_strength"]) * self.animator.motion_gain
        self.animator.follow_strength = float(s["follow_strength"])
        self.animator.auto_bored = True
        self.companion.set_height(int(s["companion_height"]))
        self.companion.set_on_top(bool(s["always_on_top"]))

    def look_anchor(self):
        w = self.companion if self.companion.isVisible() else self.avatar
        return w.mapToGlobal(w.rect().center())

    def open_speech_fixes(self):
        """Opens the word dictionary (hotwords + fixes) for speech recognition; it is created with an example first."""
        try:
            path = SpeechFixes().ensure_file()
        except OSError as exc:
            self.add_chat("error", f"فایل اصلاح واژه‌ها ساخته نشد: {exc}")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def open_sounds(self):
        SOUNDS_DIR.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(SOUNDS_DIR)))

    def _form_client(self):
        keep, _ = parse_keep_alive(self.keep_alive.currentText())
        return OllamaClient(self.url.text().strip(), self.model.text().strip(), self.num_ctx.value(), keep,
                            num_predict=self.num_predict.value())

    def _run_ollama_task(self, fn, busy_text):
        for b in (self.conn_btn, self.load_btn, self.unload_btn, self.speed_btn):
            b.setEnabled(False)
        self.conn_lbl.setText(busy_text)
        self._ollama_worker = OllamaTaskWorker(fn)
        self._ollama_worker.done.connect(self.on_ollama_task_done)
        self._ollama_worker.start()

    def on_ollama_task_done(self, ok, text):
        models = getattr(self, "_found_models", None)
        if models:
            self.model.set_models(models)
        self._found_models = None
        for b in (self.conn_btn, self.load_btn, self.unload_btn, self.speed_btn):
            b.setEnabled(True)
        self.conn_lbl.setText(("✓ " if ok else "✕ ") + text)

    def test_connection(self):
        client = self._form_client()

        def task():
            ok, text = client.describe()
            listed, models = client.status()
            self._found_models = models if listed else None
            return ok, text
        self._run_ollama_task(task, self.t("o_busy"))

    def speed_test(self):
        client = self._form_client()
        self._run_ollama_task(client.benchmark, self.t("o_busy_long"))

    def load_local_model(self):
        client = self._form_client()
        def task():
            client.preload()
            return client.describe()
        self._run_ollama_task(task, self.t("o_busy"))

    def unload_local_model(self):
        client = self._form_client()
        def task():
            client.unload()
            return client.describe()
        self._run_ollama_task(task, self.t("o_busy"))

    # ---------- chat ----------
    def check_status(self):
        st = self.client.status()
        configured = []
        for x in st:
            label = route_model.provider_label(x["provider"], self.settings.get("providers", {}).get(x["provider"]))
            if x["provider"] != "ollama" and x["enabled"] and label not in configured:
                configured.append(label)
        local_on = any(x["provider"] == "ollama" and x["enabled"] for x in st) or \
            bool(self.settings.get("providers", {}).get("ollama", {}).get("enabled", True)) and not st
        if configured:
            self.set_status("st_cloud_active" if local_on else "st_cloud_only", providers=", ".join(configured))
            return
        if not local_on:
            self.set_status("st_local_disabled")
            return
        ok, detail = self.ollama_client.status()
        m = self.settings["model"]
        if ok:
            self.model.set_models(detail)
            self._ollama_models = list(detail)
            self.set_status("st_ok" if model_installed(detail, m) else "st_nomodel", m=m)
        else:
            self.set_status("st_off")
    def capture_screen_attachment(self):
        """Capture the primary desktop only after an explicit user click; attach it for a normal Vision request."""
        try:
            screen = QApplication.primaryScreen()
            if screen is None:
                raise RuntimeError("نمایشگری برای ثبت تصویر پیدا نشد.")
            pixmap = screen.grabWindow(0)
            if pixmap.isNull():
                raise RuntimeError("ثبت تصویر صفحه ناموفق بود.")
            self.add_pasted_image(pixmap.toImage())
            self.add_chat("system", "🖥️ تصویر صفحه به پیوست‌ها اضافه شد؛ تا وقتی خودت پیام را نفرستی، برای مدل ارسال نمی‌شود.")
        except Exception as exc:
            self.add_chat("system", "ثبت تصویر صفحه ناموفق بود: " + str(exc)[:180])

    # ---- attachments (images and files) ----
    def pick_attachments(self):
        exts = " ".join("*" + e for e in sorted(att.IMAGE_TYPES))
        paths, _ = QFileDialog.getOpenFileNames(
            self, "انتخاب عکس یا فایل", "",
            f"عکس و فایل‌های پشتیبانی‌شده ({exts} *.txt *.md *.json *.csv *.log *.py *.js *.html *.xml *.yaml *.yml *.ini *.docx *.pdf *.zip);;همه‌ی فایل‌ها (*)")
        if paths:
            self.add_attachment_paths(paths)

    # -- tile strips --
    @staticmethod
    def make_tile_strip():
        frame = QFrame()
        row = QHBoxLayout(frame)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        row.addStretch(1)
        frame.row = row
        frame.hide()
        return frame

    @staticmethod
    def strip_add(strip, tile):
        strip.row.insertWidget(strip.row.count() - 1, tile)
        strip.show()

    @staticmethod
    def strip_remove(strip, tile):
        strip.row.removeWidget(tile)
        tile.setParent(None)
        tile.deleteLater()
        strip.setVisible(strip.row.count() > 1)

    def show_attach_error(self, messages):
        self.attachment_controller.show_error(messages)

    def cancel_attachments(self):
        self.attachment_controller.cancel()

    def attach_loading(self):
        return self.attachment_controller.is_loading()

    def add_attachment_paths(self, paths):
        self.attachment_controller.add_paths(paths)

    def on_attach_progress(self, index, percent):
        self.attachment_controller.on_progress(index, percent)

    def on_attach_finished(self):
        self.attachment_controller.on_finished()

    def on_attach_loaded(self, index, attachment):
        self.attachment_controller.on_loaded(index, attachment)

    def on_attach_failed(self, index, message):
        self.attachment_controller.on_failed(index, message)

    def add_pasted_image(self, image):
        self.attachment_controller.add_image(image)

    def remove_attachment_tile(self, tile):
        self.attachment_controller.remove_tile(tile)

    def clear_attachments(self):
        self.attachment_controller.clear()

    # -- sending: cards with the upload percentage --
    @front_only
    def show_upload_tiles(self, attachments):
        self.clear_upload_tiles()
        self._upload_token += 1
        self._upload_done = False
        for a in attachments or []:
            tile = AttachmentTile(a["name"])
            tile.set_attachment(a)
            tile.set_removable(False)
            tile.set_progress(-1)                               # '…' until the first real percentage arrives
            self._upload_tiles.append(tile)
            self.strip_add(self.send_strip, tile)

    @front_only
    def clear_upload_tiles(self, token=None):
        if token is not None and token != self._upload_token:
            return
        for tile in self._upload_tiles:
            self.strip_remove(self.send_strip, tile)
        self._upload_tiles = []

    @front_only
    def on_upload_event(self, phase, percent=None):
        if not self._upload_tiles:
            return
        if phase == "uploading":
            self._upload_done = False
            for tile in self._upload_tiles:
                tile.set_progress(min(99, int(percent or 0)))
        elif phase in ("waiting", "streaming") and not self._upload_done:
            self._upload_done = True                            # the model has the request: show ✓, then remove the cards
            for tile in self._upload_tiles:
                tile.set_progress(100)
            QTimer.singleShot(1500, lambda tok=self._upload_token: self.clear_upload_tiles(tok))
        elif phase == "failover":
            for tile in self._upload_tiles:
                tile.set_progress(-1)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        paths = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
        if paths:
            self.add_attachment_paths(paths)
            event.acceptProposedAction()

    def set_vision_mode(self, mode):
        """Change analysis cadence without changing the manual Game Mode safety gate."""
        policy = policy_for(mode)
        self._vision_gate.set_policy(policy)
        self.settings["vision_mode"] = policy.name
        save_settings(self.settings)
        if hasattr(self, "vision_rate_actions"):
            for key, action in self.vision_rate_actions.items():
                action.setChecked(key == policy.name)
        self._game_capture_timer.setInterval(max(250, int(policy.interval_seconds * 1000)))
        if self._game_mode_enabled and game_mode_permissions(self._game_mode_profile)["vision_capture"]:
            self._capture_game_frame()
            if not self._game_capture_timer.isActive():
                self._game_capture_timer.start()
        self.game_mode_btn.setToolTip(f"Game Mode · Vision {policy.name} · هر {policy.interval_seconds:g} ثانیه")

    def _set_game_vision_capture(self, allowed):
        """Synchronize capture permission and cancel in-flight analysis whenever Vision is disallowed."""
        allowed = bool(allowed)
        self.game_mode.set_enabled(allowed)
        if allowed:
            self._capture_game_frame()
            self._game_capture_timer.start()
        else:
            self._game_capture_timer.stop()
            self._latest_game_frame = None
            gate = getattr(self, "_vision_gate", None)
            if gate is not None:
                gate.reset()
            self._vision_last_note = ""
            self._cancel_vision_worker()

    def _cancel_vision_worker(self):
        worker = getattr(self, "_vision_worker", None)
        if worker is not None and worker.isRunning():
            worker.cancel_request()

    def _stop_local_code_jobs(self):
        code_chat = getattr(self, "code_chat", None)
        session = getattr(code_chat, "session", None) if code_chat is not None else None
        if session is not None:
            with self._as(session):
                code_chat.stop(session)

    def set_game_mode_profile(self, profile):
        """Apply a manually selected gameplay profile; never infer or enable it automatically."""
        self._game_mode_profile = normalize_game_mode_profile(profile)
        self.game_mode_story_action.setChecked(self._game_mode_profile == STORY_MODE)
        self.game_mode_safe_action.setChecked(self._game_mode_profile == COMPETITIVE_SAFE_MODE)
        self.set_game_mode(True)

    def set_game_mode(self, enabled):
        enabled = bool(enabled)
        was_enabled = self._game_mode_enabled
        self._game_mode_enabled = enabled
        permissions = game_mode_permissions(self._game_mode_profile)
        vision_allowed = bool(permissions["vision_capture"])
        audio_allowed = bool(permissions["game_audio_loopback"])

        # Capture is gated by the selected profile, not only by the master toggle.
        self._set_game_vision_capture(enabled and vision_allowed)
        safe_profile = enabled and self._game_mode_profile == COMPETITIVE_SAFE_MODE
        self.tool_agent.set_competitive_safe_mode(safe_profile)
        # Safe mode does not keep polling foreground process metadata while an online game is running.
        if safe_profile:
            self._game_poll_timer.stop()
            self._stop_local_code_jobs()
        elif not self._game_poll_timer.isActive():
            self._game_poll_timer.start()

        if enabled:
            if not was_enabled:
                self._game_prev_mic = self.mic_btn.isChecked()
                self._game_prev_wake = self.wake_btn.isChecked()
            if not self.wake_btn.isChecked():
                self.wake_btn.setChecked(True)
                self.toggle_wake()
            if audio_allowed:
                self._start_game_audio_listener()
            else:
                self._stop_game_audio_listener()
        else:
            self._stop_game_audio_listener()
            if not self._game_prev_wake and self.wake_btn.isChecked():
                self.wake_btn.setChecked(False)
                self.toggle_wake()
            if not self._game_prev_mic and self.mic_btn.isChecked():
                self.mic_btn.setChecked(False)
                self.stop_listener()

        if not enabled:
            self.game_mode_btn.setToolTip("Game Mode خاموش است؛ برای فعال‌کردن دستی کلیک کن")
            self.add_chat("system", "🎮 Game Mode خاموش شد؛ تمام Captureها و شنود صدای بازی متوقف شدند.")
        elif self._game_mode_profile == STORY_MODE:
            self.game_mode_btn.setToolTip("Story Mode فعال است؛ Vision و تحلیل محلی صدای بازی فعال‌اند")
            self.add_chat("system", "🎮 Story Mode فعال شد. Vision و تحلیل محلی صدای بازی فعال‌اند. دست‌کاری پردازش، حافظه یا ورودی بازی همچنان ممنوع است.")
        else:
            self.game_mode_btn.setToolTip("Competitive Safe فعال است؛ بدون Vision، Capture، شنود بازی یا کنترل دسکتاپ")
            self.add_chat("system", "🛡️ Competitive Safe فعال شد. Vision، Capture، شنود صدای بازی و ابزارهای کنترل دسکتاپ/MCP مسدودند. فقط چت، جست‌وجوی وب و میکروفون/Wake Word مستقل فعال‌اند.")

    def _start_game_audio_listener(self):
        self._stop_game_audio_listener()
        self.game_audio_listener = GameAudioListener(self.settings, self)
        self.game_audio_listener.transcript.connect(self.on_game_audio_transcript)
        self.game_audio_listener.error.connect(self.on_game_audio_error)
        self.game_audio_listener.start()

    def _stop_game_audio_listener(self):
        listener = self.game_audio_listener
        self.game_audio_listener = None
        if listener is not None:
            listener.stop()
            if listener.isRunning():
                self._stopping_game_audio_listener = listener
                listener.finished.connect(lambda: setattr(self, "_stopping_game_audio_listener", None))

    def on_game_audio_error(self, message):
        if (self._game_mode_enabled
                and game_mode_permissions(self._game_mode_profile)["game_audio_loopback"]):
            self.add_chat("system", "🎧 " + message)

    def on_game_audio_transcript(self, text):
        if (not self._game_mode_enabled
                or not game_mode_permissions(self._game_mode_profile)["automatic_game_audio_alerts"]
                or self.busy or self.speaker._began or not is_important_game_audio(text)):
            return
        now = time.monotonic()
        lower = text.casefold()
        category = ("urgent" if re.search(r"low health|low hp|critical|danger|warning|خطر|هشدار|خونت کم|جونت کم", lower, re.I)
                    else "complete" if re.search(r"mission complete|quest complete|victory|achievement|مرحله تمام|ماموریت تمام|دستاورد", lower, re.I)
                    else "combat")
        previous = self._game_audio_alerts.get(category, (0.0, ""))
        if now - previous[0] < 25 or lower == previous[1]:
            return
        self._game_audio_alerts[category] = (now, lower)
        alerts = {
            "urgent": "حواست باشه، از صدای بازی هشدار خطر یا کمبود سلامتی شنیدم.",
            "complete": "به نظر می‌رسه یک مرحله، مأموریت یا دستاورد مهم تکمیل شده.",
            "combat": "به نظر می‌رسه اتفاق مهمی در مبارزه یا نزدیک‌شدن دشمن رخ داده.",
        }
        self.reply_local(alerts[category], "surprised" if category == "urgent" else "thinking")


    def _capture_game_frame(self):
        """Capture a bounded frame and analyze only changed frames at the selected low-cost rate."""
        if not self._game_mode_enabled or not game_mode_permissions(self._game_mode_profile)["vision_capture"]:
            self._latest_game_frame = None
            self._vision_gate.reset()
            return
        # Re-check the foreground immediately before every capture; the slower
        # suggestion timer alone could leave a background game capturable for seconds.
        self.game_mode.poll()
        pixmap = self.game_mode.capture_last_game(
            self._vision_gate.policy.max_width, self._vision_gate.policy.max_height
        )
        self._latest_game_frame = pixmap.toImage() if pixmap is not None else None
        if self._latest_game_frame is None or self._vision_worker is not None and self._vision_worker.isRunning():
            return
        # Never compete with a user chat request for the same provider route.
        if self.busy or self.client.busy or self.speaker._began:
            return
        try:
            from PySide6.QtCore import QBuffer, QByteArray, QIODevice
            data = QByteArray()
            buffer = QBuffer(data)
            if not buffer.open(QIODevice.WriteOnly):
                return
            if not self._latest_game_frame.save(buffer, "JPEG", self._vision_gate.policy.jpeg_quality):
                return
            jpeg = bytes(data)
            # Compare a tiny grayscale thumbnail, not compressed JPEG bytes, to detect real scene changes.
            thumb = self._latest_game_frame.scaled(32, 18, Qt.IgnoreAspectRatio, Qt.FastTransformation).convertToFormat(QImage.Format_Grayscale8)
            visual_sample = bytes(thumb.pixelColor(x, y).red() for y in range(thumb.height()) for x in range(thumb.width()))
            if not self._vision_gate.accept(jpeg, visual_sample=visual_sample):
                return
            image = att.image_attachment(jpeg, "game-screen.jpg", "image/jpeg")
            session = self.cur
            self._vision_session = session
            self._vision_worker = VisionAnalysisWorker(self.client, image)
            self._vision_worker.done.connect(session.relay.game_vision_done)
            self._vision_worker.finished.connect(session.relay.game_vision_finished)
            self._vision_worker.start()
        except Exception as exc:  # noqa: BLE001 - vision must never interrupt the game/chat
            self.add_chat("system", f"Vision: آماده‌سازی فریم ناموفق بود: {str(exc)[:180]}")

    def _send_pending_for_session(self, session):
        if self._closing or session is None or session.cid not in self.sessions:
            return
        self._send_next_pending(session)

    def _on_game_vision_result(self, ok, result, latency_ms):
        self._vision_gate.mark_latency(latency_ms)
        stats = self._vision_gate.snapshot()
        self.game_mode_btn.setToolTip(
            f"Vision {stats['mode']} · تحلیل: {stats['analysis_count']} · "
            f"فریم تکراری ردشده: {stats['unchanged_skips']} · تأخیر آخرین تحلیل: {latency_ms}ms"
        )
        if (not self._game_mode_enabled
                or not game_mode_permissions(self._game_mode_profile)["vision_capture"]):
            return
        if not ok:
            # Unsupported image models are reported once, not every sampling interval.
            message = str(result or "تحلیل تصویر ناموفق بود.")
            if message != self._vision_last_note:
                self._vision_last_note = message
                self.add_chat("system", "Vision: " + message[:300])
            return
        text = str(result or "").strip()
        if not text or text == self._vision_last_note:
            return
        self._vision_last_note = text
        self.add_chat("system", "👁️ " + text[:900])

    def on_game_detected(self, info):
        """Suggest Game Mode once per detected process, unless the user already enabled it."""
        if self._game_mode_enabled:
            return
        name = info.get("title") or info.get("exe") or "بازی"
        note = (f"🎮 بازی «{name[:90]}» شناسایی شد. اگر آفلاین/داستانی است Story Mode و اگر آنلاین/PvP یا نامشخص است Competitive Safe را انتخاب کن. انتخاب با خودت است.")
        self.add_chat("system", note)
        tray = getattr(self, "tray", None)
        if tray is not None and tray.isVisible():
            tray.showMessage("Ai1 · Game Mode", "بازی شناسایی شد. برای کمک در حین بازی، Game Mode را خودت فعال کن.",
                             QSystemTrayIcon.Information, 7000)

    def _game_vision_attachment(self):
        """Attach only the newest 480p JPEG frame captured while Game Mode is manually enabled."""
        if (not self._game_mode_enabled
                or not game_mode_permissions(self._game_mode_profile)["vision_capture"]
                or self._latest_game_frame is None):
            return None
        try:
            from PySide6.QtCore import QBuffer, QByteArray, QIODevice
            data = QByteArray()
            buffer = QBuffer(data)
            if not buffer.open(QIODevice.WriteOnly) or not self._latest_game_frame.save(buffer, "JPEG", CAPTURE_JPEG_QUALITY):
                return None
            return att.image_attachment(bytes(data), "game-screen.jpg", "image/jpeg")
        except Exception as exc:  # noqa: BLE001 - a failed capture must not block ordinary chat
            self.add_chat("system", f"تصویر بازی آماده نشد: {exc}")
            return None

    def send_message(self):
        if self.attach_loading():
            self.status.setText("ضمیمه‌ها هنوز در حال بارگذاری‌اند؛ چند لحظه صبر کن.")
            return
        text = self.input.text().strip()
        files = [t.att for t in self._tiles if t.att]
        if text or files:
            self.clear_attachments()
            self.input.clear()
            self.submit(text, files)

    def _cancel_application_provider(self, request, _worker):
        session = self.session_manager.get_session(request.session_id)
        if session is not None and session.client is not None:
            with self._as(session):
                session.client.cancel()

    def _dispatch_application_request(self, request):
        session = self.session_manager.get_session(request.session_id)
        if self._closing or session is None:
            self.chat_application_service.complete_local_request(request.request_id)
            return
        with self._as(session):
            session.application_request_id = request.request_id
            self._process_chat_request(request.text, list(request.attachments), request.voice)

    def _on_chat_application_event(self, event):
        session = self.session_manager.get_session(event.session_id)
        if session is None or self._closing:
            return
        if event.kind is ApplicationEventKind.REQUEST_STARTED:
            return
        if getattr(session, "application_request_id", None) != event.request_id:
            if event.kind is ApplicationEventKind.REQUEST_FAILED and not getattr(session, "application_request_id", None):
                session.application_request_id = event.request_id
            else:
                return
        with self._as(session):
            if (event.persistence_ok is False
                    and event.kind in (
                        ApplicationEventKind.REQUEST_COMPLETED,
                        ApplicationEventKind.REQUEST_FAILED,
                        ApplicationEventKind.REQUEST_CANCELLED,
                    )
                    and not self._save_warned):
                self._save_warned = True
                self.add_chat(
                    "error",
                    "ذخیره‌ی پاسخ روی دیسک ناموفق بود. پاسخ تا اولین ذخیره‌ی موفق در حافظه نگه داشته می‌شود."
                    + (f"\nعلت: {event.error}" if event.error else ""),
                )
            if event.kind is ApplicationEventKind.PROVIDER_CHUNK:
                self.on_stream_chunk(event.chunk, event.content)
            elif event.kind is ApplicationEventKind.PROVIDER_FINAL and event.result is not None:
                result = event.result
                response = dict(result.metadata)
                response.update({
                    "text": result.content,
                    "response_status": result.status.value,
                    "request_id": event.request_id,
                    "session_id": event.session_id,
                })
                self.on_stream_done(response)
            elif event.kind is ApplicationEventKind.REQUEST_CANCELLED:
                self.on_stream_done({
                    "text": event.content,
                    "stopped": True,
                    "request_id": event.request_id,
                    "session_id": event.session_id,
                })
            elif event.kind is ApplicationEventKind.REQUEST_FAILED:
                if event.metadata.get("interrupted"):
                    self.on_stream_done({
                        "text": event.content,
                        "interrupted": event.error or "Provider stream interrupted",
                        "request_id": event.request_id,
                        "session_id": event.session_id,
                    })
                else:
                    self.on_error(event.error or "Chat request failed")

    def submit(self, text, attachments=None, _voice=None):
        if self.cur.status in ("closing", "closed", "failed"):
            return
        if _voice is None:
            voice, self._voice_next = self._voice_next, False
        else:
            voice, self._voice_next = bool(_voice), False
        vision_worker = getattr(self, "_vision_worker", None)
        wait_for_vision = (
            not self.busy and vision_worker is not None and vision_worker.isRunning()
            and getattr(vision_worker, "router", None) is self.client
        )
        if self.busy and not attachments:
            try:
                control_dispatch = self.chat_application_service.dispatch_control_commands(
                    self.cur.session_id,
                    text,
                    metadata={"character_id": self.cur.cid},
                )
            except Exception:  # noqa: BLE001 - a control message must never block normal chat
                control_dispatch = None
            if control_dispatch is not None and control_dispatch.handled:
                if control_dispatch.reply_text:
                    self.add_chat("system", control_dispatch.reply_text)
                return
        self._ensure_session_conversation(self.cur)
        result = self.chat_application_service.submit_message(
            self.cur.session_id, text, attachments, voice,
            busy=self.busy, force_queue=wait_for_vision,
            conversation_id=self.cur.conversation_id,
            character_id=self.cur.cid,
        )
        if not result.accepted:
            return
        if result.queued:
            count = self.chat_application_service.pending_count(self.cur.session_id)
            if wait_for_vision:
                self.status.setText(
                    f"پیام در صف است ({count}) — تحلیل Vision متوقف می‌شود و پیام بعد از آن ارسال خواهد شد."
                )
                vision_worker.cancel_request()
                if not vision_worker.isRunning():
                    QTimer.singleShot(0, lambda owner=self.cur: self._send_pending_for_session(owner))
            else:
                self.status.setText(f"پیام در صف است ({count}) — بعد از پایان پاسخ فعلی ارسال می‌شود.")
            return
    def _process_chat_request(self, text, attachments=None, _voice=False):
        voice = bool(_voice)
        if not attachments and getattr(self, "code_chat", None) is not None and self.code_chat.handle(text, voice):
            self.chat_application_service.complete_local_request(self.cur.application_request_id)
            return                                              # Coding Agent owns this separate execution lifecycle
        if self._game_mode_enabled and len(attachments or []) < att.MAX_FILES:
            frame = self._game_vision_attachment()
            if frame is not None:
                attachments = list(attachments or []) + [frame]
                try:
                    self.chat_application_service.add_request_attachment(
                        self.cur.application_request_id, frame
                    )
                except (AttributeError, ValueError):
                    # A non-application request can still use the legacy payload.
                    pass
        self._turn_voice = voice
        if self.speaker._began:
            self.director.event("user_interrupt")
        self.safe_stop_speaker()
        self.animator.touch()
        self._body_done = []
        original_text = str(text or "")
        self.tool_agent.begin_turn(self.cur.cid)
        has_image = any(item.get("kind") == "image" for item in (attachments or []))
        command_dispatch = self.chat_application_service.dispatch_commands(
            self.cur.application_request_id,
            original_text,
            metadata={
                "has_attachments": bool(attachments),
                "has_image": has_image,
                "character_id": self.cur.cid,
            },
        )
        text = command_dispatch.rewritten_text or original_text
        force_img = bool(command_dispatch.metadata.get("force_image_search"))
        force_web = bool(command_dispatch.metadata.get("force_web_search"))
        img_search = bool(
            has_image and (force_img or self.settings.get("image_search", False))
        )
        packed = None
        if self.cur.application_request_id:
            try:
                packed = self.chat_application_service.prepare_request_attachments(
                    self.cur.application_request_id, text=text, search=img_search
                )
            except (AttributeError, ValueError):
                packed = None
        if packed is None and attachments:
            packed = att.compose(text, attachments, search=img_search)
        if packed is not None:
            # Search must only run with a successfully prepared image payload.
            img_search = bool(packed.get("images")) and (force_img or self.settings.get("image_search", False))
        if packed and packed.get("errors"):
            self.show_attach_error(packed["errors"])
            if not packed.get("prepared_count") and not text.strip():
                self.chat_application_service.fail_request(
                    self.cur.application_request_id,
                    "No attachment content could be prepared.",
                )
                return
        if packed is not None and force_web:
            # Preserve the user's literal /web command in the visible and durable chat history.
            presentation = att.compose(original_text, attachments, search=img_search)
            packed["display"] = presentation["display"]
            packed["stored"] = presentation["stored"]
        self._turn_extra = packed
        self._turn_attach_kinds = [str(item.get("kind")) for item in (attachments or [])]
        self.add_chat(
            "user",
            packed["display"] if packed else original_text,
            images=attachments if packed else None,
        )
        self._tool_plan = (
            None
            if command_dispatch.handled and not command_dispatch.continue_chat
            else self.tool_agent.plan(text)
        )
        self.save_message("user", packed["stored"] if packed else original_text)
        if command_dispatch.handled and not command_dispatch.continue_chat:
            self.reply_local(command_dispatch.reply_text or "فرمان اجرا شد.")
            return
        self.busy = True
        self.gen_stop_btn.show()
        self.set_status("st_thinking")
        self.set_badge("connecting", self.client.preview_route())
        self.show_upload_tiles(attachments)
        self.director.event("user_message")
        self.director.event("response_started")
        self._plain_retry = False
        self._web_found = None
        self._image_search_turn = False
        if img_search and packed:
            self._image_search_turn = True
            self.begin_image_search(text, packed, packed["images"])
            return
        query, forced = (
            websearch.plan(text)
            if self.settings.get("web_search", True) or text.lstrip().startswith("/") or force_web
            else (None, False)
        )
        if force_web:
            query, forced = str(text or "").strip()[:300], True
        if query and not forced and self._tool_plan is not None and self._tool_plan.strong:
            query = None                                          # a request about this PC (files, apps, RAM...) is not a web question
        if query and not forced and self._tool_plan is not None and getattr(self._tool_plan, "web", False):
            query = None                                          # research / "read this page" requests go through the web tools (kira/webintel), not the one-shot search
        if query:
            self.begin_web_search(query, packed if packed else text, packed["images"] if packed else [])
            return
        self.begin_reply()

    def begin_reply(self):
        try:
            self.start_worker(plain=False)
        except Exception as exc:                                  # noqa: BLE001 - never leave the window stuck in 'busy'
            self.chat_application_service.fail_request(
                self.cur.application_request_id, f"{type(exc).__name__}: {exc}"
            )

    # ---- web search ----
    def toggle_web_search(self, on):
        self.settings["web_search"] = bool(on)
        save_settings(self.settings)
        self.update_web_tip()

    def update_web_tip(self):
        self.web_btn.setToolTip("جست‌وجوی وب: " + ("روشن — کیرا وقتی سؤال به اطلاعات روز نیاز دارد (قیمت، خبر، امروز…) یا بگویی «سرچ کن» در وب می‌گردد. "
                                                  "برای اجبار: /web عبارت" if self.web_btn.isChecked() else "خاموش — فقط با نوشتن /web عبارت جست‌وجو می‌کند"))

    def gemini_credentials(self):
        """(api_key, model) of the Gemini provider the person already configured, or None. Used for Google-grounded search."""
        for pid, cfg in (self.settings.get("providers") or {}).items():
            if "generativelanguage" in str(cfg.get("base_url") or "") and str(cfg.get("api_key") or "").strip():
                model = next((r["model"] for r in self.settings.get("routes", []) if r.get("provider") == pid and r.get("model")), "")
                return str(cfg["api_key"]).strip(), str(model).removeprefix("models/") or "gemini-flash-latest"
        return None

    # ---- image search (a picture is looked up on the web) ----
    IMAGE_QUERY_ASK = "این تصویر چیست؟ فقط عبارت جست‌وجو را بنویس."

    def toggle_image_search(self, on):
        on = bool(on)
        self.settings["image_search"] = on
        save_settings(self.settings)
        for widget in (getattr(self, "img_search_btn", None),):
            if widget is not None and widget.isChecked() != on:
                widget.blockSignals(True)
                widget.setChecked(on)
                widget.blockSignals(False)
        bubble = getattr(self, "bubble", None)
        if bubble is not None and bubble.img_btn.isChecked() != on:
            bubble.set_image_search(on)
        self.update_image_search_tip()

    def update_image_search_tip(self):
        btn = getattr(self, "img_search_btn", None)
        if btn is not None:
            btn.setToolTip("جست‌وجوی تصویری: " + ("روشن — عکسی که می‌فرستی در وب جست‌وجو می‌شود تا معلوم شود چیست. "
                                                  "ترتیب: Gemini (با خودِ عکس) ← توصیف عکس و جست‌وجو با Tavily ← DuckDuckGo. "
                                                  "برای یک پیام: /img" if btn.isChecked() else
                                                  "خاموش — عکس فقط به مدل داده می‌شود. برای جست‌وجوی یک عکس، پیام را با /img شروع کن."))

    def make_image_query(self, images, hint, client=None):
        """Runs in the search thread: the active vision model looks at the picture and writes a short web query."""
        msg = {"role": "user", "content": (hint or self.IMAGE_QUERY_ASK), "images": images}
        return (client or self.client).chat([msg], websearch.IMAGE_QUERY_PROMPT, 0.1)

    @staticmethod
    def _merge_search_content(base_content, images, addition, *, image_search=False):
        if isinstance(base_content, dict) and "files" in base_content and "text" in base_content:
            updated = dict(base_content)
            current_text = str(updated.get("text") or "").strip()
            if not current_text:
                if images and image_search:
                    current_text = "این تصویر چیست؟ با کمک نتایج جست‌وجوی وب بگو."
                elif images:
                    current_text = "این تصویر را ببین و نظرت را بگو."
                elif updated.get("files"):
                    current_text = "این فایل را بخوان و درباره‌اش نظر بده."
            updated["text"] = (current_text + "\n\n" if current_text else "") + str(addition or "")
            updated["images"] = list(images or [])
            updated["search"] = bool(image_search)
            return updated
        return {
            "model": str(base_content or "") + "\n\n" + str(addition or ""),
            "images": list(images or []),
        }

    def begin_image_search(self, hint, base_text, images):
        key = str(self.settings.get("tavily_api_key", "")).strip()
        fallback = bool(self.settings.get("web_fallback", True))
        gem = self.gemini_credentials()
        self._search_token += 1
        self._search_base = (base_text, images)
        self.status.setText("🔎 در حال جست‌وجوی تصویر در وب…")
        self._search_worker = SearchWorker(self._search_token, hint or "تصویر", key, self.settings.get("web_depth", "basic"),
                                           user_text=hint, gemini=gem, fallback=fallback, images=images,
                                           describe=lambda c=self.client: self.make_image_query(images, hint, c))
        self._search_worker.done.connect(self.cur.relay.search_done)
        self._search_worker.start()

    def begin_web_search(self, query, base_text, images):
        key = str(self.settings.get("tavily_api_key", "")).strip()
        fallback = bool(self.settings.get("web_fallback", True))
        if not key and not fallback:
            self.add_chat("system", "🌐 برای جست‌وجوی وب کلید Tavily لازم است (تب عمومی ← «کلید جست‌وجوی وب»؛ رایگان از tavily.com). بدون وب ادامه می‌دهم.")
            self.begin_reply()
            return
        self._search_token += 1
        self._search_base = (base_text, images)
        self.status.setText(f"🌐 در حال جست‌وجوی وب: «{query[:60]}»…")
        conversation_id = self._ensure_session_conversation(self.cur)
        history = self.chat_application_service.conversation_context(
            8, session_id=self.cur.cid, conversation_id=conversation_id
        )
        # The user's own words are sent unchanged. Only a short follow-up that points back at the chat is rewritten by the model.
        rewrite = (lambda c=self.client: self.make_search_query(history, query, c)) if websearch.is_followup(query) else None
        self._search_worker = SearchWorker(self._search_token, query, key, self.settings.get("web_depth", "basic"),
                                           rewrite=rewrite, user_text=query, gemini=self.gemini_credentials(), fallback=fallback)
        self._search_worker.done.connect(self.cur.relay.search_done)
        self._search_worker.start()

    SEARCH_QUERY_PROMPT = ("You write ONE web search query for a search engine. Use the conversation to resolve references such as "
                           "'this song', 'him', 'search better'. Keep titles and names exactly as the user wrote them (Persian stays "
                           "Persian). No quotes, no explanation, at most 12 words. Output only the query.")

    def make_search_query(self, history, fallback, client=None):
        """Runs in the search thread: ask the active model for a precise query; any failure -> the plain query."""
        out = (client or self.client).chat(history[-6:], self.SEARCH_QUERY_PROMPT, 0.1)
        line = next((ln.strip() for ln in str(out or "").splitlines() if ln.strip()), "")
        line = line.strip("\"'«»`").removeprefix("Query:").removeprefix("query:").strip()
        return line if 2 <= len(line) <= 160 else fallback

    WEB_TEST_QUERY = "آهنگ تو که معنای عشقی"

    def test_web_search(self):
        """Settings button: one real Tavily search with the key typed in the box (no need to save first)."""
        key, depth = self.tavily_key.text().strip(), self.web_depth.currentData()
        gem = self.gemini_credentials()
        self.web_test_btn.setEnabled(False)
        self.web_test_btn.setText("در حال آزمایش (چند ثانیه)…")
        self._web_test_worker = TaskWorker(lambda: websearch.diagnose(key, depth, self.WEB_TEST_QUERY, gem))
        self._web_test_worker.done.connect(self.on_web_test_done)
        self._web_test_worker.start()

    @staticmethod
    def _assessment_text(a):
        if not a or not a.get("phrase"):
            return ""
        if a.get("matched"):
            return f"عبارت جست‌وجو در منبع {'، '.join(str(n) for n in a['matched'])} عیناً دیده شد."
        return f"⚠ عبارت جست‌وجو در هیچ‌کدام از {a.get('checked', 0)} منبع خوانده‌شده عیناً پیدا نشد."

    def on_web_test_done(self, res):
        self.web_test_btn.setEnabled(True)
        self.web_test_btn.setText("آزمایش جست‌وجوی وب")
        ok, rep = res
        if not ok:
            QMessageBox.warning(self, "آزمایش جست‌وجوی وب", f"آزمایش انجام نشد:\n{rep}")
            return
        lines = []
        for name, label in (("tavily", "Tavily (اول)"), ("google", "Google / Gemini (دوم)"), ("ddg", "DuckDuckGo (سوم)")):
            e = rep["engines"][name]
            lines.append(f"{label}: " + (f"✓ کار می‌کند — {e['sources']} منبع · «{e['first'][:50]}»" if e["ok"] else f"✕ {e['error']}"))
        extra = self._assessment_text(rep.get("assessment"))
        QMessageBox.information(self, "آزمایش جست‌وجوی وب",
                                "\n".join(lines) + f"\n\nعبارت آزمایش: «{rep['probe']}»" + (f"\n{extra}" if extra else "")
                                + "\nکیرا به همین ترتیب امتحان می‌کند و از اولین موتور سالم استفاده می‌شود.")

    def add_sources(self, found):
        html = sources_html(found.get("results"), f"منابع ({websearch.ENGINE_NAMES.get(found.get('engine'), 'وب')}) · جست‌وجو برای «{found.get('query', '')}»")
        a = found.get("assessment") or {}
        if html and a.get("phrase"):
            text = self._assessment_text(a)
            colour = "#7fd99a" if a.get("matched") else "#ffb86b"
            html += f'<p dir="rtl" align="right" style="margin:3px 0 0 0;color:{colour};">{text if text.startswith("⚠") else "✓ " + text}</p>'
        if html:
            ui_dir = "rtl" if self.settings.get("ui_lang", "fa") == "fa" else "ltr"
            self.chat.append(message_html("system", "", "", ui_dir, html))
            bar = self.chat.verticalScrollBar()
            bar.setValue(bar.maximum())

    def on_web_done(self, token, ok, result):
        if self._closing or token != self._search_token or not self.busy:
            return                                                   # stopped / superseded meanwhile
        if ok:
            base, images = self._search_base
            self._web_found = result
            if result.get("note"):
                self.add_chat("system", "🌐 " + result["note"])
            self._turn_extra = self._merge_search_content(
                base, images, websearch.format_block(result),
                image_search=bool(getattr(self, "_image_search_turn", False)),
            )
            self.status.setText(f"{'🔎 Google' if result.get('engine') == 'google' else ('🦆 DuckDuckGo' if result.get('engine') == 'ddg' else '🌐 Tavily')}: {len(result['results'])} منبع پیدا شد؛ در حال پاسخ دادن…")
        elif getattr(self, "_image_search_turn", False):
            # the picture itself is still in the request: she answers from what she sees and says what is unconfirmed
            self.add_chat("system", f"🔎 جست‌وجوی تصویری انجام نشد: {result}")
            base, images = self._search_base
            self._turn_extra = self._merge_search_content(
                base, images,
                "[جست‌وجوی وب برای این تصویر انجام نشد. فقط از روی چیزی که در تصویر می‌بینی جواب بده، "
                "حدس نزن و هر چیزی که مطمئن نیستی را صریح «تأییدنشده» بگو.]",
                image_search=False,
            )
        else:
            # no usable web result: do not let the model improvise from memory; Kira says she does not know
            self.add_chat("system", f"🌐 جست‌وجوی وب انجام نشد: {result}")
            self._turn_extra = None
            self.reply_local(websearch.failure_reply(result), "sad")
            self.finish_request(None)
            self._send_next_pending()
            return
        self.begin_reply()

    def start_worker(self, plain):
        window = int(self.settings.get("memory_context_limit", 12))
        conversation_id = self._ensure_session_conversation(self.cur)
        history = self.chat_application_service.conversation_context(
            window, character_id=self.cur.cid, conversation_id=conversation_id
        )
        mode = self.detect_mode(history)                          # Active Mode of THIS message (None = switched off in settings)
        try:
            older = self.chat_application_service.recent_messages(
                window + 40, character_id=self.cur.cid, conversation_id=conversation_id
            )[:-window] if window else []
            # Every character has its own saved conversation; only Kira owns the legacy evidence index.
            character_id = self.cur.cid
            memory_block = self.memory_service.build_block(
                character_id,
                older,
                voice_samples=(mode is None or mode.name == modes.CHAT),
                query=evidence_memory.query_from_context(history) if character_id == "kira" else None,
                budget=evidence_memory.budget_for(self.settings, self.client),
            )
            total = self.chat_application_service.message_count(
                character_id, conversation_id
            )
            if self.memory_service.needs_summary(character_id, total, window):
                self.memory_service.maintain(
                    character_id,
                    self.chat_application_service.recent_messages(
                        min(total, 3000), character_id=character_id, conversation_id=conversation_id
                    ),
                    window,
                )
        except Exception:                                         # noqa: BLE001 - memory is a bonus, never block a reply
            memory_block = ""
        try:                                                      # her persisted mood + how he seems right now (same text for every provider)
            mood_block = mood.build_block(mode.name if mode else modes.CHAT)
        except Exception:                                         # noqa: BLE001
            mood_block = ""

        # Brain planning remains application policy; only its prompt contribution
        # is injected into the independent ContextBuilder.
        try:
            extra0 = self._turn_extra
            has_att = bool(self._turn_attach_kinds or (extra0 and (extra0.get("images") or "--- فایل ضمیمه" in str(extra0.get("model", "")))))
            last_user = next((m.get("content", "") for m in reversed(history) if m.get("role") == "user"), "")
            self._brain_user_text = str(last_user)
            self._brain_mode_name = mode.name if mode else None
            self._brain = brain.decide(last_user, mode, self._tool_plan, has_att, self.tool_agent.tasks.active() is not None, self.settings)
        except Exception:                                         # noqa: BLE001
            self._brain = brain.Decision()

        character_layer = self.character_service.prompt_for(self.settings)
        body_context = ""
        if self.body_active():                                    # preserve existing 3D body instruction and completed-action note
            body_context = ("" if plain else body_ctl.format_hint()) + body_ctl.done_note(self._body_done)

        context = {
            "messages": history,
            "character_id": self.cur.cid,
            "character_profile": self.active_character(),
            "settings": self.settings,
            "memory": memory_block,
            "mood": mood_block,
            "character_context": character_layer,
            "format_hint": "" if plain else self.director.format_hint(),
            "voice_input": self._turn_voice,
            "mode": mode,
            "body_context": body_context,
            "active_capabilities": tuple(sorted(getattr(self._tool_plan, "categories", ()) or ())),
            "turn_extra": self._turn_extra,
            "max_context_chars": self.settings.get("chat_context_char_limit", 0),
        }

        self._stream_begin()
        temperature = modes.temperature_for(mode, self.settings["temperature"]) if mode else self.settings["temperature"]
        relay = self.cur.relay
        request_id = self.cur.application_request_id
        if not request_id:
            raise RuntimeError("No active Chat application request is associated with this session")
        self.worker = self.chat_application_service.start_provider_request(
            request_id, context,
            provider_callbacks={"tool_event": relay.tool, "event": relay.stream_event},
            provider_event_dispatcher=relay.provider_event.emit,
            router=self.client, temperature=temperature,
            retry_index=1 if plain else 0, agent=self.tool_agent, plan=self._tool_plan,
            role=self._brain.stage, route_id=self._brain.route_id,
        )
        self.refresh_tab_buttons()

    MODE_LABELS = {"chat": "گپ", "task": "کار / کمک", "strict": "فقط جواب"}

    def detect_mode(self, context):
        """Active Mode for the message being answered (see kira/modes.py). Never raises: on any problem the old prompt is used."""
        self._turn_mode = None
        if not self.settings.get("active_modes", True):
            return None
        try:
            users = [m["content"] for m in context if m.get("role") == "user"]
            extra = self._turn_extra
            # an image or a file is attached: the structured kinds decide (the text markers are only a fallback)
            has_attachment = bool(self._turn_attach_kinds or (extra and (extra.get("images") or "--- فایل ضمیمه" in str(extra.get("model", "")))))
            earlier = users[:-1]
            try:                                                   # a "no jokes" request must outlive the short context window
                conversation_id = self.cur.conversation_id
                longer = [
                    m["content"] for m in self.chat_application_service.recent_messages(
                        80, character_id=self.cur.cid, conversation_id=conversation_id
                    ) if m.get("role") == "user"
                ]
                if len(longer) > len(users):
                    earlier = longer[:-1]
            except Exception:                                      # noqa: BLE001
                pass
            self._turn_mode = modes.detect(users[-1] if users else "", earlier, has_attachment)
        except Exception:                                         # noqa: BLE001
            self._turn_mode = None
        return self._turn_mode

    def stop_generation(self):
        """Stop button: ends the answer now; text received so far is kept."""
        if getattr(self, "code_chat", None) is not None and self.code_chat.stop(self.cur):
            self.chat_application_service.complete_local_request(self.cur.application_request_id)
            return                                                # the Coding Agent owns its separate task lifecycle
        if self._search_worker is not None and self._search_worker.isRunning():
            self._search_token += 1                                   # the late search result is ignored
            self.add_chat("system", "جست‌وجو متوقف شد.")
            self.chat_application_service.cancel_request(self.cur.application_request_id)
            return
        if not any(o.busy for o in self.sessions.values() if o is not self.cur):
            self.tool_agent.request_cancel()                      # also stops a tool loop between two steps (the tool agent is shared:
                                                                  # not while another character is in the middle of its own task)
        self.chat_application_service.cancel_request(self.cur.application_request_id)
        self.gen_stop_btn.setEnabled(False)

    # ---- body control (the 3D body moves on chat commands: kira/body.py) ----
    def _install_chat_commands(self):
        """Wire the existing feature owners into the shared chat command registry."""
        registry = create_default_command_registry(
            permission_checker=self._check_chat_command_permission,
            usage_parser=usage.parse_command,
            usage_report=usage.report,
            body_parser=body_ctl.parse_user_command,
            body_is_active=self.body_active,
            body_handler=self.run_body,
            web_parser=websearch.plan,
            image_parser=websearch.image_command,
            task_control_parser=parse_tool_task_control,
            task_running_checker=self.tool_agent.is_task_running,
            tool_agent=self.tool_agent,
            desktop_action_matcher=match_safe_action,
            desktop_action_handler=lambda text: run_safe_action(text, allow_desktop=True),
        )
        self.chat_application_service.set_command_registry(registry)
        self.command_registry = registry

    def _check_chat_command_permission(self, command, _request):
        if "desktop.launch" in command.required_permissions:
            if self._game_mode_profile == COMPETITIVE_SAFE_MODE:
                return PermissionDecision(
                    False,
                    "در حالت Competitive Safe اجرای میانبرهای دسکتاپ غیرفعال است.",
                )
        return True

    def body_active(self):
        """True while Kira's VRM body is on screen in the front chat and the setting 'body_control' is on."""
        return bool(self.settings.get("body_control", True) and getattr(self.animator, "body_enabled", False)
                    and getattr(self.animator, "kira_art_active", True))

    def run_body(self, names):
        """Perform body commands, each name once per message (a streamed reply is parsed again and again)."""
        if not names or not self.body_active():
            return
        fresh = [n for n in names if n not in self._body_done]
        if not fresh:
            return
        self._body_done.extend(fresh)
        try:
            self.animator.body.emit(body_ctl.payload(fresh))
        except Exception:                                      # noqa: BLE001 - a body move must never break the chat
            pass

    # ---- live text ----
    def display_text(self, raw):
        """User-visible part of a (possibly unfinished) streamed reply: emotion tag removed, half-written tag hidden."""
        head = raw.lstrip()
        if head.startswith("[") and "]" not in head and len(head) < 62:       # a tag still being typed by the model
            return ""
        return scrub_lines(self.director.parse_reply(raw).text)       # echoed router / system notes are never shown

    def _stream_begin(self):
        self._stream_text, self._stream_pos, self._stream_dirty, self._stream_mood = "", None, False, None
        self._emotion_applied = False
        self._t_req = time.monotonic()
        self._t_first = None
        self._speech_live = False                                   # speech of THIS reply has started while it is still being written
        self.speaker.stream_reset()
        self._stream_timer.start()

    def _speak_stream(self, text):
        """Speech starts from the first finished sentence while the model is still writing (setting: stream_speech)."""
        if not (self.voice_btn.isChecked() and self.settings.get("stream_speech", True)):
            return
        try:
            self.speaker.stream_text(text)
            self._speech_live = True
        except Exception as exc:                                    # noqa: BLE001
            self.on_voice_error(f"صدا ناموفق بود: {type(exc).__name__}: {exc}")

    def on_stream_chunk(self, piece, accumulated_content=None):
        # ResponseHandler owns ordered aggregation; the window keeps only the
        # current text snapshot required by its existing incremental renderer.
        self._stream_text = (str(accumulated_content) if accumulated_content is not None
                             else self._stream_text + str(piece))
        self._stream_dirty = True

    def _stream_flush(self, final=False):
        if not self._stream_dirty and not final:
            return
        self._stream_dirty = False
        meta = self.director.parse_reply(self._stream_text)         # pure parse: no side effects
        self.run_body(meta.body)                                    # [body:...] tags written by the model
        text = self.display_text(self._stream_text)
        if meta.source == "tag" and not self._emotion_applied:     # the model's own tag arrived: react right away
            self._emotion_applied = True
            self.director.on_reply(meta)
        if not text.strip():
            return
        self._speak_stream(text)
        name = self.character_service.display_name(self.settings)
        ui_dir = "rtl" if self.settings.get("ui_lang", "fa") == "fa" else "ltr"
        html = message_html("assistant", name, text, ui_dir, accent=self.accent())
        doc = self.chat.document()
        cur = QTextCursor(doc)
        if self._stream_pos is None:
            self._stream_pos = max(0, doc.characterCount() - 1)
        cur.setPosition(self._stream_pos)
        cur.movePosition(QTextCursor.End, QTextCursor.KeepAnchor)
        cur.removeSelectedText()
        if self._stream_pos > 0:
            cur.insertBlock()
        cur.insertHtml(html)
        if getattr(self, "bubble", None) is not None:
            self.bubble.set_live(name, text, ui_dir)
        bar = self.chat.verticalScrollBar()
        bar.setValue(bar.maximum())

    # ---- indicator ----
    BADGE_HEAD = {"idle": "● Ready", "connecting": "◌ Connecting", "waiting": "◌ Processing", "streaming": "● Connected",
                  "failover": "↪ Failover", "done": "✓ Done", "stopped": "■ Stopped", "error": "✕ Error"}

    def set_badge(self, phase, info=None):
        """Indicator next to the input. `info` comes straight from the router (never guessed from settings)."""
        self._badge_phase = phase
        if info:
            self._route_info = info
        self.cur.badge = (phase, info)
        if self.cur is not self.front:
            return
        if phase == "error":
            text, tip = self.BADGE_HEAD["error"], "آخرین درخواست ناموفق بود."
        elif not info:
            text = self.BADGE_HEAD[phase] + (" · No active route" if phase == "idle" else "")
            tip = "هیچ Route فعالی آماده نیست. تب Route را ببین."
        else:
            kind = "Cloud" if info.get("kind") == "cloud" else "Local"
            text = f"{self.BADGE_HEAD[phase]} · {info['label']} / {info['model']} · {kind}"
            tip = (f"Provider: {info['label']}\nModel: {info['model']}\nنوع: {kind}\nRoute: {info.get('route_id', '')}\n"
                   "کلیک: جزئیات و انتخاب دستی مدل")
        glyph = text.split(" ", 1)[0]
        compact = f"{glyph} {info['label']} / {info['model']}" if (info and phase != "error") else text
        self.route_badge.setText(text, display=compact)             # full text for tests/tooltips, short one on the chip
        self.route_badge.setToolTip(tip)

    MENU_ROUTES = 500                                          # effectively all models: the menus scroll (menu-scrollable) instead of cutting the list

    def build_badge_menu(self):
        menu = self.route_menu
        menu.clear()
        menu.addAction("جزئیات Route فعال…", self.show_route_details)
        menu.addAction(self.t("route_open"), lambda: self.go_tab(self.tab_keys.index("tab_ai")))
        menu.addSeparator()
        manual = self.settings.get("manual_route_id", "")
        auto = menu.addAction("خودکار (بر اساس اولویت)")
        auto.setCheckable(True)
        auto.setChecked(not manual)
        auto.triggered.connect(lambda checked=False: self.select_route(""))
        routes = self.client.available_routes()
        shown = routes[: self.MENU_ROUTES]
        chosen = next((r for r in routes if r["route_id"] == manual), None)
        if chosen is not None and chosen not in shown:         # the manually selected route is always visible
            shown = shown[:-1] + [chosen]
        for info in shown:
            icon = "☁" if info["kind"] == "cloud" else "⌂"
            model = info["model"] if len(info["model"]) <= 38 else info["model"][:37] + "…"
            act = menu.addAction(f"{icon}  {info['label']} / {model}")
            act.setCheckable(True)
            act.setChecked(info["route_id"] == manual)
            act.triggered.connect(lambda checked=False, rid=info["route_id"]: self.select_route(rid))
        if len(routes) > len(shown):
            menu.addSeparator()
            more = menu.addAction(f"{len(routes) - len(shown)} Route دیگر در مدیریت Route…")
            more.triggered.connect(lambda checked=False: self.go_tab(self.tab_keys.index("tab_ai")))

    def show_route_details(self):
        info = self._route_info or self.client.preview_route()
        if not info:
            QMessageBox.information(self, "Route", "هیچ Route فعالی آماده نیست.")
            return
        st = next((x for x in self.client.status() if x["name"] == info["route_id"]), {})
        route = route_model.find_route(self.settings, info["route_id"]) or {}
        manual = self.settings.get("manual_route_id", "")
        lines = [f"Provider: {info['label']}", f"Model: {info['model']}", f"نوع اتصال: {'Cloud' if info['kind'] == 'cloud' else 'Local'}",
                 f"Route: {info['route_id']}  ({'انتخاب دستی' if manual == info['route_id'] else 'انتخاب خودکار'})",
                 f"وضعیت سلامت: {st.get('health', 'unknown')}", f"Timeout: {route.get('timeout', '-')}s · Cooldown: {route.get('cooldown', '-')}s"]
        if st.get("last_ms") is not None:
            lines.append(f"آخرین پاسخ موفق: {st['last_ms']} ms")
        if st.get("last_error"):
            lines.append(f"آخرین خطا: {st['last_error']}")
        QMessageBox.information(self, "جزئیات Route فعال", "\n".join(lines))

    def select_route(self, route_id):
        """Manual choice ('' = automatic). Wins over priority; failover (if on) may still move on when it fails."""
        try:
            route_model.set_manual(self.settings, route_id)
        except KeyError:
            return
        if route_id:
            self.client.reset_cooldowns(route_id)
        self.save_now()
        self.refresh_route_list()
        if not self.busy:
            self.set_badge("idle", self.client.preview_route())

    def save_now(self):
        """Route Manager autosave."""
        try:
            save_settings(self.settings)
            return True
        except Exception as exc:                                  # noqa: BLE001
            if hasattr(self, "route_status"):
                self.route_status.setText(f"✕ ذخیره‌ی خودکار ناموفق بود: {exc}")
            return False

    # ---- events / completion ----
    def on_stream_event(self, e):
        phase = e.get("phase")
        self.on_upload_event(phase, e.get("percent"))
        if phase == "uploading":                                   # request body (images / files) being sent to the model
            self.status.setText(f"در حال ارسال ضمیمه‌ها به مدل… {e.get('percent', 0)}%")
            return
        self.set_badge(phase, e)
        if phase == "streaming" and self._t_first is None:
            self._t_first = time.monotonic() - (self._t_req or time.monotonic())
            mode = getattr(self, "_turn_mode", None)
            self.status.setText(f"اولین Token بعد از {int(self._t_first * 1000)} ms · {e['label']} / {e['model']}"
                                + (f" · حالت: {self.MODE_LABELS[mode.name]}" if mode else ""))
        elif phase == "failover":
            self.status.setText(f"Failover → {e['label']} / {e['model']}")
        elif phase in ("connecting", "waiting"):
            self.set_status("st_thinking")

    def on_tool_event(self, e):
        """Status line while a tool runs (no layout change). The real outcome is always reported by Kira's answer."""
        phase = e.get("phase")
        if phase == "tool_start":
            self.status.setText(f"🔧 {e.get('label', '')}…")
        elif phase == "plan_step":
            self.status.setText(f"🧭 مرحله {e.get('i', '?')} از {e.get('n', '?')}: {e.get('title', '')}")
        elif phase == "plan_ready":
            self.status.setText(f"🧭 برنامه آماده شد: {e.get('n', '?')} مرحله" + (f" — {e['estimate']}" if e.get("estimate") else ""))

    def on_stream_done(self, res):
        if self._closing:
            return
        self._stream_timer.stop()
        raw = res.get("text", "")
        meta = self.director.parse_reply(raw)
        self.run_body(meta.body)
        text = meta.text
        if not text.strip() and not res.get("stopped") and not res.get("interrupted") and not getattr(self, "_plain_retry", False):
            self._plain_retry = True            # model answered with a tag only: ask again without tags (counted as a retry)
            self.start_worker(plain=True)
            return
        if not res.get("stopped") and not res.get("interrupted"):
            request_id = getattr(self.cur, "application_request_id", None)
            if request_id:
                self.chat_application_service.complete_request(
                    request_id, raw, metadata=res, persist=bool(text.strip())
                )
        self._stream_flush(final=True)
        self._stream_pos = None
        self.bubble.commit_live()
        self.finish_request(res)
        if res.get("stopped"):
            if text.strip():
                self.save_message("assistant", raw, status="cancelled", metadata={"stream": "stopped"}, persist=False)
            self.add_chat("system", "تولید پاسخ متوقف شد." + (" متن دریافت‌شده نگه داشته شد." if text.strip() else ""))
            if self._speech_live:
                self.safe_stop_speaker()                           # the Stop button also silences the rest of the spoken reply
            self.animator.set_expression("neutral", hold=2)
        elif res.get("interrupted"):
            self.save_message("assistant", raw, status="interrupted", metadata={"stream": "provider_interrupted"}, persist=False)
            self.add_chat("error", f"ارتباط وسط پاسخ قطع شد؛ بخش دریافت‌شده نگه داشته شد و تکرار نمی‌شود.\n{res['interrupted']}")
            if self._speech_live:
                self.speaker.stream_end()                          # what arrived is still spoken to its end
            self.director.event("response_failed")
        elif not text.strip():
            self.add_chat("error", self.t("empty"))
            self.director.event("response_failed")
        else:
            self.save_message("assistant", raw, persist=False)
            try:                                                   # quiet second look (rules; optional background model call)
                brain.after_turn(self.client, self.settings, getattr(self, "_brain", brain.Decision()), getattr(self, "_brain_user_text", ""),
                                 text, res.get("tools"), getattr(self, "_brain_mode_name", None), bool(self._tool_plan))
            except Exception:                                      # noqa: BLE001
                pass
            if not self._emotion_applied:                          # no tag from the model: tag-less fallback (keywords / neutral)
                self.director.on_reply(meta)
            if self._speech_live:
                self.speaker.stream_end()                          # the sentences were spoken while it was written: say the tail
            else:
                self.say(text)
        if self._web_found and text.strip():
            self.add_sources(self._web_found)
        self._web_found = None
        self._send_next_pending()

    def on_error(self, error):
        if self._closing:
            return
        self._stream_timer.stop()
        self._stream_flush(final=True)
        self._stream_pos = None
        if getattr(self, "_speech_live", False):
            self.speaker.stream_end()
        self.add_chat("error", self.t("reply_err", e=error))
        self.director.event("response_failed")
        self.finish_request(None)
        self.set_badge("error")
        self.check_status()
        self._send_next_pending()

    def _send_next_pending(self, session=None):
        """Ask the Chat application service to drain only the completed session's FIFO queue."""
        session = session or self.cur
        if self._closing or self.sessions.get(session.cid) is not session:
            return
        if self._vision_session is session and not self._worker_is_running(self._vision_worker):
            worker = self._vision_worker
            if worker is not None:
                try:
                    worker.deleteLater()
                except RuntimeError:
                    pass
                self._vision_worker = None
            self._vision_session = None
        self.chat_application_service.dispatch_next(session.session_id, busy=session.busy)
        profiles = self.character_service.all_profiles(self.settings)
        if session.cid not in profiles and not self._session_has_pending_chat_work(session):
            self._schedule_chat_callback(self.sync_sessions)

    def finish_request(self, res=None):
        self.clear_upload_tiles()
        self.busy = False
        if self.cur is not self.front:
            self.cur.unread = True                                 # an answer arrived for a tab you are not looking at
        self.refresh_tab_buttons()
        self._speech_live = False
        self.gen_stop_btn.hide()
        self.gen_stop_btn.setEnabled(True)
        self.send_btn.setEnabled(True)
        self.input.setEnabled(True)
        self.input.setFocus()
        self.set_status("st_ready")
        if res and res.get("provider"):
            m = res.get("metrics") or {}
            detail = f"آخرین پاسخ: {res['provider']} / {res['model']}"
            if m.get("total_ms") is not None:
                detail += f" ({m['total_ms']} ms"
                if m.get("first_token_ms") is not None:
                    detail += f" · اولین Token {m['first_token_ms']} ms"
                detail += ")"
            if m.get("failovers"):
                detail += f" · Failover×{m['failovers']}"
            self.status.setText(detail)
            self.set_badge("stopped" if res.get("stopped") else "done",
                           {"route_id": res["route_id"], "provider": res["provider"], "label": res["label"],
                            "model": res["model"], "kind": res["kind"]})
        elif res is not None:
            self.set_badge("idle", self.client.preview_route())
        self.refresh_route_list()

    def reply_local(self, text, expression="happy"):
        self.add_chat("assistant", text)
        self.save_message("assistant", text)
        self.chat_application_service.complete_local_request(self.cur.application_request_id)
        self.animator.set_expression(expression, hold=4)
        self.say(text)

    def save_message(self, role, content, *, status="complete", metadata=None, persist=True):
        """Persist through ChatApplicationService; keep character memory/mood observation in the UI adapter."""
        if persist:
            outcome = self.chat_application_service.persist_message(
                self.cur.session_id, role, content,
                request_id=getattr(self.cur, "application_request_id", None),
                conversation_id=getattr(self.cur, "conversation_id", None),
                status=status, character_id=self.cur.cid, metadata=metadata,
            )
            ok = outcome.ok
        else:
            ok = True
        self.memory_service.observe(self.cur.cid, role, content)
        try:
            self._sync_mood_character()
            if role == "user":
                mood.on_user_message(content)
                self.apply_mood_to_avatar()
            elif role == "assistant":
                meta = self.director.parse_reply(content)
                if meta is not None:
                    mood.on_reply(meta.emotions, meta.intensity)
        except Exception:                                         # noqa: BLE001 - mood is a bonus, never block the chat
            pass
        if persist and ok:
            self._save_warned = False
        elif persist and not ok and not self._save_warned:
            self._save_warned = True
            self.add_chat("error", "ذخیره‌ی گفتگو روی دیسک ناموفق بود. گفتگو تا بسته‌شدن برنامه در حافظه می‌ماند و با اولین ذخیره‌ی موفق نوشته می‌شود."
                                   f"\nعلت: {self.chat_application_service.last_persistence_error}")
        return ok

    def safe_stop_speaker(self):
        """Stopping the voice must never be able to stop the app from doing its real work (sending a chat message)."""
        try:
            self.speaker.stop()
        except Exception as exc:                                  # noqa: BLE001
            self.on_voice_error(f"توقف صدا ناموفق بود: {type(exc).__name__}: {exc}")

    def say(self, text):
        if self.voice_btn.isChecked():
            try:
                self.speaker.speak(text)
            except Exception as exc:                              # noqa: BLE001
                self.on_voice_error(f"صدا ناموفق بود: {type(exc).__name__}: {exc}")

    def on_mood_changed(self, mood):
        if mood == "bored" and self.settings.get("idle_talk", True) and not self.busy \
                and time.time() - getattr(self, "_last_idle", 0) > 180:
            self._last_idle = time.time()
            lines = self.reactions.get("_idle", {}).get(self.settings.get("ui_lang", "fa"), [])
            if lines and self.voice_btn.isChecked():
                self.speaker.speak(random.choice(lines), -5, -3, cache=True)

    # ---------- click reactions ----------
    def on_region_clicked(self, region):
        if not self.settings.get("click_reactions", True):
            return
        cfg = self.reactions.get(region)
        if not cfg:
            return
        variants = cfg.get("variants")
        if variants:                                             # several reactions per area: random, never the same twice in a row
            last = self._last_variant.get(region, -1)
            pool = [i for i in range(len(variants)) if i != last] or [0]
            pick = random.choice(pool)
            self._last_variant[region] = pick
            cfg = {**{k: v for k, v in cfg.items() if k != "variants"}, **variants[pick]}
        self.animator.touch()
        if cfg.get("gesture"):
            self.animator.gesture.emit(str(cfg["gesture"]))
        now = time.time()
        hist = [x for x in self._clicks.get(region, []) if now - x < 6] + [now]
        self._clicks[region] = hist
        if len(hist) >= 4 and cfg.get("annoyed"):
            cfg = {**cfg, **cfg["annoyed"]}
        rig = self.animator.rig
        for part, ch, val in cfg.get("kicks", []):
            rig.kick(part, ch, val)
        self.animator.set_expression(cfg.get("expression", "happy"), hold=2.5)
        files = [f for f in (SOUNDS_DIR / region).glob("*") if f.suffix.lower() in (".wav", ".mp3", ".ogg")] \
            if (SOUNDS_DIR / region).exists() else []
        if files:
            self.speaker.play_file(random.choice(files))
            return
        lang = self.settings.get("ui_lang", "fa")
        lines = cfg.get(lang) or cfg.get("fa") or []
        if lines and self.voice_btn.isChecked():
            self.speaker.speak(random.choice(lines), cfg.get("rate"), cfg.get("pitch"), cache=True)

    # ---------- voice, microphone, wake mode ----------
    def set_voice_enabled(self, on):
        self.settings["speak_replies"] = bool(on)
        for w in (self.voice_btn, self.voice_page.speak_chk):
            w.blockSignals(True)
            w.setChecked(bool(on))
            w.blockSignals(False)
        save_settings(self.settings)
        if not on:
            self.safe_stop_speaker()

    def on_stop_clicked(self):
        if self.speaker._began:
            self.director.event("user_interrupt")
        self.safe_stop_speaker()

    def on_speech_started(self):
        self.director.event("tts_started")           # real audio playback has begun
        if self.listener:
            self.listener.begin_kira_speech()        # keeps listening for an interruption (or mutes when barge-in is off)
        self.set_status("st_speaking")

    def on_speech_finished(self):
        self.director.event("tts_stopped")           # playback ended or was stopped
        if self.listener:
            self.listener.end_kira_speech()
        QTimer.singleShot(500, self.unmute)
        if self.listener:
            self.on_listener_state("listening")
        else:
            self.set_status("st_ready")

    def _on_kira_level(self, level):
        if self.listener:
            self.listener.kira_level = float(level)

    def on_user_barge_in(self):
        """The person started talking over Kira: she stops at once, and what they say is still heard as the next message."""
        if self.speaker._began:
            self.director.event("user_interrupt")
        self.safe_stop_speaker()

    def unmute(self):
        if self.listener and not self.speaker._began:
            self.listener.muted = False

    def toggle_mic(self):
        if self.mic_btn.isChecked():
            self.start_listener()
        else:
            if self.wake_btn.isChecked():
                self.wake_btn.setChecked(False)
                self.toggle_wake()
            self.stop_listener()

    def start_listener(self):
        # A stopped QThread cannot be restarted. Wait for its finished signal before
        # creating the replacement, otherwise rapid mic toggles can open two streams.
        if self.listener is not None:
            self.stop_listener()
        previous = getattr(self, "_stopping_listener", None)
        if previous is not None and previous.isRunning():
            self._restart_listener_after_stop = True
            self.set_status("st_loading")
            return
        self._restart_listener_after_stop = False
        self.listener = Listener(self.settings["whisper_model"], self.settings["stt_language"], self,
                                 sensitivity=self.settings.get("mic_sensitivity", 100), barge_in=self.settings.get("barge_in", True),
                                 settings=self.settings)
        listener = self.listener
        listener.heard.connect(self.on_heard)
        listener.interrupted.connect(self.on_user_barge_in)
        listener.state.connect(self.on_listener_state)
        listener.error.connect(self.on_listener_error)
        listener.note.connect(self.on_voice_note)
        listener.finished.connect(lambda current=listener: self._listener_finished(current))
        listener.start()

    def stop_listener(self):
        self._restart_listener_after_stop = False
        if self.listener:
            listener, self.listener = self.listener, None
            listener.stop()
            if listener.isRunning():
                self._stopping_listener = listener
        self.set_status("st_ready")
        self.update_engine_label()

    def _listener_finished(self, listener):
        was_current = self.listener is listener
        if was_current:
            self.listener = None
            self.mic_btn.setChecked(False)
        if getattr(self, "_stopping_listener", None) is listener:
            self._stopping_listener = None
        self.update_engine_label()
        if not self._closing:
            if getattr(self, "_restart_listener_after_stop", False) and self.mic_btn.isChecked():
                self._restart_listener_after_stop = False
                QTimer.singleShot(0, self.start_listener)
            elif was_current:
                self.set_status("st_ready")

    def on_listener_error(self, msg):
        self.add_chat("error", msg)
        self.mic_btn.setChecked(False)
        if self.wake_btn.isChecked():
            self.wake_btn.setChecked(False)
            self.animator.set_sleeping(False)
            self.wake_timer.stop()
        # Keep the worker owned until its stream has closed; stop() is non-blocking.
        self.stop_listener()

    def on_listener_state(self, state):
        if state == "listening":
            self.update_engine_label()
            self.set_status("st_sleeping" if (self.wake_btn.isChecked() and not self.awake) else "st_listening")
        else:
            self.set_status({"loading": "st_loading", "hearing": "st_hearing", "transcribing": "st_transcribing"}.get(state, "st_ready"))

    def update_engine_label(self):
        eng = getattr(self.listener, "engine", None) if self.listener else None
        via = getattr(self.listener, "via", "") if self.listener else ""
        if via == "local:qwen3-asr":
            label = "Qwen3-ASR · Local"
        elif via == "local:whisper" or eng == "whisper":
            label = "Whisper · Local"
        elif self.listener is not None and self.listener.isRunning():
            label = "STT محلی"
        else:
            label = "—"
        self.voice_page.engine_lbl.setText(label)

    def toggle_wake(self):
        if self.wake_btn.isChecked():
            if not self.mic_btn.isChecked():
                self.mic_btn.setChecked(True)
                self.start_listener()
            self.go_sleep()
        else:
            self.wake_timer.stop()
            self.awake = False
            self.animator.set_sleeping(False)

    def go_sleep(self):
        self.wake_timer.stop()
        self.awake = False
        if self.wake_btn.isChecked():
            self.animator.set_sleeping(True)
            self.on_listener_state("listening")

    def wake_up(self):
        self.awake = True
        self.animator.set_sleeping(False)
        self.animator.set_expression("happy", hold=2)
        self.wake_timer.start(int(self.settings["wake_timeout"]) * 1000)

    def on_heard(self, text):
        self.animator.touch()
        # Keep processing voice input while a reply is generating: submit() owns
        # the same bounded queue as typed messages and handles running-task controls.
        if self.wake_btn.isChecked():
            if not self.awake:
                mt = WAKE_RE.search(text)
                if not mt:
                    return
                self.wake_up()
                rest = text[mt.end():].strip(" ،,.!؟?؛")
                if len(rest) < 2:
                    self.reply_local(self.t("yes"))
                    return
                text = rest
            else:
                if SLEEP_RE.search(text):
                    self.add_chat("user", text)
                    self.go_sleep()
                    self.say(self.t("night"))
                    return
                self.wake_timer.start(int(self.settings["wake_timeout"]) * 1000)
        if STOP_RE.match(text.strip()):
            self.safe_stop_speaker()                  # "بس کن / ساکت" only silences Kira; it is not sent to the model
            return
        self._voice_next = True
        self.submit(text)

    # ---------- companion window ----------
    def toggle_companion(self):
        if self.companion.isVisible():
            self.companion.hide()
        else:
            self.companion.show()
            self.companion.raise_()

    def on_companion_visibility(self, _):
        self.update_companion_btn()

    def update_companion_btn(self):
        shown = self.companion.isVisible()
        self.companion_btn.setToolTip(self.t("hide_char" if shown else "show_char"))
        self.companion_btn.setChecked(shown)

    def _running_background_workers(self):
        """Return every owned QThread that must finish before Qt destroys the window."""
        workers = []
        for session in getattr(self, "sessions", {}).values():
            workers.extend((getattr(session, "worker", None), getattr(session, "_search_worker", None)))
        for name in (
            "_local_voice_worker", "_api_worker", "_route_worker", "_bench_worker",
            "_scan_worker", "_provider_test_worker", "_ollama_worker", "_vision_worker",
            "_web_test_worker", "_attach_worker", "_model_import_worker", "_stopping_listener",
            "_stopping_game_audio_listener", "game_audio_listener", "listener",
        ):
            workers.append(getattr(self, name, None))
        unique = []
        seen = set()
        for worker in workers:
            if worker is None or id(worker) in seen:
                continue
            seen.add(id(worker))
            try:
                if worker.isRunning():
                    unique.append(worker)
            except RuntimeError:
                continue
        return unique

    def _resume_close_after_workers(self):
        if getattr(self, "_closing", False):
            QTimer.singleShot(0, self.close)

    def _clear_chat_coordinator_queues(self):
        """Drop scheduled/pending messages; the service releases its injected registry."""
        self.chat_application_service.dispose()

    def closeEvent(self, event):
        if (getattr(self, "tray", None) is not None and self.settings.get("close_to_tray")
                and not getattr(self, "_quitting", False)):
            event.ignore()                                           # X only hides; "Exit" in the tray menu really quits
            self.hide_to_tray()
            return
        if getattr(self, "_closing", False):
            if self._running_background_workers():
                event.ignore()
                return
            for session in self.session_manager.list_sessions():
                session.busy = False
            if not self.session_manager.dispose():
                event.ignore()
                QTimer.singleShot(100, self.close)
                return
            unsubscribe = getattr(self, "_session_event_unsubscribe", None)
            if callable(unsubscribe):
                unsubscribe()
                self._session_event_unsubscribe = None
            event.accept()
            QTimer.singleShot(0, QApplication.quit)
            return
        local_worker = getattr(self, "_local_voice_worker", None)
        if local_worker is not None and local_worker.isRunning():
            if not getattr(self, "_close_after_local_voice", False):
                self._close_after_local_voice = True
                self.add_chat("system", "بارگذاری یا آزمایش موتور صوتی هنوز در حال اجراست؛ Kira پس از پایان امن آن بسته می‌شود.")
            event.ignore()
            return
        # ChatApplicationService owns cancellation and persists partial output once.
        self._closing = True
        self._clear_chat_coordinator_queues()
        if getattr(self, "code_chat", None) is not None:
            self.code_chat.shutdown()
        if getattr(self, "tray", None) is not None:
            self.tray.hide()
        self.bubble.close()
        self.tool_agent.request_cancel()
        # Stop attachment reads as soon as shutdown starts; a large file must not
        # keep the window alive for the full read when the user already cancelled.
        self.cancel_attachments()
        for sess in self.sessions.values():
            if sess.client is not None:
                sess.client.cancel()
            if sess.timer is not None:
                sess.timer.stop()
        self._game_poll_timer.stop()
        self._set_game_vision_capture(False)
        self._stop_game_audio_listener()
        self.game_mode.set_enabled(False)
        for sess in self.sessions.values():
            for w in (sess.worker, sess._search_worker):
                if w is not None and w.isRunning():
                    w.wait(3000)
        for name in ("_api_worker", "_route_worker", "_bench_worker", "_scan_worker", "_provider_test_worker",
                     "_ollama_worker", "_vision_worker", "_web_test_worker", "_attach_worker"):
            w = getattr(self, name, None)
            if w is not None and w.isRunning():
                w.wait(5000)
        self.stop_listener()
        self.safe_stop_speaker()
        self.companion.close()
        running = self._running_background_workers()
        if running:
            self.add_chat(
                "system",
                "چند کار پس‌زمینه هنوز در حال پایان‌اند؛ پنجره بعد از پایان امن آن‌ها بسته می‌شود."
            )
            for worker in running:
                try:
                    worker.finished.connect(self._resume_close_after_workers)
                except RuntimeError:
                    pass
            event.ignore()
            # Cover the race where a worker finishes while its finished slot is connected.
            if not self._running_background_workers():
                QTimer.singleShot(0, self.close)
            return
        for session in self.session_manager.list_sessions():
            session.busy = False
        if not self.session_manager.dispose():
            event.ignore()
            QTimer.singleShot(100, self.close)
            return
        event.accept()
        QTimer.singleShot(0, QApplication.quit)                     # the tray keeps 'last window closed' from quitting by itself
    def reload_chat_view(self):
        for sess in self.sessions.values():             # every character's conversation is shown again from the database
            if sess.view is None:
                continue
            with self._as(sess):
                self.chat.clear()
                self.restore_history(200)

    def clear_chat(self):
        who = self.character_service.display_name(self.settings)
        question = (f"تاریخچه‌ی گفتگوی «{who}» پاک شود؟ (گفتگوی بقیه‌ی کاراکترها دست‌نخورده می‌ماند)"
                    if self.settings.get("ui_lang", "fa") == "fa" else f"Delete the saved history of {who}? (the other characters' chats stay)")
        if QMessageBox.question(self, self.t("clear_t"), question) == QMessageBox.Yes:
            try:
                self.chat_application_service.clear_history(self.cur.cid)      # only THIS character's conversation; saves a snapshot first, nothing is deleted if that fails
                # Facts, moments and habits remain in the character's own memory file.
                self.memory_service.forget_conversation(self.cur.cid)
                self.tool_agent.clear_tasks(self.cur.cid)   # the unfinished task (its goal is the user's own words) goes with the chat
                brain.reset_state()
            except ChatHistoryError as exc:
                QMessageBox.warning(self, self.t("clear_t"), str(exc))
                return
            self.chat.clear()
            self.add_chat("system", self.t("mem_cleared") + " (اگر اشتباه بود: تنظیمات ← عمومی ← «بازگرداندن آخرین پاک‌سازی».)")

    def apply_mood_to_avatar(self):
        """A quick avatar reaction that matches how he seems right now (sad -> soft, joke -> laughing ...). Never raises."""
        try:
            hint = mood.avatar_hint()
            eid = self.director.library.resolve_name(hint[0]) if hint else None
            if eid:
                self.director.engine.request([eid], hint[1], 3.0, "event", self.director.clock(), tag="mood")
        except Exception:                                         # noqa: BLE001
            pass

    def open_memory_dialog(self):
        character_id = self.character_service.active_id(self.settings)
        profile = self.character_service.all_profiles(self.settings).get(character_id, {})
        character_name = profile.get("name") or character_id.title()
        MemoryDialog(
            self,
            character_id,
            character_name=character_name,
            memory_service=self.memory_service,
            mood_service=self.mood_service,
        ).exec()

    def restore_cleared_chat(self):
        try:
            n = self.chat_application_service.restore_history()
        except ChatHistoryError as exc:
            QMessageBox.information(self, "بازگرداندن گفتگو", str(exc))
            return
        self.reload_chat_view()
        self.add_chat("system", f"{n} پیام بازگردانده شد." if n else "همه‌ی پیام‌های آن پاک‌سازی از قبل در گفتگو بودند.")

    def import_old_chat(self, path=None):
        """Merge chats from an older Kira database (nothing is overwritten; duplicates are skipped)."""
        if path is None:
            start = ""
            for folder in storage.legacy_candidates(ROOT):
                start = str(Path(folder))
                break
            path, _ = QFileDialog.getOpenFileName(self, "انتخاب فایل گفتگوی قدیمی (kira_memory.sqlite3)", start or str(ROOT),
                                                  "SQLite (*.sqlite3 *.db);;All files (*)")
            if not path:
                return
        try:
            n = self.chat_application_service.import_history(path)
        except ChatHistoryError as exc:
            QMessageBox.warning(self, "ورود گفتگو", str(exc))
            return
        self.reload_chat_view()
        self.add_chat("system", f"{n} پیام از فایل قدیمی وارد شد." if n else "پیام جدیدی در آن فایل نبود (همه از قبل وجود داشتند).")

    @staticmethod
    def html(s):
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br>")

