"""Shared Qt and capability imports used by the composed desktop window.

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
from PySide6.QtCore import Qt, Slot, Signal, QObject, QTimer, QRectF, QUrl, QSize
from PySide6.QtGui import QAction, QIcon, QDesktopServices, QTextCursor, QColor, QBrush, QImage, QTextDocument, QPixmap
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit, QTextBrowser, QLineEdit,
    QPushButton, QMessageBox, QComboBox, QFormLayout, QSpinBox, QTabWidget, QGroupBox, QCheckBox,
    QSlider, QScrollArea, QToolButton, QMenu, QListWidget, QListWidgetItem, QAbstractItemView, QDialog,
    QDialogButtonBox, QFrame, QFileDialog, QSizePolicy, QSystemTrayIcon, QTableWidget, QTableWidgetItem, QHeaderView, QInputDialog,
    QStackedWidget, QDoubleSpinBox, QGridLayout, QButtonGroup, QGraphicsDropShadowEffect, QColorDialog, QProgressBar
)
from ..config import (load_settings, save_settings, ROOT, VERSION, LOAD_WARNINGS, DATA_DIR,
                     APP_NAME, PROJECT_URL, RELEASES_URL)
from .. import about
from .. import storage
from ..core.exceptions import ChatHistoryError
from ..ollama_client import OllamaClient, model_installed, parse_keep_alive, clamp_num_ctx, clamp_num_predict, DEFAULT_NUM_PREDICT, DEFAULT_NUM_CTX, DEFAULT_KEEP_ALIVE
from ..hybrid_ai import HybridRouter, probe_provider
from .. import routes as route_model
from .. import discovery
from .. import api_manager
from .. import websearch
from ..chat import attachments as att
from ..actions import match_safe_action, run_safe_action
from ..tools import ToolAgent
from ..leak_guard import scrub_lines
from ..companion import CompanionWindow, CompanionBubble
from ..chat_render import sources_html, message_html, detect_direction, bubble_accent
from ..face import AvatarView
from ..vrm_avatar import KiraAvatar
from ..emotion.backend_png import EmotionFaceAnimator
from ..emotion.director import EmotionDirector
from ..voice import Speaker
from ..listener import Listener
from ..game_audio import GameAudioListener, is_important_game_audio
from .. import modes
from ..speech_fixes import SpeechFixes
from ..strings import STR
from ..personality import build_system_prompt
from .. import evidence_memory
from .. import brain
from .. import usage
from .. import mood
from ..characters.kira import PROFILE as KIRA_PROFILE
from ..character.traits import BASE_TRAITS
from .. import avatar_art
from .. import body as body_ctl
from ..rig import MOODS
from ..ui_icons import make_icon, set_glow_intensity
from ..ui_widgets import ChatInput, RouteChip, AttachmentTile
from ..theme import build_style, STYLE
from .. import theme as theme_mod
from ..chat_sessions import ChatSession, NOOP, SESSION_FIELDS, session_property, front_only_property
from ..chat.application_service import ChatApplicationService, ApplicationEventKind, RequestStatus
from ..chat.session_manager import SessionManager
from ..chat.commands import PermissionDecision
from ..chat.command_adapters import create_default_command_registry
from ..tools.tasks import parse_control as parse_tool_task_control
from .. import winfx
from ..game_mode import GameModeMonitor, CAPTURE_JPEG_QUALITY
from ..vision_pipeline import FrameGate, policy_for
from ..chat_code_ui import CodeChat
from .components import ApiAddPanel, ChatHeader, McpRegistryPanel, ModelCombo, OllamaProviderPanel, RouteEditor, ChatComposer
from .controllers import ChatAttachmentController
from .dialogs import MemoryDialog, ModelPickerDialog
from .pages import AssistantPage, AppearancePage, CharactersPage, HelpPage, PreferencesPage, VoicePage
from .workers import (
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


def front_only(fn):
    """Method that only touches the shared screen (status line, route chip, upload cards): skipped while a background chat runs it."""
    def wrapper(self, *args, **kwargs):
        if self.cur is not self.front:
            return None
        return fn(self, *args, **kwargs)
    wrapper.__name__ = fn.__name__
    wrapper.__doc__ = fn.__doc__
    return wrapper


class SessionRelay(QObject):
    """Marshals this session's worker/provider callbacks onto the GUI thread."""

    provider_event = Signal(object)

    def __init__(self, window, session):
        super().__init__(window)
        self.w, self.s = window, session
        self.provider_event.connect(self._handle_provider_event)

    @Slot(object)
    def _handle_provider_event(self, event):
        self.w.chat_application_service.handle_provider_event(event)

    def _run(self, name, *args):
        with self.w._as(self.s):
            getattr(self.w, name)(*args)

    @Slot(str)
    def chunk(self, piece):
        self._run("on_stream_chunk", piece)

    @Slot(dict)
    def stream_event(self, e):          # NOT named `event`: that would override QObject.event(QEvent)
        self._run("on_stream_event", e)

    @Slot(dict)
    def tool(self, e):
        self._run("on_tool_event", e)

    @Slot(dict)
    def done(self, res):
        self._run("on_stream_done", res)

    @Slot(str)
    def failed(self, error):
        self._run("on_error", error)

    @Slot()
    def tick(self):
        self._run("_stream_flush")

    @Slot(int, bool, object)
    def search_done(self, token, ok, result):
        self._run("on_web_done", token, ok, result)

    @Slot(bool, str, int)
    def game_vision_done(self, ok, result, latency_ms):
        self._run("_on_game_vision_result", ok, result, latency_ms)

    @Slot()
    def game_vision_finished(self):
        self._run("_send_next_pending")


