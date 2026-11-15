import contextlib
import base64
import json
import random
import time
import threading
from pathlib import Path
import re
import sys
from PySide6.QtCore import Qt, QThread, Signal, Slot, QObject, QTimer, QRectF, QUrl, QSize
from PySide6.QtGui import QAction, QIcon, QDesktopServices, QTextCursor, QColor, QBrush, QImage, QTextDocument, QPixmap
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit, QTextBrowser, QLineEdit,
    QPushButton, QMessageBox, QComboBox, QFormLayout, QSpinBox, QTabWidget, QGroupBox, QCheckBox,
    QSlider, QScrollArea, QToolButton, QMenu, QListWidget, QListWidgetItem, QAbstractItemView, QDialog,
    QDialogButtonBox, QFrame, QFileDialog, QSizePolicy, QSystemTrayIcon, QTableWidget, QTableWidgetItem, QHeaderView, QInputDialog,
    QStackedWidget, QDoubleSpinBox, QButtonGroup, QGraphicsDropShadowEffect
)
from .config import (load_settings, save_settings, ROOT, VERSION, LOAD_WARNINGS, DATA_DIR,
                     APP_NAME, PROJECT_URL, RELEASES_URL)
from . import about
from . import storage
from . import memory as chat_store
from .memory import init_db, add_message, conversation_context, clear_memory, recent_messages, message_count, ChatStoreError
from .ollama_client import OllamaClient, model_installed, parse_keep_alive, clamp_num_ctx, clamp_num_predict, DEFAULT_NUM_PREDICT, DEFAULT_NUM_CTX, DEFAULT_KEEP_ALIVE
from .hybrid_ai import HybridRouter, probe_provider
from . import routes as route_model
from . import discovery
from . import api_manager
from . import websearch
from . import attachments as att
from .actions import run_safe_action
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
from . import cloud_voice
from . import voice_caps
from . import modes
from .cloud_voice_ui import CloudVoicePage
from .speech_fixes import SpeechFixes
from .strings import STR, TEST_LINES
from .personality import build_system_prompt
from . import persona_memory
from . import evidence_memory
from . import brain
from . import usage
from . import mood
from . import characters
from .characters.kira import PROFILE as KIRA_PROFILE
from .character.traits import BASE_TRAITS
from . import avatar_art
from . import body as body_ctl
from .rig import MOODS
from .ui_icons import make_icon
from .ui_widgets import ChatInput, RouteChip, AttachmentTile
from .theme import build_style, STYLE
from . import theme as theme_mod
from .chat_sessions import ChatSession, NOOP, SESSION_FIELDS, session_property, front_only_property
from . import winfx
from .game_mode import GameModeMonitor, CAPTURE_JPEG_QUALITY
from .vision_pipeline import FrameGate, policy_for
from .game_mode_policy import (STORY_MODE, COMPETITIVE_SAFE_MODE, game_mode_permissions, normalize_game_mode_profile)
from .chat_code_ui import CodeChat

WAKE_RE = re.compile(r"(?:(?:هی|سلام|hey|hi)[\s\u200c]*)?(?:کی[\s\u200c]?را|کایرا|کیرآ|کیارا|kira|keira|kyra|kiera)", re.I)
STOP_RE = re.compile(r"^\W*(?:بس\s*کن|بسه|ساکت(?:\s*شو)?|صبر\s*کن|وایسا|وایستا|stop|be\s*quiet)\W*$", re.I)       # "just be quiet" is not a chat message
SLEEP_RE = re.compile(r"بخواب|خداحافظ|شب بخیر|good\s*night", re.I)
SOUNDS_DIR = ROOT / "assets" / "sounds"
EDGE_FA = ["fa-IR-DilaraNeural", "fa-IR-FaridNeural"]
EDGE_EN = ["en-US-AriaNeural", "en-US-JennyNeural", "en-US-GuyNeural", "en-GB-SoniaNeural", "en-GB-RyanNeural"]
EDGE_JA = ["ja-JP-NanamiNeural", "ja-JP-KeitaNeural"]


def load_reactions():
    try:
        return json.loads((ROOT / "reactions.json").read_text(encoding="utf-8"))
    except Exception:
        return {}


class ModelPickerDialog(QDialog):
    """Pick discovered models (or type one by hand) to add as Routes. Click anywhere on a row to tick it.
    Models the provider marks (or is known) as paid can be hidden with the free-only switch."""
    def __init__(self, parent, title, models, existing, error=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(560)
        self.existing = set(existing)
        self._free = {m["id"]: m.get("free") for m in models}
        lay = QVBoxLayout(self)
        note = QLabel("بودن یک مدل در فهرست به معنی تضمین دسترسی یا داشتن سهمیه نیست؛ فقط هنگام استفاده‌ی واقعی معلوم می‌شود. "
                      "روی هر ردیف کلیک کن تا انتخاب شود. 🆓 = رایگان، 💲 = پولی (برای Gemini تشخیص تقریبی است).")
        note.setObjectName("hint")
        note.setWordWrap(True)
        lay.addWidget(note)
        self.error_lbl = QLabel(("✕ " + error) if error else "")
        self.error_lbl.setWordWrap(True)
        self.error_lbl.setVisible(bool(error))
        lay.addWidget(self.error_lbl)
        self.free_only = QCheckBox("فقط مدل‌های رایگان (و نامشخص) را نشان بده")
        has_paid = any(m.get("free") is False for m in models)
        self.free_only.setChecked(has_paid)
        self.free_only.setVisible(has_paid)
        self.free_only.toggled.connect(lambda *_: self.apply_filter())
        lay.addWidget(self.free_only)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("جست‌وجو در نام یا Model ID…")
        self.filter.textChanged.connect(lambda *_: self.apply_filter())
        lay.addWidget(self.filter)
        self.list = QListWidget()
        self.list.setMinimumHeight(260)
        self.list.setLayoutDirection(Qt.LeftToRight)
        self.list.itemClicked.connect(self.toggle_item)
        lay.addWidget(self.list)
        for m in models:
            self.add_item(m["id"], m.get("name", ""), m.get("info", ""), free=m.get("free"))
        bulk = QHBoxLayout()
        all_btn = QPushButton("انتخاب همه‌ی نمایان")
        none_btn = QPushButton("برداشتن همه")
        all_btn.clicked.connect(lambda: self.set_visible_checked(True))
        none_btn.clicked.connect(lambda: self.set_visible_checked(False))
        bulk.addWidget(all_btn)
        bulk.addWidget(none_btn)
        bulk.addStretch(1)
        lay.addLayout(bulk)
        manual = QHBoxLayout()
        self.manual = QLineEdit()
        self.manual.setPlaceholderText("افزودن دستی: Model ID را بنویس")
        self.manual.setLayoutDirection(Qt.LeftToRight)
        add = QPushButton("افزودن دستی به فهرست")
        add.clicked.connect(self.add_manual)
        self.manual.returnPressed.connect(self.add_manual)
        manual.addWidget(self.manual, 1)
        manual.addWidget(add)
        lay.addLayout(manual)
        self.count_lbl = QLabel()
        lay.addWidget(self.count_lbl)
        box = QDialogButtonBox()
        self.ok_btn = box.addButton("افزودن به Route Manager", QDialogButtonBox.AcceptRole)
        box.addButton("انصراف", QDialogButtonBox.RejectRole)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        lay.addWidget(box)
        self.apply_filter()

    def add_item(self, mid, name="", info="", checked=False, free=None):
        mark = {True: "🆓 ", False: "💲 "}.get(free, "")
        item = QListWidgetItem(mark + (f"{name}  —  {mid}" if name else mid) + ("   (از قبل موجود)" if mid in self.existing else ""))
        item.setData(Qt.UserRole, mid)
        item.setToolTip(info or mid)
        self._free.setdefault(mid, free)
        if mid in self.existing:
            item.setFlags(Qt.ItemIsEnabled)
            item.setForeground(QBrush(QColor("#8d93ab")))
        else:
            item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            item.setCheckState(Qt.Checked if checked else Qt.Unchecked)
        self.list.addItem(item)
        return item

    def _selectable(self, item):
        return item.data(Qt.UserRole) not in self.existing

    def toggle_item(self, item):
        if self._selectable(item):
            item.setCheckState(Qt.Unchecked if item.checkState() == Qt.Checked else Qt.Checked)
            self.update_count()

    def set_visible_checked(self, on):
        for i in range(self.list.count()):
            item = self.list.item(i)
            if self._selectable(item) and not item.isHidden():
                item.setCheckState(Qt.Checked if on else Qt.Unchecked)
        self.update_count()

    def add_manual(self):
        mid = self.manual.text().strip()
        if mid.startswith("models/"):
            mid = mid[7:]
        if not mid:
            return
        for i in range(self.list.count()):
            item = self.list.item(i)
            if item.data(Qt.UserRole) == mid:
                if self._selectable(item):
                    item.setCheckState(Qt.Checked)
                    item.setHidden(False)
                self.manual.clear()
                self.update_count()
                return
        self.add_item(mid, "", "افزوده‌ی دستی", checked=True)
        self.manual.clear()
        self.apply_filter()

    def apply_filter(self, *_):
        text = self.filter.text().strip().lower()
        hide_paid = self.free_only.isChecked()
        for i in range(self.list.count()):
            item = self.list.item(i)
            mid = str(item.data(Qt.UserRole))
            miss = bool(text) and text not in item.text().lower() and text not in mid.lower()
            paid = hide_paid and self._free.get(mid) is False and item.checkState() != Qt.Checked
            item.setHidden(miss or paid)
        self.update_count()

    def selected_ids(self):
        return [self.list.item(i).data(Qt.UserRole) for i in range(self.list.count())
                if self._selectable(self.list.item(i)) and self.list.item(i).checkState() == Qt.Checked]

    def update_count(self):
        shown = sum(1 for i in range(self.list.count()) if not self.list.item(i).isHidden())
        self.count_lbl.setText(f"{shown} مدل نمایان از {self.list.count()} · {len(self.selected_ids())} انتخاب‌شده")


class StreamWorker(QThread):
    """Runs one streamed request off the GUI thread. Everything the router reports becomes a Qt signal."""
    event = Signal(dict)            # phase changes with the REAL route (connecting / waiting / streaming / failover)
    chunk = Signal(str)
    finished_ok = Signal(dict)
    failed = Signal(str)
    tool_event = Signal(dict)       # a tool starts / ends (status line only)

    def __init__(self, router, messages, prompt, temperature, retry_index=0, agent=None, plan=None, role="", route_id=""):
        super().__init__()
        self.role, self.route_id = role, route_id                 # brain stage (kira/brain.py); "" = normal routing
        self.router, self.messages, self.prompt, self.temperature, self.retry_index = router, messages, prompt, temperature, retry_index
        self.agent, self.plan = agent, plan                       # tool loop (kira/tools); plan None = an ordinary chat turn

    def run(self):
        try:
            has_images = any(bool(item.get("images")) for item in (self.messages or []) if isinstance(item, dict))
            vision_context = contextlib.nullcontext()
            if has_images:
                vision_route = self.router.vision_route_id()
                if not vision_route:
                    raise RuntimeError("برای تحلیل این تصویر هیچ مدل Vision فعالی در Route Manager پیدا نشد. یک مدل بینایی انتخاب کن.")
                vision_context = self.router.vision_scope(vision_route)
            scope = getattr(self.router, "role_scope", None)
            with vision_context:
                with (scope(self.role, self.route_id) if scope else contextlib.nullcontext()):
                    result = self._run_request()
            self.finished_ok.emit(result)
        except Exception as e:                                    # noqa: BLE001 - shown to the user, never crashes the UI
            self.failed.emit(str(e))

    def _run_request(self):
        if True:
            if self.agent is not None and self.plan is not None:
                result = self.agent.run(self.router, self.messages, self.prompt, self.temperature, self.plan, retry_index=self.retry_index,
                                        on_chunk=self.chunk.emit, on_event=self.event.emit, on_tool=self.tool_event.emit)
            else:
                result = self.router.chat_stream(self.messages, self.prompt, self.temperature, on_chunk=self.chunk.emit,
                                                 on_event=self.event.emit, retry_index=self.retry_index)
            return result


class AttachWorker(QThread):
    """Reads attachments off the GUI thread; each queued file can be cancelled independently."""
    progress = Signal(int, int)
    loaded = Signal(int, dict)
    failed = Signal(int, str)

    def __init__(self, paths):
        super().__init__()
        self.paths = list(paths)
        self._cancelled = [threading.Event() for _ in self.paths]

    def cancel(self, index):
        if 0 <= int(index) < len(self._cancelled):
            self._cancelled[int(index)].set()

    def run(self):
        for i, path in enumerate(self.paths):
            cancelled = self._cancelled[i]
            if cancelled.is_set():
                continue
            self.progress.emit(i, 0)
            try:
                attachment = att.load_attachment(
                    path, lambda pct, i=i: self.progress.emit(i, pct), cancelled=cancelled.is_set
                )
                if not cancelled.is_set():
                    self.loaded.emit(i, attachment)
            except (att.AttachmentError, OSError) as exc:
                if not cancelled.is_set():
                    self.failed.emit(i, str(exc))


class SearchWorker(QThread):
    """Web search (Tavily, then the fallbacks) off the GUI thread. done(token, ok, result-or-message)."""
    done = Signal(int, bool, object)

    def __init__(self, token, query, api_key, depth, rewrite=None, user_text=None, gemini=None, fallback=True,
                 images=None, describe=None):
        super().__init__()
        self.token, self.query, self.api_key, self.depth, self.rewrite = token, query, api_key, depth, rewrite
        self.gemini, self.fallback = gemini, fallback
        self.images, self.describe = images, describe          # picture search: the pictures + a callback that turns them into a query
        self.user_text = user_text or query

    def run(self):
        try:
            if self.images:                                           # search WITH a picture (Gemini sees it; the others get a text query)
                self.done.emit(self.token, True, websearch.image_research(self.images, self.user_text, self.api_key, self.depth,
                                                                         gemini=self.gemini, fallback=self.fallback, describe=self.describe))
                return
            query, evidence_text = self.query, self.user_text
            if self.rewrite:                                          # only for follow-ups ("نه بابا بهتر سرچ کن"): the chat gives the meaning
                try:
                    query = self.rewrite() or query
                    evidence_text = query
                except Exception:                                     # noqa: BLE001 - fall back to the plain query
                    query = self.query
            self.done.emit(self.token, True, websearch.research(query, self.api_key, self.depth, evidence_text,
                                                                          gemini=self.gemini, fallback=self.fallback))
        except websearch.SearchError as exc:
            self.done.emit(self.token, False, str(exc))
        except Exception as exc:                                      # noqa: BLE001 - search must never crash the chat
            self.done.emit(self.token, False, f"خطای جست‌وجو: {type(exc).__name__}")


class TaskWorker(QThread):
    """One blocking call (route test, Ollama scan) off the GUI thread. done -> (ok, value-or-error-text)."""
    done = Signal(object)

    def __init__(self, fn):
        super().__init__()
        self.fn = fn

    def run(self):
        try:
            self.done.emit((True, self.fn()))
        except Exception as exc:                                  # noqa: BLE001
            self.done.emit((False, str(exc)[:400]))


class BenchWorker(QThread):
    progress = Signal(dict)
    done = Signal(object)

    def __init__(self, router, route_ids):
        super().__init__()
        self.router, self.route_ids = router, list(route_ids)

    def run(self):
        try:
            rows = self.router.benchmark(self.route_ids, on_progress=self.progress.emit)
            self.done.emit((True, rows))
        except Exception as exc:                                  # noqa: BLE001
            self.done.emit((False, str(exc)[:400]))


class MemoryDialog(QDialog):
    """View, edit and delete the active character's isolated long-term memory."""
    GROUPS = {"fact": "درباره‌ی تو", "moment": "لحظه / رویداد", "summary": "خلاصه‌ی گفتگوهای قدیمی"}

    def __init__(self, parent=None, character_id="kira"):
        super().__init__(parent)
        self.character_id = str(character_id or "kira")
        profiles = characters.all_profiles(getattr(parent, "settings", {}))
        self.character_name = str(profiles.get(self.character_id, {}).get("name") or self.character_id.title())
        self.setWindowTitle(f"حافظه‌ی {self.character_name}")
        self.resize(680, 480)
        lay = QVBoxLayout(self)
        self.info = QLabel()
        self.info.setWordWrap(True)
        lay.addWidget(self.info)
        self.items = QListWidget()
        self.items.setSelectionMode(QAbstractItemView.SingleSelection)
        lay.addWidget(self.items, 1)
        row = QHBoxLayout()
        for text, fn in (("افزودن یادداشت", self.add_note), ("ویرایش", self.edit_item), ("حذف", self.delete_item), ("فراموش‌کردن همه", self.forget_all)):
            btn = QPushButton(text)
            btn.clicked.connect(lambda checked=False, f=fn: f())
            row.addWidget(btn)
        lay.addLayout(row)
        close = QPushButton("بستن")
        close.clicked.connect(self.accept)
        lay.addWidget(close)
        self.refresh()

    def refresh(self):
        cur = mood.current()
        self.info.setText(f"حال‌وهوای فعلی همراه: {cur['emotion']} ({cur['intensity']}/100). حافظه‌ی بلندمدت {self.character_name} جداست؛ هرچه اینجا نباشد در حافظه‌ی او ثبت نشده است. تاریخچه‌ی کوتاه‌مدت گفتگو همچنان مشترک است.")
        self.items.clear()
        with persona_memory.character_scope(self.character_id):
            saved_items = persona_memory.list_items()
        for it in saved_items:
            row = QListWidgetItem(f"[{self.GROUPS.get(it['group'], it['group'])}] {it['text']}")
            row.setData(Qt.UserRole, it["id"])
            self.items.addItem(row)

    def _selected(self):
        item = self.items.currentItem()
        return item.data(Qt.UserRole) if item else None

    def add_note(self):
        text, ok = QInputDialog.getText(self, "یادداشت جدید", f"چه چیزی را {self.character_name} یادش بماند؟")
        if ok:
            with persona_memory.character_scope(self.character_id):
                added = persona_memory.add_note(text)
            if added:
                self.refresh()

    def edit_item(self):
        iid = self._selected()
        if not iid:
            return
        with persona_memory.character_scope(self.character_id):
            current = next((i["text"] for i in persona_memory.list_items() if i["id"] == iid), "")
        text, ok = QInputDialog.getText(self, "ویرایش", "متن:", QLineEdit.Normal, current)
        if ok:
            with persona_memory.character_scope(self.character_id):
                updated = persona_memory.update_item(iid, text)
            if updated:
                self.refresh()

    def delete_item(self):
        iid = self._selected()
        if iid:
            with persona_memory.character_scope(self.character_id):
                deleted = persona_memory.delete_item(iid)
            if deleted:
                self.refresh()

    def forget_all(self):
        if QMessageBox.question(self, "فراموش‌کردن همه", f"همه‌ی چیزهایی که {self.character_name} در حافظه‌ی بلندمدتش درباره‌ی تو نگه داشته پاک شود؟ تاریخچه‌ی کوتاه‌مدت گفتگو و حافظه‌ی شخصیت‌های دیگر دست‌نخورده می‌ماند.") == QMessageBox.Yes:
            with persona_memory.character_scope(self.character_id):
                persona_memory.forget_all()
            if self.character_id == "kira":       # mood is still a shared state, not part of Ren/Mika's isolated memory
                mood.reset()
            self.refresh()


class ProviderTestWorker(QThread):
    done = Signal(str, bool, str)

    def __init__(self, name, config):
        super().__init__()
        self.name, self.config = name, dict(config)

    def run(self):
        # Key check, model check and one real chat request live in hybrid_ai.probe_provider (unit-tested with mocks).
        try:
            ok, detail = probe_provider(self.name, self.config)
        except Exception as exc:
            ok, detail = False, str(exc)[:500]
        self.done.emit(self.name, ok, detail)


class ModelCombo(QComboBox):
    """Editable list of installed Ollama models that still behaves like a QLineEdit (text()/setText())."""
    def __init__(self, text=""):
        super().__init__()
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.NoInsert)
        self.setEditText(text)

    def text(self):
        return self.currentText()

    def setText(self, value):
        self.setEditText(str(value))

    def set_models(self, names):
        keep = self.currentText()
        self.blockSignals(True)
        self.clear()
        self.addItems(list(names))
        self.setEditText(keep)
        self.blockSignals(False)



class VisionAnalysisWorker(QThread):
    """Bounded image analysis; uses only a route marked/recognized as Vision-capable."""
    done = Signal(bool, str, int)

    def __init__(self, router, image, context=""):
        super().__init__()
        self.router = router
        self.image = dict(image)
        self.context = str(context or "").strip()[:1200]
        self._cancelled = threading.Event()

    def cancel_request(self):
        self._cancelled.set()
        # HybridRouter closes the active HTTP response, which interrupts network waits.
        try:
            self.router.cancel()
        except Exception:
            pass

    def run(self):
        began = time.monotonic()
        try:
            if self._cancelled.is_set():
                return
            route_id = self.router.vision_route_id()
            if not route_id:
                raise RuntimeError("هیچ مدل Vision فعالی پیدا نشد. یک Route بینایی انتخاب کن یا برای Provider سفارشی vision_enabled را فعال کن.")
            from .vision_ocr import extract_local_text
            ocr_text = extract_local_text(self.image)
            prompt = (
                "این تصویر، فریم بازی کاربر است. فقط شواهد قابل مشاهده را گزارش کن و حدس نزن. "
                "اگر متن OCR در اختیار داری، آن را به‌عنوان سرنخ کمکی در نظر بگیر، نه حقیقت قطعی. "
                "اگر زمینه یا سؤال کاربر داده شده، دقیقاً به همان پاسخ بده؛ در غیر این صورت وضعیت، خطر، هدف و اقدام فوری را کوتاه بگو.\n"
                + (("زمینه/سؤال کاربر: " + self.context + "\n") if self.context else "")
                + (("متن استخراج‌شده‌ی محلی از تصویر: " + ocr_text[:1800]) if ocr_text else "")
            )
            with self.router.role_scope("vision", route_id):
                result = self.router.chat(
                    [{"role": "user", "content": self.context or "فریم فعلی بازی را بررسی کن.", "images": [self.image]}],
                    prompt, 0.2,
                )
            if not self._cancelled.is_set():
                self.done.emit(True, str(result or "").strip(), int((time.monotonic() - began) * 1000))
        except Exception as exc:
            if not self._cancelled.is_set():
                self.done.emit(False, str(exc)[:350], int((time.monotonic() - began) * 1000))


class OllamaTaskWorker(QThread):
    """Runs one blocking Ollama call off the GUI thread. fn() returns (ok, text) or raises."""
    done = Signal(bool, str)

    def __init__(self, fn):
        super().__init__()
        self.fn = fn

    def run(self):
        try:
            ok, text = self.fn()
        except Exception as exc:
            ok, text = False, str(exc)[:500]
        self.done.emit(bool(ok), str(text))


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
    """Receives the signals of one chat's workers on the GUI thread and runs the normal handler *as that chat*
    (MainWindow._as), so a reply that arrives while another tab is in front is written into its own conversation."""

    def __init__(self, window, session):
        super().__init__(window)
        self.w, self.s = window, session

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


class MainWindow(QMainWindow):
    # Per-chat state: one ChatSession per character; these names read/write the session that is current (see chat_sessions.py).
    busy = session_property("busy")
    worker = session_property("worker")
    _pending = session_property("_pending")
    _stream_text = session_property("_stream_text")
    _stream_pos = session_property("_stream_pos")
    _stream_dirty = session_property("_stream_dirty")
    _stream_mood = session_property("_stream_mood")
    _partial_saved = session_property("_partial_saved")
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

    def __init__(self):
        super().__init__()
        self.settings = load_settings()
        self.sessions = {}
        self.cur = self.front = ChatSession(characters.active_id(self.settings))
        self.sessions[self.cur.cid] = self.cur
        self._db_notes = init_db()
        self._save_warned = False
        self._emotion_applied = False
        self._closing = False
        self._partial_saved = False
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
        self._pending = []                 # messages typed while an answer is being generated (sent one by one afterwards)
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
        self.speaker.cloud_note.connect(self.on_cloud_note)
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
        self.build_assistant_section()
        self.build_voice_tab()
        self.build_characters_tab()
        self.build_general_tab()
        self.build_ai_tab()
        self.save_btn = QPushButton()
        self.save_btn.setObjectName("save")
        self.save_btn.setIcon(make_icon("check", normal="#ffffff", hover="#ffffff"))
        self.save_btn.setIconSize(QSize(16, 16))
        self.save_btn.clicked.connect(self.apply_settings)
        self.reg(self.save_btn.setText, "save")
        self.tab_keys = ["tab_chat", "tab_assistant", "tab_voice", "tab_char", "tab_general", "tab_ai"]
        self.tidy_forms()                      # field widths follow their content (done once every page exists)
        for i, key in enumerate(self.tab_keys):
            self.reg(lambda s, i=i: self.tabs.setTabText(i, s), key)
        # Compact icon navigation. The QTabWidget stays as the page stack (its tab strip is hidden).
        self.tabs.tabBar().hide()
        ai_index = self.tab_keys.index("tab_ai")
        self.nav_chat_btn = self.icon_button("chat", True)
        self.nav_chat_btn.clicked.connect(lambda: self.go_tab(0))
        self.reg(self.nav_chat_btn.setToolTip, "tab_chat")
        self.nav_route_btn = self.icon_button("route", True)
        self.nav_route_btn.clicked.connect(lambda: self.go_tab(ai_index))
        self.reg(self.nav_route_btn.setToolTip, "tab_ai")
        self.menu_btn = QToolButton()
        self.menu_btn.setObjectName("menuBtn")
        self.menu_btn.setIcon(make_icon("menu"))
        self.menu_btn.setIconSize(QSize(20, 20))
        self.menu_btn.setCursor(Qt.PointingHandCursor)
        self.reg(self.menu_btn.setToolTip, "nav_menu_tip")
        self.menu_btn.setPopupMode(QToolButton.InstantPopup)
        self.nav_menu = QMenu(self)
        self.menu_btn.setMenu(self.nav_menu)
        self._menu_actions = []
        for i, key in enumerate(self.tab_keys):
            action = self.nav_menu.addAction(self.t(key))
            action.triggered.connect(lambda checked=False, idx=i: self.go_tab(idx))
            self._menu_actions.append(action)
        central = QWidget()
        central_layout = QVBoxLayout(central)
        central_layout.setContentsMargins(10, 8, 10, 10)
        central_layout.setSpacing(8)
        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(0, 0, 0, 0)
        toolbar.setSpacing(4)
        toolbar.addWidget(self.nav_chat_btn)
        toolbar.addWidget(self.nav_route_btn)
        toolbar.addWidget(self.menu_btn)
        toolbar.addStretch(1)
        toolbar.addWidget(self.save_btn)
        central_layout.addLayout(toolbar)
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
        self.apply_runtime()
        self.retranslate()
        self.set_badge("idle", self.client.preview_route())
        self.sync_sessions()
        self.switch_session(characters.active_id(self.settings), save=False)
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
        if hasattr(self, "_menu_actions"):
            for action, key in zip(self._menu_actions, self.tab_keys):
                action.setText(self.t(key))
        if getattr(self, "cloud_page", None) is not None:
            self.cloud_page.retranslate(self.t)

    def on_voice_error(self, message):
        """Voice failures (e.g. no internet for edge-tts) are shown once per 10 minutes, not after every reply."""
        now = time.monotonic()
        if now - getattr(self, "_voice_err_at", -1e9) < 600:
            return
        self._voice_err_at = now
        self.add_chat("error", message + "\n" + self.t("voice_err_hint"))

    # ---------- chat sessions (one independent conversation per character) ----------
    @contextlib.contextmanager
    def _as(self, session):
        """Run code as `session` (its history, router, stream state and character). Used by every worker / timer callback,
        so a reply for a background tab is handled exactly like one for the visible tab - just without voice / face / status."""
        prev, prev_cid = self.cur, self.settings.get("active_character_id", "kira")
        self.cur = session
        self.settings["active_character_id"] = session.cid
        try:
            yield session
        finally:
            self.cur = prev
            self.settings["active_character_id"] = prev_cid

    def accent(self):
        theme = getattr(self.cur, "theme", None)
        return theme_mod.chat_accent(theme) if theme else None

    def _new_router(self):
        """Router of one chat. Cooldowns / health are shared with the other chats (a failing key is failing for everyone)."""
        router = HybridRouter(self.settings)
        base = next((sess.client for sess in self.sessions.values() if sess.client is not None), None)
        if base is not None:
            router.cooldowns, router.states = base.cooldowns, base.states
        return router

    def make_session_view(self):
        view = QTextBrowser()                              # read-only chat whose links open in the default browser
        view.setObjectName("chatView")
        view.setOpenLinks(False)                           # links are handled in on_chat_link (web pages + the Ai1 Code approve / reject links)
        view.setOpenExternalLinks(False)
        view.anchorClicked.connect(self.on_chat_link)
        view.setReadOnly(True)
        view.setFrameShape(QFrame.NoFrame)
        return view

    def on_chat_link(self, url):
        """Web / mail links open in the default app; kira-code:// links are the Diff approve / reject buttons of Ai1 Code mode;
        kira-action:// links are the per-message copy / edit / speak chips."""
        if url.scheme() == "kira-action":
            self.handle_chat_link(url)
            return
        if url.scheme() == "kira-code":
            code_chat = getattr(self, "code_chat", None)
            if code_chat is not None:
                code_chat.on_link(url)
            return
        if url.scheme() in ("http", "https", "mailto"):
            QDesktopServices.openUrl(url)

    def active_character(self):
        """Full profile of the character in front. Kira keeps her canonical identity (the profiles list only carries UI data)."""
        cid = getattr(getattr(self, "cur", None), "cid", "") or characters.active_id(self.settings)
        if cid == "kira":
            profile = dict(KIRA_PROFILE)
        else:
            profile = dict(characters.all_profiles(self.settings).get(cid) or characters.active(self.settings))
        traits = (self.settings.get("character_traits") or {}).get(cid)
        if isinstance(traits, dict):
            profile["traits"] = {**profile.get("traits", {}), **traits}
        return profile

    def character_traits(self, cid, profile=None):
        """Baseline traits of one character (settings overrides win over the built-in defaults)."""
        profile = profile if isinstance(profile, dict) else (characters.all_profiles(self.settings).get(cid) or {})
        traits = dict(profile.get("traits") or {})
        override = (self.settings.get("character_traits") or {}).get(cid)
        if isinstance(override, dict):
            traits.update(override)
        return traits

    def _sync_mood_character(self):
        """Point the persisted mood at the character in front so its neon chips and prompt follow that profile."""
        cid = getattr(getattr(self, "cur", None), "cid", "") or characters.active_id(self.settings)
        profile = characters.all_profiles(self.settings).get(cid) or {}
        try:
            mood.set_active_character(cid, self.character_traits(cid, profile))
        except Exception:                                   # noqa: BLE001 - mood is a bonus, never block the UI
            pass

    def _ensure_session(self, cid, profile):
        sess = self.sessions.get(cid)
        if sess is None:
            sess = ChatSession(cid)
            self.sessions[cid] = sess
        if sess.view is None:
            sess.view = self.make_session_view()
            self.chat_stack.addWidget(sess.view)
            sess.timer = QTimer(self)
            sess.timer.setInterval(60)
            sess.relay = SessionRelay(self, sess)
            sess.timer.timeout.connect(sess.relay.tick)
        if sess.client is None:
            sess.client = self._new_router()
        sess.theme = theme_mod.character_theme(cid, profile)
        if sess.cid not in self.char_tab_buttons:
            button = QPushButton()
            button.setObjectName("charTab")
            button.setCheckable(True)
            button.setCursor(Qt.PointingHandCursor)
            button.setFocusPolicy(Qt.NoFocus)
            button.clicked.connect(lambda checked=False, c=cid: self.switch_session(c))
            self.char_tab_group.addButton(button)
            self.char_tab_buttons[cid] = button
        return sess

    def sync_sessions(self):
        """Make the tabs match the characters that exist now (built-in ones + custom ones, minus deleted ones)."""
        profiles = characters.all_profiles(self.settings)
        order = [c for c in ("kira", "ren", "mika") if c in profiles] + [c for c in profiles if c not in ("kira", "ren", "mika")]
        for cid in order:
            sess = self._ensure_session(cid, profiles[cid])
            if not sess.loaded:
                sess.loaded = True
                with self._as(sess):
                    self.restore_history()
        order += [c for c in self.sessions if c not in order]          # a deleted character that is still answering keeps its tab for now
        for cid in [c for c in self.sessions if c not in profiles]:      # a deleted character: close its tab (unless it is answering)
            sess = self.sessions[cid]
            if sess.busy:
                continue
            self.char_tabs_row.removeWidget(self.char_tab_buttons[cid])
            self.char_tab_group.removeButton(self.char_tab_buttons[cid])
            self.char_tab_buttons.pop(cid).deleteLater()
            self.chat_stack.removeWidget(sess.view)
            sess.view.deleteLater()
            sess.timer.stop()
            del self.sessions[cid]
            if self.front is sess or self.cur is sess:
                self.front = self.cur = self.sessions["kira"]
        while self.char_tabs_row.count():                                # rebuild the row in character order
            self.char_tabs_row.takeAt(0)
        for cid in order:
            if cid in self.char_tab_buttons:
                self.char_tabs_row.addWidget(self.char_tab_buttons[cid])
        self.char_tabs_row.addStretch(1)
        self.refresh_tab_buttons()

    def refresh_tab_buttons(self):
        profiles = characters.all_profiles(self.settings)
        for cid, button in self.char_tab_buttons.items():
            sess = self.sessions.get(cid)
            profile = profiles.get(cid) or {}
            name = profile.get("name_fa") if self.settings.get("ui_lang", "fa") == "fa" else profile.get("name")
            mark = ""
            if sess is not None and sess.busy:
                mark = "  ⏳"
            elif sess is not None and sess.unread:
                mark = "  ●"
            button.setText(f"{name or cid}{mark}")
            button.setChecked(sess is self.front)

    def switch_session(self, cid, save=True):
        """Bring one character's chat to the front: its conversation, its colours, its picture. Other chats keep working."""
        sess = self.sessions.get(cid)
        if sess is None:
            return
        old = self.front
        if old is not sess:
            old.draft = self.input.text()
            if old._speech_live:                       # the voice belongs to the chat in front
                old._speech_live = False
            self.safe_stop_speaker()
            try:
                self.speaker.stream_reset()
            except Exception:                           # noqa: BLE001
                pass
            self.clear_upload_tiles()
        self.front = self.cur = sess
        sess.unread = False
        self.settings["active_character_id"] = cid
        self.refresh_navigation_icons()
        try:
            mood.set_active_character(cid, self.character_traits(cid, characters.all_profiles(self.settings).get(cid)))
        except Exception:                               # noqa: BLE001 - never block switching tabs
            pass
        self.chat_stack.setCurrentWidget(sess.view)
        if old is not sess:
            self.input.setText(sess.draft)
        self.apply_chat_theme()
        self.apply_character_art()
        self.gen_stop_btn.setVisible(bool(sess.busy))
        self.gen_stop_btn.setEnabled(True)
        if sess.busy:
            self.set_status("st_thinking")
        else:
            self.set_status("st_ready")
        phase, info = sess.badge
        self.set_badge(phase if sess.busy else "idle", info if sess.busy else self.client.preview_route())
        self.refresh_tab_buttons()
        if hasattr(self, "character_combo"):
            self.refresh_character_choices()
            self.refresh_character_card(cid)
        self.refresh_personality_controls()
        self.update_mood_indicator()
        bar = sess.view.verticalScrollBar()
        bar.setValue(bar.maximum())
        if save:
            try:
                save_settings(self.settings)
            except Exception:                           # noqa: BLE001 - never block switching tabs
                pass

    def apply_chat_theme(self):
        """Glass + neon colours of the chat in front (same glass, the character's own colours)."""
        theme = self.front.theme or theme_mod.character_theme("kira")
        self.chat_page.setStyleSheet(theme_mod.character_style(theme, getattr(self, "_effect", "off")))
        r, g, b = (int(theme["main"].lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
        for glow in self.glow_effects:
            glow.setColor(QColor(r, g, b, 150))

    def greeting_text(self):
        profile = characters.active(self.settings)
        if profile["id"] == "kira":
            return self.t("greeting")
        name = profile.get("name_fa") if self.settings.get("ui_lang", "fa") == "fa" else profile.get("name")
        if self.settings.get("ui_lang", "fa") == "fa":
            return f"سلام! من {name} هستم. {profile.get('description', '')}"
        return f"Hi! I'm {name}. {profile.get('description', '')}"

    def restore_history(self, limit=40):
        """Show the saved conversation of the CURRENT chat again after a restart (it is already used as model context)."""
        try:
            history = recent_messages(limit, self.cur.cid)
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
        if len(self._chat_action_texts) > 300:
            self._chat_action_texts.pop(next(iter(self._chat_action_texts)))
        actions = [
            ("copy", "⧉", "#8CF5FF", "#103A52", "#39DFFF", "کپی"),
            ("edit", "✎", "#E0C8FF", "#30214F", "#B18AFF", "ویرایش"),
            ("speak", "♫", "#FFC0E9", "#4B2044", "#FF83D0", "خواندن"),
        ]
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
                self.safe_stop_speaker()
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
        self.nav_chat_btn.setChecked(i == 0)
        self.nav_route_btn.setChecked(i == self.tab_keys.index("tab_ai"))
        self.save_btn.setVisible(i != 0)            # the chat page needs no Save button
        if hasattr(self, "_voice_form") and i == self.tab_keys.index("tab_voice"):
            self.refresh_voice_caps()               # Cloud Voice may have been changed in the Route section meanwhile

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
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(8)
        return box, form

    def page(self, *boxes):
        host = QWidget()
        lay = QVBoxLayout(host)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(8)
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
        cid = characters.active_id(self.settings)
        profile = characters.all_profiles(self.settings).get(cid, {})
        palette = theme_mod.character_theme(cid, profile)
        b.setIcon(make_icon(name, normal=palette["second"], hover="#FFFFFF",
                            checked=palette["main"], disabled="#52617B"))
        b.setIconSize(QSize(20, 20))
        b.setCheckable(checkable)
        b.setCursor(Qt.PointingHandCursor)
        b.setFocusPolicy(Qt.NoFocus)
        return b

    def refresh_navigation_icons(self):
        """Keep shared navigation glyphs in sync when the active character changes."""
        cid = characters.active_id(self.settings)
        profile = characters.all_profiles(self.settings).get(cid, {})
        palette = theme_mod.character_theme(cid, profile)
        for attr, name in (("nav_chat_btn", "chat"), ("nav_route_btn", "route"), ("menu_btn", "menu")):
            button = getattr(self, attr, None)
            if button is not None:
                button.setIcon(make_icon(name, normal=palette["second"], hover="#FFFFFF",
                                          checked=palette["main"], disabled="#52617B"))
        badge = getattr(self, "route_badge", None)
        if badge is not None:
            badge.setIcon(make_icon("chevron_up", normal=palette["second"], hover="#FFFFFF",
                                    checked=palette["main"], disabled="#52617B"))

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
        header = QHBoxLayout()
        header.setSpacing(6)
        self.title = QLabel("Project Kira")
        self.title.setObjectName("title")
        header.addWidget(self.title)
        header.addStretch(1)
        self.mood_emotion_icon = QLabel()
        self.mood_emotion_icon.setObjectName("moodEmotionIcon")
        self.mood_emotion_icon.setAlignment(Qt.AlignCenter)
        self.mood_emotion_icon.setFixedSize(38, 38)
        self.mood_emotion_icon.setToolTip("احساس فعلی شخصیت فعال")
        self.mood_emotion_icon.setStyleSheet(
            "QLabel#moodEmotionIcon { background: rgba(12, 20, 43, 0.96); "
            "border: 1px solid rgba(105, 229, 255, 0.85); border-radius: 11px; padding: 2px; }"
        )
        header.addWidget(self.mood_emotion_icon)
        self.mood_indicator = QLabel()
        self.mood_indicator.setObjectName("moodIndicator")
        self.mood_indicator.setAlignment(Qt.AlignCenter)
        self.mood_indicator.hide()
        self.mood_indicator.setFixedSize(32, 32)
        self.mood_indicator.setToolTip("رفتار و انرژی فعلی شخصیت فعال")
        self.mood_indicator.setStyleSheet(
            "QLabel#moodIndicator { background: rgba(20, 24, 62, 0.92); "
            "border: 1px solid rgba(137, 112, 255, 0.88); border-radius: 11px; "
            "padding: 4px 7px; font-size: 16px; color: #F2E9FF; }"
        )
        header.addWidget(self.mood_indicator)
        self.companion_btn = self.icon_button("user", True)
        self.companion_btn.clicked.connect(self.toggle_companion)
        header.addWidget(self.companion_btn)
        cv.addLayout(header)
        self.chat_stack = QStackedWidget()                 # one read-only chat view per character (created in make_session_view)
        cv.addWidget(self.chat_stack, 1)
        composer = QFrame()
        composer.setObjectName("composer")
        co = QVBoxLayout(composer)
        co.setContentsMargins(10, 6, 8, 6)
        co.setSpacing(2)
        self.send_strip = self.make_tile_strip()           # cards with the upload percentage while a message is being sent
        self.attach_strip = self.make_tile_strip()         # cards of the files chosen for the next message
        self.attach_err = QLabel()
        self.attach_err.setObjectName("hint")
        self.attach_err.setWordWrap(True)
        self.attach_err_close = QToolButton()
        self.attach_err_close.setObjectName("attClose")
        self.attach_err_close.setText("✕")
        self.attach_err_close.setToolTip("لغو بارگذاری ضمیمه‌ها / بستن پیام")
        self.attach_err_close.setCursor(Qt.PointingHandCursor)
        self.attach_err_close.setFixedSize(20, 20)
        self.attach_err_close.clicked.connect(self.cancel_attachments)
        self.attach_err_row = QHBoxLayout()
        self.attach_err_row.setContentsMargins(0, 0, 0, 0)
        self.attach_err_row.addWidget(self.attach_err, 1)
        self.attach_err_row.addWidget(self.attach_err_close)
        self.attach_err_widget = QWidget()
        self.attach_err_widget.setLayout(self.attach_err_row)
        self.attach_err_widget.hide()
        co.addWidget(self.send_strip)
        co.addWidget(self.attach_strip)
        co.addWidget(self.attach_err_widget)
        self.input = ChatInput()
        self.input.filesDropped.connect(self.add_attachment_paths)
        self.input.imagePasted.connect(self.add_pasted_image)
        self.input.returnPressed.connect(self.send_message)
        self.input.textChanged.connect(lambda: self.on_input_changed(self.input.text()))
        co.addWidget(self.input)
        bar = QHBoxLayout()
        bar.setSpacing(2)
        # Model indicator: Claude 2's compact chip, driven by the router (set_badge / build_badge_menu).
        self.route_badge = RouteChip()
        self.route_badge.setObjectName("routeChip")
        self.route_badge.setText("● Ready")
        self.route_badge.setIcon(make_icon("chevron_up", normal="#4FD8FF", hover="#FFFFFF"))
        self.route_badge.setIconSize(QSize(12, 12))
        self.route_badge.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.route_badge.setCursor(Qt.PointingHandCursor)
        self.route_badge.setFocusPolicy(Qt.NoFocus)
        self.route_badge.setPopupMode(QToolButton.InstantPopup)
        self.route_menu = QMenu(self)
        self.route_menu.setStyleSheet("QMenu { menu-scrollable: 1; }")      # many models: scroll with the wheel / arrows
        self.route_menu.aboutToShow.connect(self.build_badge_menu)
        self.route_badge.setMenu(self.route_menu)
        bar.addWidget(self.route_badge)
        self.attach_btn = QToolButton()
        self.attach_btn.setText("📎")
        self.attach_btn.setToolTip("پیوست عکس یا فایل (می‌توانی فایل را روی پنجره بکشی یا عکس را Ctrl+V کنی)")
        self.attach_btn.setCursor(Qt.PointingHandCursor)
        self.attach_btn.setFocusPolicy(Qt.NoFocus)
        self.attach_btn.clicked.connect(self.pick_attachments)
        bar.addWidget(self.attach_btn)
        self.web_btn = QToolButton()
        self.web_btn.setText("🌐")
        self.web_btn.setCheckable(True)
        self.web_btn.setChecked(bool(self.settings.get("web_search", True)))
        self.web_btn.setCursor(Qt.PointingHandCursor)
        self.web_btn.setFocusPolicy(Qt.NoFocus)
        self.web_btn.toggled.connect(self.toggle_web_search)
        self.update_web_tip()
        bar.addWidget(self.web_btn)
        self.img_search_btn = QToolButton()
        self.img_search_btn.setText("🔎")
        self.img_search_btn.setCheckable(True)
        self.img_search_btn.setChecked(bool(self.settings.get("image_search", False)))
        self.img_search_btn.setCursor(Qt.PointingHandCursor)
        self.img_search_btn.setFocusPolicy(Qt.NoFocus)
        self.img_search_btn.toggled.connect(self.toggle_image_search)
        self.update_image_search_tip()
        bar.addWidget(self.img_search_btn)
        self.code_chat = CodeChat(self)                     # Ai1 Code: no button; Kira's chat understands coding requests by itself
        bar.addStretch(1)
        self.mic_btn = self.icon_button("mic", True)
        self.mic_btn.clicked.connect(self.toggle_mic)
        self.wake_btn = self.icon_button("moon", True)
        self.wake_btn.clicked.connect(self.toggle_wake)
        self.voice_btn = self.icon_button("speaker", True)
        self.voice_btn.setChecked(bool(self.settings.get("speak_replies", True)))
        self.voice_btn.clicked.connect(lambda: self.set_voice_enabled(self.voice_btn.isChecked()))
        self.game_mode_btn = QToolButton()
        self.game_mode_btn.setObjectName("gameModeBtn")
        self.game_mode_btn.setText("🎮")
        self.game_mode_btn.setCheckable(False)
        self.game_mode_btn.setCursor(Qt.PointingHandCursor)
        self.game_mode_btn.setFocusPolicy(Qt.NoFocus)
        self.game_mode_menu = QMenu(self.game_mode_btn)
        self.game_mode_story_action = QAction("Story Mode · آفلاین و داستانی", self.game_mode_menu)
        self.game_mode_story_action.setCheckable(True)
        self.game_mode_story_action.triggered.connect(lambda checked=False: self.set_game_mode_profile(STORY_MODE))
        self.game_mode_safe_action = QAction("Competitive Safe · آنلاین و PvP", self.game_mode_menu)
        self.game_mode_safe_action.setCheckable(True)
        self.game_mode_safe_action.setChecked(True)
        self.game_mode_safe_action.triggered.connect(lambda checked=False: self.set_game_mode_profile(COMPETITIVE_SAFE_MODE))
        self.game_mode_off_action = QAction("خاموش‌کردن Game Mode", self.game_mode_menu)
        self.game_mode_off_action.triggered.connect(lambda checked=False: self.set_game_mode(False))
        self.vision_rate_menu = self.game_mode_menu.addMenu("سرعت Vision")
        self.vision_rate_actions = {}
        for mode, label in (("economic", "اقتصادی · هر ۵ ثانیه"), ("smart", "هوشمند · هر ۱ ثانیه"), ("fast", "سریع · هر نیم‌ثانیه")):
            action = QAction(label, self.vision_rate_menu)
            action.setCheckable(True)
            action.setChecked(mode == self._vision_gate.policy.name)
            action.triggered.connect(lambda checked=False, selected=mode: self.set_vision_mode(selected))
            self.vision_rate_menu.addAction(action)
            self.vision_rate_actions[mode] = action
        self.game_mode_menu.addAction(self.game_mode_story_action)
        self.game_mode_menu.addAction(self.game_mode_safe_action)
        self.game_mode_menu.addSeparator()
        self.game_mode_menu.addAction(self.game_mode_off_action)
        self.game_mode_btn.setMenu(self.game_mode_menu)
        self.game_mode_btn.setPopupMode(QToolButton.InstantPopup)
        self.game_mode_btn.setToolTip("انتخاب حالت بازی: Story یا Competitive Safe")
        bar.addWidget(self.game_mode_btn)
        self.stop_btn = self.icon_button("stop")
        self.stop_btn.clicked.connect(lambda *_: self.on_stop_clicked())
        for b, k in ((self.mic_btn, "mic"), (self.wake_btn, "wake"), (self.voice_btn, "voice"), (self.stop_btn, "stop")):
            self.reg(b.setToolTip, k)
            bar.addWidget(b)
        # Stop the ANSWER being generated (different from the voice-stop icon): red round button, visible only while generating.
        self.gen_stop_btn = QToolButton()
        self.gen_stop_btn.setObjectName("genStop")
        self.gen_stop_btn.setIcon(make_icon("stop", normal="#ffffff", hover="#ffffff", disabled="#e0aab3"))
        self.gen_stop_btn.setIconSize(QSize(16, 16))
        self.gen_stop_btn.setFixedSize(32, 32)
        self.gen_stop_btn.setCursor(Qt.PointingHandCursor)
        self.gen_stop_btn.setFocusPolicy(Qt.NoFocus)
        self.gen_stop_btn.setToolTip("توقف تولید پاسخ (متن دریافت‌شده تا اینجا حفظ می‌شود)")
        self.gen_stop_btn.clicked.connect(self.stop_generation)
        self.gen_stop_btn.hide()
        self.send_btn = QToolButton()
        self.send_btn.setObjectName("sendBtn")
        self.send_btn.setIcon(make_icon("send", normal="#ffffff", hover="#ffffff", disabled="#7d8095"))
        self.send_btn.setIconSize(QSize(18, 18))
        self.send_btn.setFixedSize(32, 32)
        self.send_btn.setCursor(Qt.PointingHandCursor)
        self.send_btn.setFocusPolicy(Qt.NoFocus)
        self.reg(self.send_btn.setToolTip, "send")
        self.send_btn.clicked.connect(self.send_message)
        bar.addSpacing(4)
        bar.addWidget(self.gen_stop_btn)
        bar.addWidget(self.send_btn)
        co.addLayout(bar)
        cv.addWidget(composer)
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
        s = self.settings
        box1, f1 = self.group("g_assistant")
        self.name = self.row(f1, "name", QLineEdit(s["assistant_name"]))
        self.persona = QTextEdit()
        self.persona.setPlainText(s["persona"])
        self.persona.setMinimumHeight(110)
        self.row(f1, "persona", self.persona)
        self.modes_chk = QCheckBox()
        self.modes_chk.setChecked(bool(s.get("active_modes", True)))
        self.reg(self.modes_chk.setText, "active_modes")
        self.reg(self.modes_chk.setToolTip, "active_modes_tip")
        f1.addRow(self.modes_chk)
        self.temp = self.row(f1, "temp", QComboBox())
        self.temp.addItems(["0.2", "0.4", "0.7", "0.9", "1.0"])
        self.temp.setCurrentText(str(s.get("temperature", 0.7)))
        box2, f2 = self.group("g_model")
        ocfg = s.get("providers", {}).get("ollama", {})
        local_route_note = QLabel("فعال‌سازی و اولویت Ollama از بخش Route مدیریت می‌شود.")
        local_route_note.setObjectName("hint")
        local_route_note.setWordWrap(True)
        f2.addRow(local_route_note)
        self.model = self.row(f2, "model", ModelCombo(s["model"]))
        self.url = self.row(f2, "url", QLineEdit(s["ollama_url"]))
        self.use_qwen_btn = QPushButton()
        self.reg(self.use_qwen_btn.setText, "o_use_qwen")
        self.use_qwen_btn.clicked.connect(lambda: self.model.setText("qwen3.5:4b"))
        f2.addRow(self.use_qwen_btn)
        self.num_ctx = self.row(f2, "o_ctx", QSpinBox())
        self.num_ctx.setRange(1024, 32768)
        self.num_ctx.setSingleStep(1024)
        self.num_ctx.setValue(clamp_num_ctx(ocfg.get("num_ctx", DEFAULT_NUM_CTX)))
        self.num_predict = self.row(f2, "o_predict", QSpinBox())
        self.num_predict.setRange(32, 4096)
        self.num_predict.setSingleStep(64)
        self.num_predict.setValue(clamp_num_predict(ocfg.get("num_predict", DEFAULT_NUM_PREDICT)))
        self.keep_alive = self.row(f2, "o_keep", QComboBox())
        self.keep_alive.setEditable(True)
        self.keep_alive.addItems(["0", "30s", "2m", "5m", "15m"])
        self.keep_alive.setCurrentText(str(ocfg.get("keep_alive", DEFAULT_KEEP_ALIVE)))
        keep_hint = QLabel()
        keep_hint.setObjectName("hint")
        keep_hint.setWordWrap(True)
        self.reg(keep_hint.setText, "o_keep_hint")
        f2.addRow(keep_hint)
        self.conn_btn = QPushButton()
        self.reg(self.conn_btn.setText, "check_conn")
        self.conn_btn.clicked.connect(self.test_connection)
        self.load_btn = QPushButton()
        self.reg(self.load_btn.setText, "o_load")
        self.load_btn.clicked.connect(self.load_local_model)
        self.unload_btn = QPushButton()
        self.reg(self.unload_btn.setText, "o_unload")
        self.unload_btn.clicked.connect(self.unload_local_model)
        h = QHBoxLayout()
        h.addWidget(self.conn_btn)
        h.addWidget(self.load_btn)
        h.addWidget(self.unload_btn)
        f2.addRow(h)
        self.speed_btn = QPushButton()
        self.reg(self.speed_btn.setText, "o_speed")
        self.speed_btn.clicked.connect(self.speed_test)
        f2.addRow(self.speed_btn)
        self.conn_lbl = QLabel()
        self.conn_lbl.setWordWrap(True)
        f2.addRow(self.conn_lbl)
        game_note = QLabel()
        game_note.setObjectName("hint")
        game_note.setWordWrap(True)
        self.reg(game_note.setText, "o_game_note")
        f2.addRow(game_note)
        self.tabs.addTab(self.page(box1, box2), "")

    def voice_row(self, form, key, items, current, lang_key):
        combo = QComboBox()
        combo.setEditable(True)
        combo.addItems(items)
        combo.setCurrentText(current)
        btn = QPushButton()
        self.reg(btn.setText, "test")
        btn.clicked.connect(lambda: self.test_voice(combo.currentText().strip(), lang_key))
        h = QHBoxLayout()
        h.addWidget(combo, 1)
        h.addWidget(btn)
        lab = QLabel()
        self.reg(lab.setText, key)
        form.addRow(lab, h)
        return combo

    def build_voice_tab(self):
        s = self.settings
        box1, f1 = self.group("g_tts")
        self.speak_chk = QCheckBox()
        self.speak_chk.setChecked(bool(s.get("speak_replies", True)))
        self.speak_chk.toggled.connect(self.set_voice_enabled)
        self.reg(self.speak_chk.setText, "speak_on")
        f1.addRow(self.speak_chk)
        self.stream_chk = QCheckBox()
        self.stream_chk.setChecked(bool(s.get("stream_speech", True)))
        self.reg(self.stream_chk.setText, "stream_speech")
        self.reg(self.stream_chk.setToolTip, "stream_speech_tip")
        f1.addRow(self.stream_chk)
        self.voice_fa = self.voice_row(f1, "voice_fa", EDGE_FA, s["voice_fa"], "fa")
        self.voice_en = self.voice_row(f1, "voice_en", EDGE_EN, s["voice_en"], "en")
        self.voice_ja = self.voice_row(f1, "voice_ja", EDGE_JA, s["voice_ja"], "ja")
        self.rate = self.row(f1, "rate", QSpinBox())
        self.rate.setRange(-50, 50); self.rate.setSuffix(" %"); self.rate.setValue(int(s["voice_rate"]))
        self.pitch = self.row(f1, "pitch", QSpinBox())
        self.pitch.setRange(-50, 50); self.pitch.setSuffix(" Hz"); self.pitch.setValue(int(s["voice_pitch"]))
        self.voice_style = self.row(f1, "voice_style", QComboBox())
        for key, label in cloud_voice.STYLE_LABELS.items():
            self.voice_style.addItem(label, key)
        self.voice_style.setCurrentIndex(max(0, self.voice_style.findData(str(s.get("voice_style") or ""))))
        self.voice_style_deg = self.row(f1, "voice_style_degree", QSlider(Qt.Horizontal))
        self.voice_style_deg.setRange(0, 100); self.voice_style_deg.setValue(int(s.get("voice_style_degree", 50)))
        self.volume = self.row(f1, "volume", QSlider(Qt.Horizontal))
        self.volume.setRange(0, 100); self.volume.setValue(int(float(s["voice_volume"]) * 100))
        self.out_device = self.row(f1, "output_device", QComboBox())
        self.fill_output_devices(str(s.get("output_device") or ""))
        self.voice_caps_note = QLabel()
        self.voice_caps_note.setObjectName("hint")
        self.voice_caps_note.setWordWrap(True)
        f1.addRow(self.voice_caps_note)
        self._voice_form = f1
        box2, f2 = self.group("g_stt")
        self.stt_lang = self.row(f2, "stt_lang", QComboBox())
        self.stt_lang.addItems(["fa", "en", "auto"]); self.stt_lang.setCurrentText(s["stt_language"])
        self.whisper = self.row(f2, "whisper", QComboBox())
        self.whisper.setEditable(True)                  # any faster-whisper model name, Hugging Face repo or local folder
        self.whisper.addItems(["base", "small", "medium", "large-v3-turbo", "large-v3", "parseh/whisper-fa-accuracy-ct2"])
        self.whisper.setCurrentText(s["whisper_model"])
        self.reg(self.whisper.setToolTip, "whisper_tip")
        fixes_btn = QPushButton()
        self.reg(fixes_btn.setText, "open_fixes")
        fixes_btn.clicked.connect(self.open_speech_fixes)
        f2.addRow(fixes_btn)
        cloud_btn = QPushButton()
        self.reg(cloud_btn.setText, "cv_open_route")
        cloud_btn.clicked.connect(self.show_voice_routes)
        f2.addRow(cloud_btn)
        self.mic_device = self.row(f2, "mic_device", QComboBox())
        self.fill_mic_devices(str(s.get("mic_device") or ""))
        self.mic_gain = self.row(f2, "mic_gain", QSlider(Qt.Horizontal))
        self.mic_gain.setRange(50, 300); self.mic_gain.setValue(int(s.get("mic_gain", 100)))
        self.mic_sens = self.row(f2, "mic_sens", QSlider(Qt.Horizontal))
        self.mic_sens.setRange(50, 200); self.mic_sens.setValue(int(s.get("mic_sensitivity", 100)))
        self.barge_chk = QCheckBox(); self.barge_chk.setChecked(bool(s.get("barge_in", True)))
        self.reg(self.barge_chk.setText, "barge_in")
        f2.addRow(self.barge_chk)
        self.wake_timeout = self.row(f2, "wake_timeout", QSpinBox())
        self.wake_timeout.setRange(5, 120); self.wake_timeout.setValue(int(s["wake_timeout"]))
        self.engine_lbl = self.row(f2, "engine", QLabel())
        self._voice_save_timer = QTimer(self)
        self._voice_save_timer.setSingleShot(True)
        self._voice_save_timer.setInterval(600)
        self._voice_save_timer.timeout.connect(self.autosave_voice)
        for w in (self.rate, self.pitch, self.voice_style_deg, self.volume, self.mic_gain, self.mic_sens):
            w.valueChanged.connect(lambda *_: self._voice_save_timer.start())
        for w in (self.voice_style, self.out_device, self.mic_device):
            w.currentIndexChanged.connect(lambda *_: self._voice_save_timer.start())
        self.refresh_voice_caps()
        self.tabs.addTab(self.page(box1, box2), "")

    # ---- voice: devices, supported controls, autosave ----
    def fill_output_devices(self, current):
        self.out_device.clear()
        self.out_device.addItem(self.t("dev_default"), "")
        try:
            from PySide6.QtMultimedia import QMediaDevices
            seen = set()
            for dev in QMediaDevices.audioOutputs():
                name = dev.description()
                if name and name not in seen:
                    seen.add(name)
                    self.out_device.addItem(name, name)
        except Exception:                                      # noqa: BLE001 - no audio backend: only the default entry
            pass
        i = self.out_device.findData(current)
        self.out_device.setCurrentIndex(i if i >= 0 else 0)

    def fill_mic_devices(self, current):
        self.mic_device.clear()
        self.mic_device.addItem(self.t("dev_default"), "")
        try:
            import sounddevice as sd
            seen = set()
            for dev in sd.query_devices():
                name = str(dev.get("name") or "")
                if dev.get("max_input_channels", 0) > 0 and name and name not in seen:
                    seen.add(name)
                    self.mic_device.addItem(name, name)
        except Exception:                                      # noqa: BLE001 - sounddevice missing: only the default entry
            pass
        i = self.mic_device.findData(current)
        self.mic_device.setCurrentIndex(i if i >= 0 else 0)

    def refresh_voice_caps(self):
        """Show a voice control only when an engine that is really in use supports it (and say which one)."""
        try:
            sup = voice_caps.supported(self.settings)
            chain = " ← ".join(label for label, _ in voice_caps.chain(self.settings))
        except Exception:                                      # noqa: BLE001
            sup, chain = {c: ["?"] for c in voice_caps.CONTROLS}, ""
        for widget, key in ((self.rate, "rate"), (self.pitch, "pitch"), (self.voice_style, "style"), (self.voice_style_deg, "style_degree")):
            names = sup.get(key) or []
            self._voice_form.setRowVisible(widget, bool(names))
            if names:
                widget.setToolTip(self.t("voice_supported_by") + " " + "، ".join(names))
        self.voice_caps_note.setText(self.t("voice_caps_note", chain=chain or "-"))

    def collect_voice_settings(self):
        s = self.settings
        s.update({"voice_rate": self.rate.value(), "voice_pitch": self.pitch.value(), "voice_volume": self.volume.value() / 100.0,
                  "voice_style": self.voice_style.currentData() or "", "voice_style_degree": self.voice_style_deg.value(),
                  "output_device": self.out_device.currentData() or "", "mic_device": self.mic_device.currentData() or "",
                  "mic_gain": self.mic_gain.value(), "mic_sensitivity": self.mic_sens.value()})

    def autosave_voice(self):
        """Voice sliders / devices are saved as soon as they are changed (the Save button is not needed for them)."""
        self.collect_voice_settings()
        self.save_now()

    def build_cloud_voice_tab(self):
        """Cloud Voice providers (keys, models, STT / TTS order, failover). Shown inside the Route section, next to the chat providers."""
        service = cloud_voice.service()
        LOAD_WARNINGS.extend(service.store.warnings)
        self.cloud_page = CloudVoicePage(service, self.t, test_tts=self.test_cloud_voice, data_path=str(DATA_DIR / cloud_voice.FILE_NAME))
        return self.cloud_page

    def show_voice_routes(self):
        """Open the Route section on its voice (Cloud Voice) view."""
        self.go_tab(self.tab_keys.index("tab_ai"))
        self.set_route_view(1)

    def set_route_view(self, index):
        self.route_stack.setCurrentIndex(index)
        self.route_view_chat_btn.setChecked(index == 0)
        self.route_view_voice_btn.setChecked(index == 1)

    def test_cloud_voice(self):
        if not cloud_voice.service().tts_ready():
            self.add_chat("system", "صدای ابری آماده نیست: «از صدای ابری استفاده شود» را روشن کن و حداقل یک Provider معتبر و فعال داشته باش.")
            return
        self.animator.set_expression("happy", hold=3)
        self.speaker.speak(TEST_LINES["fa" if self.settings.get("ui_lang", "fa") == "fa" else "en"])

    def on_cloud_note(self, message):
        """Cloud Voice switched key / provider or fell back to the local engine (the same note is not repeated within a minute)."""
        now = time.monotonic()
        last = getattr(self, "_cloud_note_at", {})
        if now - last.get(message, -999) > 60:
            last[message] = now
            self._cloud_note_at = last
            self.add_chat("system", "🔁 " + message)

    def build_characters_tab(self):
        s = self.settings
        box, f = self.group("g_char")
        # Character selector: every profile shares the same brain, routes, tools and permissions.
        self.character_combo = QComboBox()
        self.character_portrait = QLabel()
        self.character_portrait.setFixedSize(144, 180)
        self.character_portrait.setScaledContents(True)
        self.character_portrait.setStyleSheet("border: 1px solid #6954a8; border-radius: 10px; background: #171326;")
        self.character_description = QLabel()
        self.character_description.setWordWrap(True)
        profile_row = QHBoxLayout()
        profile_row.addWidget(self.character_portrait)
        profile_info = QVBoxLayout()
        profile_info.addWidget(QLabel("شخصیت فعال"))
        profile_info.addWidget(self.character_combo)
        profile_info.addWidget(self.character_description)
        manager_row = QHBoxLayout()
        self.character_add_btn = QPushButton("شخصیت جدید")
        self.character_edit_btn = QPushButton("ویرایش")
        self.character_delete_btn = QPushButton("حذف")
        self.character_add_btn.clicked.connect(self.add_character)
        self.character_edit_btn.clicked.connect(self.edit_character)
        self.character_delete_btn.clicked.connect(self.delete_character)
        manager_row.addWidget(self.character_add_btn)
        manager_row.addWidget(self.character_edit_btn)
        manager_row.addWidget(self.character_delete_btn)
        profile_info.addLayout(manager_row)
        profile_row.addLayout(profile_info, 1)
        f.addRow(profile_row)
        self.refresh_character_choices()
        self.character_combo.currentIndexChanged.connect(self.select_character)
        self.refresh_character_card()
        self.size_sl = self.row(f, "char_size", QSlider(Qt.Horizontal))
        self.size_sl.setRange(300, 1000); self.size_sl.setValue(int(s["companion_height"]))
        self.follow_sl = self.row(f, "follow", QSlider(Qt.Horizontal))
        self.follow_sl.setRange(0, 150); self.follow_sl.setValue(int(float(s["follow_strength"]) * 100))
        self.motion_sl = self.row(f, "motion", QSlider(Qt.Horizontal))
        self.motion_sl.setRange(0, 200); self.motion_sl.setValue(int(float(s["motion_strength"]) * 100))
        self.react_chk = QCheckBox(); self.react_chk.setChecked(bool(s["click_reactions"]))
        self.reg(self.react_chk.setText, "reactions")
        self.top_chk = QCheckBox(); self.top_chk.setChecked(bool(s["always_on_top"]))
        self.reg(self.top_chk.setText, "on_top")
        self.idle_chk = QCheckBox(); self.idle_chk.setChecked(bool(s.get("idle_talk", True)))
        self.reg(self.idle_chk.setText, "idle_talk")
        f.addRow(self.react_chk)
        f.addRow(self.idle_chk)
        f.addRow(self.top_chk)
        self.tray_min_chk = QCheckBox("با دکمه‌ی Minimize به System Tray برود")
        self.tray_min_chk.setChecked(bool(s.get("minimize_to_tray", True)))
        self.tray_close_chk = QCheckBox("با دکمه‌ی بستن (X) به System Tray برود و بسته نشود")
        self.tray_close_chk.setChecked(bool(s.get("close_to_tray", False)))
        f.addRow(self.tray_min_chk)
        f.addRow(self.tray_close_chk)
        self.mood_combo = QComboBox()
        for mood in MOODS:
            self.mood_combo.addItem(mood, mood)
        pv = QPushButton()
        self.reg(pv.setText, "preview")
        pv.clicked.connect(lambda: self.animator.set_expression(self.mood_combo.currentData(), hold=8))
        hb = QHBoxLayout()
        hb.addWidget(self.mood_combo, 1)
        hb.addWidget(pv)
        lab = QLabel()
        self.reg(lab.setText, "mood_preview")
        f.addRow(lab, hb)
        btn = QPushButton()
        self.reg(btn.setText, "open_sounds")
        btn.clicked.connect(self.open_sounds)
        f.addRow(btn)
        note = QLabel()
        note.setObjectName("hint")
        note.setWordWrap(True)
        self.reg(note.setText, "char_note")
        f.addRow(note)
        subtabs = QTabWidget()
        subtabs.addTab(self.page(box), "")
        subtabs.addTab(self.build_personality_tab(), "")
        self.character_subtabs = subtabs
        self.reg(lambda text: subtabs.setTabText(0, text), "tab_characters")
        self.reg(lambda text: subtabs.setTabText(1, text), "tab_personality")
        self.tabs.addTab(self.page(subtabs), "")

    def build_personality_tab(self):
        """Baseline behavioral traits of the active character (learning may move them only inside a narrow band)."""
        box, form = self.group("g_personality_traits")
        labels = {
            "playfulness": "trait_playfulness", "warmth": "trait_warmth",
            "curiosity": "trait_curiosity", "confidence": "trait_confidence",
            "assertiveness": "trait_assertiveness", "teasing": "trait_teasing",
            "empathy": "trait_empathy", "independence": "trait_independence",
            "patience": "trait_patience", "carefulness": "trait_carefulness",
        }
        self.personality_sliders = {}
        for key, translation_key in labels.items():
            slider = QSlider(Qt.Horizontal)
            slider.setRange(0, 100)
            slider.setValue(int(round(float(BASE_TRAITS.get(key, 0.5)) * 100)))
            self.row(form, translation_key, slider)
            self.personality_sliders[key] = slider
        note = QLabel()
        note.setObjectName("hint")
        note.setWordWrap(True)
        self.reg(note.setText, "personality_hint")
        form.addRow(note)
        save = QPushButton()
        self.reg(save.setText, "character_save_traits")
        save.clicked.connect(self.save_personality_profile)
        form.addRow(save)
        self.refresh_personality_controls()
        return self.page(box)

    def refresh_personality_controls(self):
        if not getattr(self, "personality_sliders", None):
            return
        traits = self.character_traits(self.active_character().get("id", "kira")) or BASE_TRAITS
        for key, slider in self.personality_sliders.items():
            slider.blockSignals(True)
            slider.setValue(int(round(float(traits.get(key, BASE_TRAITS.get(key, 0.5))) * 100)))
            slider.blockSignals(False)

    def save_personality_profile(self, silent=False):
        profile = self.active_character()
        cid = profile.get("id", "kira")
        traits = {key: slider.value() / 100.0 for key, slider in self.personality_sliders.items()}
        try:
            self.settings.setdefault("character_traits", {})[cid] = traits
            mood.set_active_character(cid, traits)
            self.refresh_personality_controls()
            if not silent:
                self.add_chat("system", self.t("character_traits_saved", name=profile.get("name", cid)))
            return True
        except Exception as exc:                            # noqa: BLE001
            if not silent:
                QMessageBox.warning(self, self.t("character_error_title"), str(exc))
            return False

    def refresh_character_choices(self):
        current = characters.active_id(self.settings)
        self.character_combo.blockSignals(True)
        self.character_combo.clear()
        profiles = characters.all_profiles(self.settings)
        for cid in ("kira", "ren", "mika"):
            if cid in profiles:
                p = profiles[cid]
                self.character_combo.addItem(p.get("name_fa", p["name"]) + " · " + p["name"], cid)
        for cid, p in profiles.items():
            if cid not in ("kira", "ren", "mika"):
                self.character_combo.addItem(p.get("name_fa", p["name"]) + " · " + p["name"], cid)
        self.character_combo.setCurrentIndex(max(0, self.character_combo.findData(current)))
        self.character_combo.blockSignals(False)
        self.character_edit_btn.setEnabled(current != "kira")
        self.character_delete_btn.setEnabled(current != "kira")

    def refresh_character_card(self, character_id=None):
        profile = characters.all_profiles(self.settings).get(character_id or characters.active_id(self.settings), characters.CHARACTERS["kira"])
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
        self.character_portrait.setPixmap(pixmap)
        self.character_description.setText(profile.get("description", ""))

    def _fit_portrait(self, pixmap):
        """Fill the portrait frame without stretching: pictures whose proportions differ from the frame are
        cropped (centred, biased toward the face). A picture that already fits (Kira's SVG) is left untouched."""
        if pixmap.isNull():
            return pixmap
        size = self.character_portrait.size()
        if abs(pixmap.width() / pixmap.height() - size.width() / size.height()) < 0.03:
            return pixmap
        x, y, w, h = avatar_art.cover_crop(pixmap.width(), pixmap.height(), size.width(), size.height())
        crop = pixmap.copy(int(round(x)), int(round(y)), int(round(w)), int(round(h)))
        return crop.scaled(size, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)

    def apply_character_art(self):
        """Chat page + floating companion show the active character: Kira's own animated PNG, or the character's
        full-body picture (a profile without one falls back to Kira's art). Called at start-up and on every change."""
        profile = characters.active(self.settings)
        self.animator.set_character_art(characters.avatar_file(profile, ROOT))
        self.animator.rig.intensity = float(self.settings.get("motion_strength", self.animator.rig.intensity)) * self.animator.motion_gain
        self.animator.touch()

    def select_character(self, index):
        character_id = self.character_combo.itemData(index)
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
        self.sync_sessions()                           # a new tab with its own conversation
        self.switch_session(cid)
        self.save_now()

    def edit_character(self):
        cid = characters.active_id(self.settings)
        if cid == "kira":
            return
        profile = dict(characters.all_profiles(self.settings)[cid])
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
        cid = characters.active_id(self.settings)
        if cid == "kira":
            return
        if QMessageBox.question(self, "حذف شخصیت", "این شخصیت حذف شود؟") != QMessageBox.Yes:
            return
        if cid in characters.CHARACTERS:
            hidden = self.settings.setdefault("deleted_character_ids", [])
            if cid not in hidden:
                hidden.append(cid)
        else:
            self.settings["characters"] = [x for x in self.settings.get("characters", []) if x.get("id") != cid]
        self.settings["active_character_id"] = "kira"
        self.sync_sessions()                           # its tab (and conversation view) goes away
        self.switch_session("kira")
        self.save_now()

    def build_general_tab(self):
        box1, f1 = self.group("g_lang")
        self.ui_lang = self.row(f1, "ui_lang", QComboBox())
        self.ui_lang.addItem("فارسی", "fa")
        self.ui_lang.addItem("English", "en")
        self.ui_lang.setCurrentIndex(0 if self.settings.get("ui_lang", "fa") == "fa" else 1)
        self.window_effect = QComboBox()
        for label, value in (("شیشه‌ای (Acrylic)", "acrylic"), ("شیشه‌ای ملایم (Mica)", "mica"), ("ساده (تیره)", "off")):
            self.window_effect.addItem(label, value)
        self.window_effect.setCurrentIndex(max(0, self.window_effect.findData(self.settings.get("window_effect", "acrylic"))))
        if not winfx.supported():
            self.window_effect.setEnabled(False)
            self.window_effect.setToolTip("حالت شیشه‌ای فقط روی Windows 11 (نسخه‌ی 22H2 به بالا) کار می‌کند.")
        f1.addRow("ظاهر پنجره", self.window_effect)
        self.tavily_key = QLineEdit(self.settings.get("tavily_api_key", ""))
        self.tavily_key.setEchoMode(QLineEdit.Password)
        self.tavily_key.setPlaceholderText("tvly-…  (رایگان از tavily.com)")
        self.tavily_key.setLayoutDirection(Qt.LeftToRight)
        f1.addRow("کلید جست‌وجوی وب (Tavily)", self.tavily_key)
        self.web_depth = QComboBox()
        for value, label in websearch.DEPTHS.items():
            self.web_depth.addItem(label, value)
        self.web_depth.setCurrentIndex(max(0, self.web_depth.findData(self.settings.get("web_depth", "basic"))))
        self.web_depth.setToolTip("«دقیق» دو برابر اعتبار مصرف می‌کند ولی برای چیزهای سخت مثل نام آهنگ و خواننده بهتر است.")
        f1.addRow("عمق جست‌وجو", self.web_depth)
        self.web_fallback_chk = QCheckBox("اگر Tavily کار نکرد، با Google (Gemini) و بعد DuckDuckGo جست‌وجو کن")
        self.web_fallback_chk.setChecked(bool(self.settings.get("web_fallback", True)))
        f1.addRow(self.web_fallback_chk)
        self.web_test_btn = QPushButton("آزمایش جست‌وجوی وب")
        self.web_test_btn.clicked.connect(self.test_web_search)
        f1.addRow("", self.web_test_btn)
        box2, f2 = self.group("g_memory")
        btn = QPushButton()
        self.reg(btn.setText, "clear_mem")
        btn.clicked.connect(self.clear_chat)
        f2.addRow(btn)
        self.restore_chat_btn = QPushButton("بازگرداندن آخرین پاک‌سازی")
        self.restore_chat_btn.clicked.connect(self.restore_cleared_chat)
        f2.addRow(self.restore_chat_btn)
        self.memory_btn = QPushButton("حافظه‌ی Kira درباره‌ی تو: مشاهده، ویرایش و حذف…")
        self.memory_btn.clicked.connect(self.open_memory_dialog)
        f2.addRow(self.memory_btn)
        self.import_chat_btn = QPushButton("ورود گفتگو از نسخه‌ی قدیمی…")
        self.import_chat_btn.clicked.connect(lambda: self.import_old_chat())
        f2.addRow(self.import_chat_btn)
        # About (mandatory version metadata: Version, Gregorian build date, 24h build time, detected developer)
        box3, f3 = self.group("g_about")
        self.about_labels = {}
        for key, value in about.about_rows(VERSION):
            label = QLabel(value)
            label.setObjectName(key)
            label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            self.about_labels[key] = self.row(f3, key, label)
        subtabs = QTabWidget()
        subtabs.addTab(self.page(box1, box2, box3), "")
        subtabs.addTab(self.build_help_tab(), "")
        self.general_subtabs = subtabs
        self.reg(lambda text: subtabs.setTabText(0, text), "tab_preferences")
        self.reg(lambda text: subtabs.setTabText(1, text), "tab_help")
        self.tabs.addTab(self.page(subtabs), "")

    def build_help_tab(self):
        """Guide, troubleshooting, changelog and project links (the About metadata stays in Preferences)."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 8, 8, 8)
        update_box, update_form = self.group("g_help_updates")
        version_label = QLabel(f"{APP_NAME} · {VERSION}")
        version_label.setObjectName("title")
        update_form.addRow(version_label)
        description = QLabel()
        description.setWordWrap(True)
        self.reg(description.setText, "help_description")
        update_form.addRow(description)
        latest_btn = QPushButton()
        repo_btn = QPushButton()
        guide_btn = QPushButton()
        troubleshoot_btn = QPushButton()
        changes_btn = QPushButton()
        data_btn = QPushButton()
        self.reg(latest_btn.setText, "help_latest")
        self.reg(repo_btn.setText, "help_repository")
        self.reg(guide_btn.setText, "help_guide")
        self.reg(troubleshoot_btn.setText, "help_troubleshooting")
        self.reg(changes_btn.setText, "help_changes")
        self.reg(data_btn.setText, "help_data")
        latest_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(RELEASES_URL)))
        repo_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(PROJECT_URL)))
        guide_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(PROJECT_URL + "/blob/main/docs/USAGE_FA.md")))
        troubleshoot_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(PROJECT_URL + "/blob/main/docs/WINDOWS11_CHECKLIST_FA.md")))
        changes_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(PROJECT_URL + "/commits/main")))
        data_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(PROJECT_URL + "/blob/main/docs/CHARACTER_PROFILES_FA.md")))
        for button in (latest_btn, repo_btn, guide_btn, troubleshoot_btn, changes_btn, data_btn):
            update_form.addRow(button)
        about_box, about_form = self.group("g_help_about")
        about_label = QLabel()
        about_label.setWordWrap(True)
        self.reg(about_label.setText, "help_about_text")
        about_form.addRow(about_label)
        layout.addWidget(update_box)
        layout.addWidget(about_box)
        layout.addStretch(1)
        return self.page(page)

    def build_ai_tab(self):
        """Route Manager: ordered list of routes (drag & drop), per-route editor, providers (keys), benchmark."""
        page = QWidget()
        root_layout = QVBoxLayout(page)
        intro = QLabel("هر Route یک مدل است که از طریق یک Provider در دسترس است. ترتیب فهرست همان اولویت و ترتیب Failover است "
                       "(با کشیدن و رها کردن یا ▲▼ جابه‌جا کن). تغییرات همین‌جا خودکار ذخیره می‌شوند. تست و Benchmark ممکن است از سهمیه API مصرف کنند.")
        intro.setWordWrap(True)
        intro.setObjectName("hint")
        root_layout.addWidget(intro)
        # --- API Manager (replaces the per-provider boxes: Groq / Mistral / Google / Cloudflare are registered by key)
        for box in self.build_api_boxes():
            root_layout.addWidget(box)
        # --- routes list
        rbox, rform = self.group("Routeها (مدل‌ها و اولویت اجرا)")
        self.route_list = QListWidget()
        self.route_list.setMinimumHeight(190)
        self.route_list.setDragDropMode(QAbstractItemView.InternalMove)
        self.route_list.setDefaultDropAction(Qt.MoveAction)
        self.route_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.route_list.currentItemChanged.connect(lambda *_: self.on_route_selected())
        self.route_list.model().rowsMoved.connect(lambda *_: self.on_routes_reordered())
        rform.addRow(self.route_list)
        self.route_manual_lbl = QLabel()
        self.route_manual_lbl.setObjectName("hint")
        rform.addRow(self.route_manual_lbl)
        self.failover_chk = QCheckBox("Failover: اگر مسیر انتخاب‌شده خراب بود، به Route بعدی برو")
        self.failover_chk.setChecked(bool(self.settings.get("failover_enabled", True)))
        self.failover_chk.toggled.connect(self.on_failover_toggled)
        rform.addRow(self.failover_chk)
        b1 = QHBoxLayout()
        self.route_up_btn = QPushButton("▲")
        self.route_down_btn = QPushButton("▼")
        self.route_add_btn = QPushButton("افزودن Route")
        self.route_del_btn = QPushButton("حذف")
        self.route_default_btn = QPushButton("پیش‌فرض")
        self.route_use_btn = QPushButton("استفاده‌ی دستی")
        self.route_auto_btn = QPushButton("خودکار")
        self.route_up_btn.clicked.connect(lambda: self.move_selected(-1))
        self.route_down_btn.clicked.connect(lambda: self.move_selected(1))
        self.route_add_btn.clicked.connect(self.add_route_dialog)
        self.route_del_btn.clicked.connect(self.delete_selected_route)
        self.route_default_btn.clicked.connect(self.default_selected_route)
        self.route_use_btn.clicked.connect(lambda: self.select_route(self._selected_route_id() or ""))
        self.route_auto_btn.clicked.connect(lambda: self.select_route(""))
        for w in (self.route_up_btn, self.route_down_btn, self.route_add_btn, self.route_del_btn, self.route_default_btn,
                  self.route_use_btn, self.route_auto_btn):
            b1.addWidget(w)
        rform.addRow(b1)
        # --- selected route editor
        ebox, eform = self.group("تنظیمات Route انتخاب‌شده")
        self.route_provider_lbl = QLabel("-")
        eform.addRow("Provider", self.route_provider_lbl)
        self.route_model_edit = ModelCombo("")
        eform.addRow("Model ID", self.route_model_edit)
        self.route_enabled_chk = QCheckBox("فعال (غیرفعال کردن موقت، بدون حذف تنظیمات)")
        eform.addRow(self.route_enabled_chk)
        self.route_timeout = QSpinBox()
        self.route_timeout.setRange(5, 600)
        self.route_timeout.setSuffix(" s")
        eform.addRow("Timeout", self.route_timeout)
        self.route_cooldown = QSpinBox()
        self.route_cooldown.setRange(0, 3600)
        self.route_cooldown.setSuffix(" s")
        eform.addRow("Cooldown بعد از خطا", self.route_cooldown)
        self.route_ctx = QSpinBox()
        self.route_ctx.setRange(0, 32768)
        self.route_ctx.setSingleStep(1024)
        self.route_ctx.setSpecialValueText("پیش‌فرض Provider")
        self.route_predict = QSpinBox()
        self.route_predict.setRange(0, 4096)
        self.route_predict.setSingleStep(64)
        self.route_predict.setSpecialValueText("پیش‌فرض Provider")
        eform.addRow("Context (فقط Ollama)", self.route_ctx)
        eform.addRow("Num Predict (فقط Ollama)", self.route_predict)
        self.route_status = QLabel("Route‌ای انتخاب نشده.")
        self.route_status.setWordWrap(True)
        eform.addRow(self.route_status)
        b2 = QHBoxLayout()
        self.route_test_btn = QPushButton("تست اتصال")
        self.route_scan_btn = QPushButton("یافتن مدل‌های Ollama")
        self.route_bench_btn = QPushButton("Benchmark این Route")
        self.route_bench_all_btn = QPushButton("Benchmark همه‌ی فعال‌ها")
        self.route_test_btn.clicked.connect(self.test_selected_route)
        self.route_scan_btn.clicked.connect(self.scan_ollama)
        self.route_bench_btn.clicked.connect(lambda: self.run_benchmark(False))
        self.route_bench_all_btn.clicked.connect(lambda: self.run_benchmark(True))
        for w in (self.route_test_btn, self.route_scan_btn, self.route_bench_btn, self.route_bench_all_btn):
            b2.addWidget(w)
        eform.addRow(b2)
        self.bench_out = QTextEdit()
        self.bench_out.setReadOnly(True)
        self.bench_out.setMinimumHeight(110)
        self.bench_out.setLayoutDirection(Qt.LeftToRight)
        self.bench_out.setPlaceholderText("نتیجه‌ی Benchmark اینجا نمایش داده می‌شود (Routeها یکی‌یکی و نه هم‌زمان تست می‌شوند).")
        eform.addRow(self.bench_out)
        for w in (self.route_enabled_chk,):
            w.toggled.connect(lambda *_: self.route_edit_changed())
        for w in (self.route_timeout, self.route_cooldown, self.route_ctx, self.route_predict):
            w.valueChanged.connect(lambda *_: self.route_edit_changed())
        self.route_model_edit.lineEdit().editingFinished.connect(self.route_edit_changed)
        self.route_model_edit.activated.connect(lambda *_: self.route_edit_changed())
        root_layout.addWidget(rbox)
        root_layout.addWidget(ebox)
        root_layout.addWidget(self.build_local_model_group())
        root_layout.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(page)
        # The Route section has two views that work the same way (Providers, keys, enable / disable, status, priority, fallback):
        # chat models and voice (Cloud Voice). Their settings stay separate: a voice model is never a chat route.
        container = QWidget()
        cbox = QVBoxLayout(container)
        cbox.setContentsMargins(0, 0, 0, 0)
        cbox.setSpacing(6)
        switch = QHBoxLayout()
        switch.setContentsMargins(8, 6, 8, 0)
        self.route_view_chat_btn = QPushButton()
        self.route_view_voice_btn = QPushButton()
        for b in (self.route_view_chat_btn, self.route_view_voice_btn):
            b.setCheckable(True)
            switch.addWidget(b)
        switch.addStretch(1)
        self.reg(self.route_view_chat_btn.setText, "route_view_chat")
        self.reg(self.route_view_voice_btn.setText, "route_view_voice")
        self.route_stack = QStackedWidget()
        self.route_stack.addWidget(scroll)
        self.route_stack.addWidget(self.build_cloud_voice_tab())
        self.route_view_chat_btn.clicked.connect(lambda: self.set_route_view(0))
        self.route_view_voice_btn.clicked.connect(lambda: self.set_route_view(1))
        cbox.addLayout(switch)
        cbox.addWidget(self.route_stack, 1)
        self.set_route_view(0)
        self.tabs.addTab(container, "")
        self.refresh_route_list()
        self.refresh_api_table()

    def build_local_model_group(self):
        """Backwards-compatible name for the Route local-provider group."""
        return self.build_ollama_group()

    def build_ollama_group(self):
        """Local Ollama provider: enable switch + Edit for its address (Local Model settings stay exactly as before)."""
        local_cfg = self.settings.get("providers", {}).get("ollama", {})
        lg, lf = self.group("Ollama · Local")
        self.route_ollama_enabled = QCheckBox("فعال بودن Provider محلی Ollama")
        self.route_ollama_enabled.setChecked(bool(local_cfg.get("enabled", True)))
        self.route_ollama_enabled.toggled.connect(lambda *_: self.provider_changed())
        lf.addRow(self.route_ollama_enabled)
        self.ollama_url_edit = QLineEdit(self.settings.get("ollama_url", "http://localhost:11434"))
        self.ollama_url_edit.setReadOnly(True)
        lf.addRow("Base URL", self.ollama_url_edit)
        self.ollama_edit_btn, self.ollama_save_btn, self.ollama_cancel_btn = QPushButton("Edit"), QPushButton("ذخیره"), QPushButton("Cancel")
        self.ollama_save_btn.hide()
        self.ollama_cancel_btn.hide()
        oline = QHBoxLayout()
        for b in (self.ollama_edit_btn, self.ollama_save_btn, self.ollama_cancel_btn):
            oline.addWidget(b)
        lf.addRow(oline)
        self.ollama_edit_btn.clicked.connect(lambda: self.ollama_edit_mode(True))
        self.ollama_cancel_btn.clicked.connect(lambda: self.ollama_edit_mode(False))
        self.ollama_save_btn.clicked.connect(self.save_ollama_edit)
        note = QLabel("Context، Keep-alive و Num Predict پیش‌فرض Ollama در تب «دستیار» است؛ هر Route محلی می‌تواند Context/Num Predict خودش را هم داشته باشد. مدل‌های نصب‌شده را با «یافتن مدل‌های Ollama» بالای صفحه بیاور.")
        note.setObjectName("hint")
        note.setWordWrap(True)
        lf.addRow(note)
        return lg

    def collect_provider_settings(self):
        """Only the local Ollama switch lives in the form now; API keys / enabled flags are changed by the API Manager actions directly."""
        self.settings.setdefault("providers", {}).setdefault("ollama", {})["enabled"] = self.route_ollama_enabled.isChecked()
        route_model.ensure_routes(self.settings)

    def ollama_edit_mode(self, on):
        self.ollama_url_edit.setReadOnly(not on)
        self.ollama_edit_btn.setVisible(not on)
        self.ollama_save_btn.setVisible(on)
        self.ollama_cancel_btn.setVisible(on)
        if not on:
            self.ollama_url_edit.setText(self.settings.get("ollama_url", "http://localhost:11434"))

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
        """Add API + Registered APIs + details of the selected API. Returns the three group boxes."""
        add_box, af = self.group("Add API")
        hint = QLabel("فقط API Key را وارد کن؛ Kira خودش سرویس را (Groq، Mistral، Google AI Studio یا Cloudflare) از روی پاسخ رسمی آن تشخیص می‌دهد، "
                      "کلید را اعتبارسنجی می‌کند و مدل‌های قابل‌دسترسی را می‌گیرد. اگر سرویس با قطعیت شناسایی نشود، چیزی ثبت نمی‌شود.")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        af.addRow(hint)
        self.api_key_edit = QLineEdit()
        self.api_key_edit.setEchoMode(QLineEdit.Password)
        self.api_key_edit.setPlaceholderText("API Key")
        self.api_key_edit.setLayoutDirection(Qt.LeftToRight)
        self.api_account_edit = QLineEdit()
        self.api_account_edit.setPlaceholderText("Cloudflare Account ID (فقط اگر خواسته شد)")
        self.api_account_edit.setLayoutDirection(Qt.LeftToRight)
        self.api_add_btn = QPushButton("Add")
        line = QHBoxLayout()
        line.addWidget(self.api_key_edit, 1)
        line.addWidget(self.api_add_btn)
        af.addRow(line)
        af.addRow(self.api_account_edit)
        self.api_add_status = QLabel("")
        self.api_add_status.setWordWrap(True)
        af.addRow(self.api_add_status)
        self.api_add_btn.clicked.connect(self.api_add)
        self.api_key_edit.returnPressed.connect(self.api_add)

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
    def api_add(self):
        if self._api_busy():
            return
        key = self.api_key_edit.text().strip()
        account = self.api_account_edit.text().strip()
        problem = api_manager.key_problem(key)
        dup = api_manager.find_duplicate(self.settings, key) if not problem else ""
        if problem or dup:
            self.api_add_status.setText("✕ " + (problem or f"این کلید قبلاً به‌عنوان «{route_model.provider_label(dup, self.settings['providers'][dup])}» ثبت شده است."))
            return
        self.api_add_btn.setEnabled(False)
        self.api_add_status.setText("در حال شناسایی سرویس و اعتبارسنجی…")
        self._api_worker = TaskWorker(lambda: api_manager.detect(key, account))
        self._api_worker.done.connect(lambda result, k=key: self.on_api_detected(result, k))
        self._api_worker.start()

    def on_api_detected(self, result, key):
        self.api_add_btn.setEnabled(True)
        ok, det = result
        if not ok:
            self.api_add_status.setText("✕ " + str(det))
            return
        if not det.ok:
            self.api_add_status.setText(api_manager.describe_failure(det))
            if det.state == "needs_account":
                self.api_account_edit.setFocus()
            return
        try:
            pid = api_manager.register(self.settings, det, key)
        except ValueError as exc:
            self.api_add_status.setText("✕ " + str(exc))
            return
        self.api_key_edit.clear()
        self.api_account_edit.clear()
        label = route_model.provider_label(pid, self.settings["providers"][pid])
        self.api_add_status.setText(f"✓ {label} شناسایی و ثبت شد · {len(det.models)} مدل قابل‌دسترسی پیدا شد. مدل‌های دلخواه را در جزئیات فعال کن.")
        self._api_changed(pid)

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
        QApplication.instance().setStyleSheet(build_style(new))
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
            "speak_replies": self.speak_chk.isChecked(), "stream_speech": self.stream_chk.isChecked(),
            "voice_fa": self.voice_fa.currentText().strip() or EDGE_FA[0],
            "voice_en": self.voice_en.currentText().strip() or EDGE_EN[0],
            "voice_ja": self.voice_ja.currentText().strip() or EDGE_JA[0],
            "voice_rate": self.rate.value(), "voice_pitch": self.pitch.value(),
            "voice_volume": self.volume.value() / 100.0,
            "voice_style": self.voice_style.currentData() or "", "voice_style_degree": self.voice_style_deg.value(),
            "output_device": self.out_device.currentData() or "", "mic_device": self.mic_device.currentData() or "",
            "mic_gain": self.mic_gain.value(),
            "stt_language": self.stt_lang.currentText(), "whisper_model": self.whisper.currentText().strip() or "small",
            "wake_timeout": self.wake_timeout.value(),
            "mic_sensitivity": self.mic_sens.value(), "barge_in": self.barge_chk.isChecked(),
            "companion_height": self.size_sl.value(),
            "follow_strength": self.follow_sl.value() / 100.0,
            "motion_strength": self.motion_sl.value() / 100.0,
            "click_reactions": self.react_chk.isChecked(), "idle_talk": self.idle_chk.isChecked(), "always_on_top": self.top_chk.isChecked(),
            "minimize_to_tray": self.tray_min_chk.isChecked(), "close_to_tray": self.tray_close_chk.isChecked(),
            "ui_lang": self.ui_lang.currentData(),
            "window_effect": self.window_effect.currentData(),
            "tavily_api_key": self.tavily_key.text().strip(),
            "web_depth": self.web_depth.currentData(),
            "web_fallback": self.web_fallback_chk.isChecked(),
        })
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
        self.update_window_effect(s["window_effect"])
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

    def test_voice(self, voice, lang):
        # use the values currently shown in the form, without saving them yet
        self.settings.update({"voice_fa": self.voice_fa.currentText(), "voice_en": self.voice_en.currentText(),
                              "voice_ja": self.voice_ja.currentText(), "voice_rate": self.rate.value(),
                              "voice_pitch": self.pitch.value(), "voice_volume": self.volume.value() / 100.0,
                              "voice_style": self.voice_style.currentData() or "", "voice_style_degree": self.voice_style_deg.value(),
                              "output_device": self.out_device.currentData() or ""})
        self.animator.set_expression("happy", hold=3)
        self.speaker.speak(TEST_LINES[lang])

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
        self.attach_err.setText("\n".join(str(m) for m in messages))
        self.attach_err_widget.setVisible(bool(messages))
        self.attach_err_close.setVisible(bool(messages))

    def cancel_attachments(self):
        """Cancel pending file reads; when idle, the same control only dismisses the error."""
        worker = getattr(self, "_attach_worker", None)
        if worker is not None and worker.isRunning():
            for index in range(len(getattr(self, "_load_tiles", []))):
                worker.cancel(index)
            for tile in list(self._tiles):
                self.remove_attachment_tile(tile)
        self.show_attach_error([])

    # -- choosing files --
    def attach_loading(self):
        worker = getattr(self, "_attach_worker", None)
        return worker is not None and worker.isRunning()

    def add_attachment_paths(self, paths):
        """Each chosen file becomes a card with a thumbnail and its own percentage while it is read in a worker thread."""
        if self.attach_loading():
            self.show_attach_error(["صبر کن؛ ضمیمه‌های قبلی هنوز در حال بارگذاری‌اند."])
            return
        paths = list(paths)
        room = att.MAX_FILES - len(self._tiles)
        errors = []
        if len(paths) > room:
            errors.append(f"حداکثر {att.MAX_FILES} ضمیمه برای هر پیام.")
            paths = paths[:max(0, room)]
        self.show_attach_error(errors)
        if not paths:
            return
        self._load_tiles = []
        for path in paths:
            tile = AttachmentTile(Path(path).name)
            tile.removeRequested.connect(self.remove_attachment_tile)
            tile.set_progress(0)
            self._tiles.append(tile)
            self._load_tiles.append(tile)
            self.strip_add(self.attach_strip, tile)
        self._attach_worker = AttachWorker(paths)
        self._attach_worker.progress.connect(self.on_attach_progress)
        self._attach_worker.loaded.connect(self.on_attach_loaded)
        self._attach_worker.failed.connect(self.on_attach_failed)
        self._attach_worker.finished.connect(lambda: self.send_btn.setEnabled(not self.busy))
        self._attach_worker.finished.connect(self.on_attach_finished)
        self.send_btn.setEnabled(False)
        self.attach_err.setText("در حال بارگذاری ضمیمه‌ها؛ برای لغو روی ضربدر بزن.")
        self.attach_err_close.setVisible(True)
        self.attach_err_widget.show()
        self._attach_worker.start()

    def on_attach_progress(self, index, percent):
        tile = self._load_tiles[index] if index < len(self._load_tiles) else None
        if tile is not None and not tile.deleted:
            tile.set_progress(percent)

    def on_attach_finished(self):
        if self.attach_err.text().startswith("در حال بارگذاری"):
            self.show_attach_error([])

    def on_attach_loaded(self, index, attachment):
        tile = self._load_tiles[index] if index < len(self._load_tiles) else None
        if tile is not None and not tile.deleted:
            tile.set_attachment(attachment)
            tile.set_progress(100)

    def on_attach_failed(self, index, message):
        tile = self._load_tiles[index] if index < len(self._load_tiles) else None
        if tile is not None and not tile.deleted:
            self.remove_attachment_tile(tile)
        self.show_attach_error([message])

    def add_pasted_image(self, image):
        try:
            from PySide6.QtCore import QBuffer, QIODevice
            if len(self._tiles) >= att.MAX_FILES:
                raise att.AttachmentError(f"حداکثر {att.MAX_FILES} ضمیمه برای هر پیام.")
            buf = QBuffer()
            buf.open(QIODevice.WriteOnly)
            image.save(buf, "PNG")
            self._att_seq += 1
            attachment = att.image_attachment(bytes(buf.data()), f"clipboard-{self._att_seq}.png")
        except (att.AttachmentError, AttributeError) as exc:
            self.show_attach_error([str(exc)])
            return
        tile = AttachmentTile(attachment["name"])
        tile.removeRequested.connect(self.remove_attachment_tile)
        tile.set_attachment(attachment)
        self._tiles.append(tile)
        self.strip_add(self.attach_strip, tile)
        self.show_attach_error([])

    def remove_attachment_tile(self, tile):
        tile.deleted = True
        worker = getattr(self, "_attach_worker", None)
        if worker is not None and worker.isRunning():
            try:
                worker.cancel(self._load_tiles.index(tile))
            except (ValueError, AttributeError):
                pass
        if tile in self._tiles:
            self._tiles.remove(tile)
        self.strip_remove(self.attach_strip, tile)

    def clear_attachments(self):
        for tile in list(self._tiles):
            self.remove_attachment_tile(tile)
        self.show_attach_error([])

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
        self.game_mode.set_enabled(enabled and vision_allowed)
        safe_profile = enabled and self._game_mode_profile == COMPETITIVE_SAFE_MODE
        self.tool_agent.set_competitive_safe_mode(safe_profile)
        # Safe mode does not keep polling foreground process metadata while an online game is running.
        if safe_profile:
            self._game_poll_timer.stop()
        elif not self._game_poll_timer.isActive():
            self._game_poll_timer.start()

        if enabled:
            if not was_enabled:
                self._game_prev_mic = self.mic_btn.isChecked()
                self._game_prev_wake = self.wake_btn.isChecked()
            if not self.wake_btn.isChecked():
                self.wake_btn.setChecked(True)
                self.toggle_wake()
            if vision_allowed:
                self._capture_game_frame()
                self._game_capture_timer.start()
            else:
                self._game_capture_timer.stop()
                self._latest_game_frame = None
            if audio_allowed:
                self._start_game_audio_listener()
            else:
                self._stop_game_audio_listener()
        else:
            self._game_capture_timer.stop()
            self._latest_game_frame = None
            worker = getattr(self, "_vision_worker", None)
            if worker is not None and worker.isRunning():
                worker.cancel_request()
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
            self._vision_worker = VisionAnalysisWorker(self.client, image)
            self._vision_worker.done.connect(self._on_game_vision_result)
            self._vision_worker.start()
        except Exception as exc:  # noqa: BLE001 - vision must never interrupt the game/chat
            self.add_chat("system", f"Vision: آماده‌سازی فریم ناموفق بود: {str(exc)[:180]}")

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

    def submit(self, text, attachments=None):
        voice, self._voice_next = self._voice_next, False
        if self.busy and not attachments:
            try:
                control = self.tool_agent.control_running(text)        # "وضعیت / توقف / لغو کار / مرحله اضافه کن" act between two steps of a running task
            except Exception:                                      # noqa: BLE001 - never block typing
                control = None
            if control:
                self.add_chat("system", control)
                return
        if self.busy:
            # Policy: typing never blocks. A message sent while an answer is being generated waits in a small queue
            # (max 3) and is sent automatically, in order, when the current answer ends.
            if len(self._pending) < 3:
                self._pending.append((text, attachments))
                self.status.setText(f"پیام در صف است ({len(self._pending)}) — بعد از پایان پاسخ فعلی ارسال می‌شود.")
            return
        if not attachments and getattr(self, "code_chat", None) is not None and self.code_chat.handle(text, voice):
            return                                              # Kira's chat: coding missions / project questions (decided from the wording)
        if self._game_mode_enabled and len(attachments or []) < att.MAX_FILES:
            frame = self._game_vision_attachment()
            if frame is not None:
                attachments = list(attachments or []) + [frame]
        self._turn_voice = voice
        if self.speaker._began:
            self.director.event("user_interrupt")
        self.safe_stop_speaker()
        self.animator.touch()
        self._body_done = []
        try:
            self.run_body(body_ctl.parse_user_command(text))            # "raise your hand" / "پشتتو کن": moves at once, before the model answers
        except Exception:                                      # noqa: BLE001
            pass
        force_img = False
        if attachments and any(a.get("kind") == "image" for a in attachments):
            text, force_img = websearch.image_command(text)              # '/img ...' or '/عکس ...' = search this picture even if the switch is off
        img_search = bool(attachments and any(a.get("kind") == "image" for a in attachments)
                          and (force_img or self.settings.get("image_search", False)))
        packed = att.compose(text, attachments, search=img_search) if attachments else None
        self._turn_extra = packed
        self._turn_attach_kinds = [str(a.get("kind")) for a in (attachments or [])]       # structured kinds: Active Mode must not guess from display text
        self.add_chat("user", packed["display"] if packed else text, images=attachments if packed else None)
        self.tool_agent.begin_turn()
        action_result = None
        if not packed:
            action_result = usage.handle_command(text)                                 # "/usage [days]": numbers from the local ledger, no model call
            if action_result is not None:
                pass
            elif self.tool_agent.enabled():
                action_result = self.tool_agent.handle_confirmation_reply(text)       # "تأیید" / "لغو" for a pending sensitive action: decided in code, not by the model
                if action_result is None:
                    action_result = self.tool_agent.handle_task_command(text)         # status / pause / cancel / add a step of an unfinished task: decided in code too
            else:
                action_result = run_safe_action(text)                                  # tools switched off (tools_mode = off): the old fixed shortcuts
        self._tool_plan = None if action_result else self.tool_agent.plan(text)
        self.save_message("user", packed["stored"] if packed else text)
        if action_result:
            self.reply_local(action_result)
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
            self.begin_image_search(text, packed["model"], packed["images"])
            return
        query, forced = websearch.plan(text) if self.settings.get("web_search", True) or text.lstrip().startswith("/") else (None, False)
        if query and not forced and self._tool_plan is not None and self._tool_plan.strong:
            query = None                                          # a request about this PC (files, apps, RAM...) is not a web question
        if query and not forced and self._tool_plan is not None and getattr(self._tool_plan, "web", False):
            query = None                                          # research / "read this page" requests go through the web tools (kira/webintel), not the one-shot search
        if query:
            self.begin_web_search(query, packed["model"] if packed else text, packed["images"] if packed else [])
            return
        self.begin_reply()

    def begin_reply(self):
        try:
            self.start_worker(plain=False)
        except Exception as exc:                                  # noqa: BLE001 - never leave the window stuck in 'busy'
            self._stream_timer.stop()
            self.add_chat("error", self.t("reply_err", e=f"{type(exc).__name__}: {exc}"))
            self.finish_request(None)
            self.set_badge("error")

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
        history = conversation_context(8, character_id=self.cur.cid)
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
            self._turn_extra = {"model": base + "\n\n" + websearch.format_block(result), "images": images}
            self.status.setText(f"{'🔎 Google' if result.get('engine') == 'google' else ('🦆 DuckDuckGo' if result.get('engine') == 'ddg' else '🌐 Tavily')}: {len(result['results'])} منبع پیدا شد؛ در حال پاسخ دادن…")
        elif getattr(self, "_image_search_turn", False):
            # the picture itself is still in the request: she answers from what she sees and says what is unconfirmed
            self.add_chat("system", f"🔎 جست‌وجوی تصویری انجام نشد: {result}")
            base, images = self._search_base
            self._turn_extra = {"model": base + "\n\n[جست‌وجوی وب برای این تصویر انجام نشد. فقط از روی چیزی که در تصویر می‌بینی جواب بده، "
                                                 "حدس نزن و هر چیزی که مطمئن نیستی را صریح «تأییدنشده» بگو.]", "images": images}
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
        context = conversation_context(window, character_id=self.cur.cid)
        mode = self.detect_mode(context)                          # Active Mode of THIS message (None = switched off in settings)
        try:
            older = recent_messages(window + 40, self.cur.cid)[:-window] if window else []
            # Every character has its own saved conversation; only Kira owns the legacy evidence index.
            character_id = self.cur.cid
            with persona_memory.character_scope(character_id):
                memory_block = persona_memory.build_block(
                    older, voice_samples=(mode is None or mode.name == modes.CHAT),
                    query=evidence_memory.query_from_context(context) if character_id == "kira" else None,
                    budget=evidence_memory.budget_for(self.settings, self.client),
                )
                total = message_count(character_id)
                if persona_memory.needs_summary(total, window):
                    persona_memory.maintain(recent_messages(min(total, 3000), character_id), window)
        except Exception:                                         # noqa: BLE001 - memory is a bonus, never block a reply
            memory_block = ""
        try:                                                      # her persisted mood + how he seems right now (same text for every provider)
            mood_block = mood.build_block(mode.name if mode else modes.CHAT)
        except Exception:                                         # noqa: BLE001
            mood_block = ""
        prompt = build_system_prompt(self.settings, "" if plain else self.director.format_hint(), memory_block,
                                     voice_input=self._turn_voice, mode=mode, mood_block=mood_block,
                                     character_profile=self.active_character())
        # The selected character changes identity and conversational style only; all shared tools and policies stay intact.
        character_layer = characters.prompt_for(self.settings)
        if character_layer:
            prompt += "\n\n" + character_layer
        if self.body_active():                                    # she can move her 3D body: tell the model how (tags) and what the app already did
            prompt += ("" if plain else body_ctl.format_hint()) + body_ctl.done_note(self._body_done)
        try:                                                      # brain stage: deterministic, no model call; any problem = the normal path
            extra0 = self._turn_extra
            has_att = bool(self._turn_attach_kinds or (extra0 and (extra0.get("images") or "--- فایل ضمیمه" in str(extra0.get("model", "")))))
            last_user = next((m.get("content", "") for m in reversed(context) if m.get("role") == "user"), "")
            self._brain_user_text = str(last_user)
            self._brain_mode_name = mode.name if mode else None
            self._brain = brain.decide(last_user, mode, self._tool_plan, has_att, self.tool_agent.tasks.active() is not None, self.settings)
            prompt = brain.extend_prompt(prompt, self._brain, self.settings, self.client)
        except Exception:                                         # noqa: BLE001
            self._brain = brain.Decision()
        self._stream_begin()
        extra = self._turn_extra
        if extra and context and context[-1]["role"] == "user":          # this turn gets the full file text and the real images
            context[-1] = {"role": "user", "content": extra["model"], "images": extra["images"]}
        temperature = modes.temperature_for(mode, self.settings["temperature"]) if mode else self.settings["temperature"]
        self.worker = StreamWorker(self.client, context, prompt, temperature, retry_index=1 if plain else 0,
                                   agent=self.tool_agent, plan=self._tool_plan, role=self._brain.stage,
                                   route_id=self._brain.route_id)
        relay = self.cur.relay
        self.worker.tool_event.connect(relay.tool)
        self.worker.event.connect(relay.stream_event)
        self.worker.chunk.connect(relay.chunk)
        self.worker.finished_ok.connect(relay.done)
        self.worker.failed.connect(relay.failed)
        self.worker.start()
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
                longer = [m["content"] for m in recent_messages(80, self.cur.cid) if m.get("role") == "user"]
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
            return                                                # a running Ai1 Code command was killed; its handler ends the turn
        if self._search_worker is not None and self._search_worker.isRunning():
            self._search_token += 1                                   # the late search result is ignored
            self.add_chat("system", "جست‌وجو متوقف شد.")
            self.finish_request(None)
            self._send_next_pending()
            return
        if not any(o.busy for o in self.sessions.values() if o is not self.cur):
            self.tool_agent.request_cancel()                      # also stops a tool loop between two steps (the tool agent is shared:
                                                                  # not while another character is in the middle of its own task)
        self.client.cancel()                                      # this chat's own router: the other characters keep answering
        self.gen_stop_btn.setEnabled(False)

    # ---- body control (the 3D body moves on chat commands: kira/body.py) ----
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
        self._partial_saved = False
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

    def on_stream_chunk(self, piece):
        self._stream_text += piece
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
        name = characters.display_name(self.settings)
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
        self._stream_flush(final=True)
        self._stream_pos = None
        self.bubble.commit_live()
        self.finish_request(res)
        if res.get("stopped"):
            if text.strip():
                self.save_message("assistant", raw)
            self.add_chat("system", "تولید پاسخ متوقف شد." + (" متن دریافت‌شده نگه داشته شد." if text.strip() else ""))
            if self._speech_live:
                self.safe_stop_speaker()                           # the Stop button also silences the rest of the spoken reply
            self.animator.set_expression("neutral", hold=2)
        elif res.get("interrupted"):
            self.save_message("assistant", raw)
            self.add_chat("error", f"ارتباط وسط پاسخ قطع شد؛ بخش دریافت‌شده نگه داشته شد و تکرار نمی‌شود.\n{res['interrupted']}")
            if self._speech_live:
                self.speaker.stream_end()                          # what arrived is still spoken to its end
            self.director.event("response_failed")
        elif not text.strip():
            self.add_chat("error", self.t("empty"))
            self.director.event("response_failed")
        else:
            self.save_message("assistant", raw)
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

    def _send_next_pending(self):
        if self._pending and not self.busy:
            nxt = self._pending.pop(0)
            QTimer.singleShot(0, lambda t=nxt, sess=self.cur: self._submit_for(sess, t))

    def _submit_for(self, session, args):
        if session.cid in self.sessions:
            with self._as(session):
                self.submit(*args)

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
        self.animator.set_expression(expression, hold=4)
        self.say(text)

    def save_message(self, role, content):
        """Save to the chat database. A failure never blocks the chat: the text stays in memory and the person is told once."""
        try:
            ok = add_message(role, content, self.cur.cid)
        except Exception as exc:                                  # noqa: BLE001
            ok = False
            chat_store.last_error = f"{type(exc).__name__}: {exc}"
        with persona_memory.character_scope(self.cur.cid):
            persona_memory.observe(role, content)
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
        if ok:
            self._save_warned = False
        elif not self._save_warned:
            self._save_warned = True
            self.add_chat("error", "ذخیره‌ی گفتگو روی دیسک ناموفق بود. گفتگو تا بسته‌شدن برنامه در حافظه می‌ماند و با اولین ذخیره‌ی موفق نوشته می‌شود."
                                   f"\nعلت: {chat_store.last_error}")
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
        for w in (self.voice_btn, self.speak_chk):
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
        if self._game_mode_enabled and not self.mic_btn.isChecked():
            self.mic_btn.setChecked(True)
            return
        if self.mic_btn.isChecked():
            self.start_listener()
        else:
            if self.wake_btn.isChecked():
                self.wake_btn.setChecked(False)
                self.toggle_wake()
            self.stop_listener()

    def start_listener(self):
        self.stop_listener()
        self.listener = Listener(self.settings["whisper_model"], self.settings["stt_language"], self,
                                 sensitivity=self.settings.get("mic_sensitivity", 100), barge_in=self.settings.get("barge_in", True),
                                 settings=self.settings)
        self.listener.heard.connect(self.on_heard)
        self.listener.interrupted.connect(self.on_user_barge_in)
        self.listener.state.connect(self.on_listener_state)
        self.listener.error.connect(self.on_listener_error)
        self.listener.note.connect(self.on_cloud_note)
        self.listener.start()

    def stop_listener(self):
        if self.listener:
            self.listener.stop()
            self.listener = None
        self.set_status("st_ready")
        self.update_engine_label()

    def on_listener_error(self, msg):
        self.add_chat("error", msg)
        self.mic_btn.setChecked(False)
        self.listener = None

    def on_listener_state(self, state):
        if state == "listening":
            self.update_engine_label()
            self.set_status("st_sleeping" if (self.wake_btn.isChecked() and not self.awake) else "st_listening")
        else:
            self.set_status({"loading": "st_loading", "hearing": "st_hearing", "transcribing": "st_transcribing"}.get(state, "st_ready"))

    def update_engine_label(self):
        eng = getattr(self.listener, "engine", None) if self.listener else None
        via = getattr(self.listener, "via", "") if self.listener else ""
        if via.startswith("cloud:"):
            self.engine_lbl.setText(f"{self.t('engine_cloud')} · {cloud_voice.LABELS.get(via[6:], via[6:])}")
        elif not eng and self.listener and cloud_voice.service().stt_ready():
            self.engine_lbl.setText(self.t("engine_cloud"))
        else:
            self.engine_lbl.setText(self.t({"whisper": "engine_whisper", "google": "engine_google"}.get(eng, "engine_none")))

    def toggle_wake(self):
        if self._game_mode_enabled and not self.wake_btn.isChecked():
            self.wake_btn.setChecked(True)
            self.go_sleep()
            return
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
        if self.busy:
            return
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

    def closeEvent(self, event):
        if (getattr(self, "tray", None) is not None and self.settings.get("close_to_tray")
                and not getattr(self, "_quitting", False)):
            event.ignore()                                           # X only hides; "Exit" in the tray menu really quits
            self.hide_to_tray()
            return
        for sess in list(self.sessions.values()):
            with self._as(sess):
                if self.busy and not self._bench_busy and self._stream_text.strip() and not self._partial_saved:
                    self._partial_saved = True
                    self.save_message("assistant", self._stream_text)      # the half answer that was already on screen is not lost
        self._closing = True
        if getattr(self, "code_chat", None) is not None:
            self.code_chat.shutdown()
        if getattr(self, "tray", None) is not None:
            self.tray.hide()
        self.bubble.close()
        self.tool_agent.request_cancel()
        for sess in self.sessions.values():
            if sess.client is not None:
                sess.client.cancel()
            if sess.timer is not None:
                sess.timer.stop()
        self._game_poll_timer.stop()
        self._game_capture_timer.stop()
        self._latest_game_frame = None
        vision_worker = getattr(self, "_vision_worker", None)
        if vision_worker is not None and vision_worker.isRunning():
            vision_worker.cancel_request()
        self._stop_game_audio_listener()
        self.game_mode.set_enabled(False)
        for sess in self.sessions.values():
            for w in (sess.worker, sess._search_worker):
                if w is not None and w.isRunning():
                    w.wait(3000)
        for name in ("_route_worker", "_bench_worker", "_scan_worker", "_provider_test_worker", "_ollama_worker", "_vision_worker"):
            w = getattr(self, name, None)
            if w is not None and w.isRunning():
                w.wait(5000)
        self.stop_listener()
        self.safe_stop_speaker()
        self.companion.close()
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
        who = characters.display_name(self.settings)
        question = (f"تاریخچه‌ی گفتگوی «{who}» پاک شود؟ (گفتگوی بقیه‌ی کاراکترها دست‌نخورده می‌ماند)"
                    if self.settings.get("ui_lang", "fa") == "fa" else f"Delete the saved history of {who}? (the other characters' chats stay)")
        if QMessageBox.question(self, self.t("clear_t"), question) == QMessageBox.Yes:
            try:
                clear_memory(self.cur.cid)      # only THIS character's conversation; saves a snapshot first, nothing is deleted if that fails
                # Facts, moments and habits remain in the character's own memory file.
                with persona_memory.character_scope(self.cur.cid):
                    persona_memory.forget_conversation()
                self.tool_agent.clear_tasks()   # the unfinished task (its goal is the user's own words) goes with the chat
                brain.reset_state()
            except ChatStoreError as exc:
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
        MemoryDialog(self, characters.active_id(self.settings)).exec()

    def restore_cleared_chat(self):
        try:
            n = chat_store.restore_last_cleared()
        except ChatStoreError as exc:
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
            n = chat_store.import_messages(path)
        except ChatStoreError as exc:
            QMessageBox.warning(self, "ورود گفتگو", str(exc))
            return
        self.reload_chat_view()
        self.add_chat("system", f"{n} پیام از فایل قدیمی وارد شد." if n else "پیام جدیدی در آن فایل نبود (همه از قبل وجود داشتند).")

    @staticmethod
    def html(s):
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br>")


def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(build_style(winfx.active_effect(load_settings().get("window_effect"))))
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
