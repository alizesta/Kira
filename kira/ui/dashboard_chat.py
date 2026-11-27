"""Chat surfaces of the dashboard skin: message bubbles, the "Today" chip, header icons, the composer pill and the portrait card.

Companion of chat_shell (which builds the three columns). Same rules: widgets that already exist are moved, never recreated;
every step is independent and logged on failure; controller methods that would overwrite the skin are wrapped on the controller
INSTANCE only.

* Bubbles: the session module's `message_html` is replaced by a version that draws the reference bubbles (avatar next to the
  assistant, time under the text, double tick under the user's). Messages restored from history carry no time, because their real
  time is unknown here.
* Composer: one pill [✦][input][emoji][attach][stop][send]. The old toolbar (route chip, search, Eye Mode, microphone, voice,
  expand editor) is moved into a tray that the ✦ button opens, so no feature is lost.
* Portrait: assets/dashboard/<character id>_portrait.png. A character without that file keeps the animated avatar.
"""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QRectF, QUrl, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPixmap, QTextDocument
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QToolButton, QWidget

from .. import chat_render
from ..config import ROOT

_LOG = logging.getLogger("kira.ui")
AVATAR_URL = "kira-avatar://self"
USER_BUBBLE, ASSISTANT_BUBBLE, BUBBLE_BORDER = "#1f1445", "#171034", "#2b1b57"
TEXT, META, TICKS = "#f1ecff", "#8f7bc0", "#8b5cf6"

STYLE = """
QFrame#chatInputSurface { background: #120a26; border: 1px solid #3b2380; border-radius: 26px; }
QWidget#composerTray { background: transparent; }
QToolButton#sparkBtn { background: #1a1038; border: 2px solid #5b2fd6; border-radius: 22px; color: #c4a6ff; font-size: 18px;
    min-width: 40px; max-width: 40px; min-height: 40px; max-height: 40px; }
QToolButton#sparkBtn:checked { background: #3b2380; color: #ffffff; }
QToolButton#emojiBtn { background: transparent; border: none; color: #cbbcff; font-size: 20px; }
QToolButton#sendBtn { background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #7c3aed, stop:1 #a855f7); border: none;
    border-radius: 22px; min-width: 44px; max-width: 44px; min-height: 44px; max-height: 44px; }
QLabel#todayChip { background: #150c2e; border: 1px solid #2a1a52; border-radius: 12px; color: #cbbcff; padding: 4px 16px; }
QToolButton#headerIcon { background: transparent; border: none; color: #cbbcff; font-size: 16px; padding: 4px; }
"""


# ---------------------------------------------------------------- helpers shared with chat_shell

def _shell_helpers():
    from . import chat_shell                                 # imported lazily: chat_shell does not import this module
    return chat_shell._soon, chat_shell._character_pixmap


def _display_tool(context, lang, text, name, parent) -> QToolButton:
    soon, _pixmap = _shell_helpers()
    button = QToolButton(parent)
    button.setObjectName(name)
    button.setText(text)
    button.setAutoRaise(True)
    button.setCursor(Qt.PointingHandCursor)
    button.setFocusPolicy(Qt.NoFocus)
    button.clicked.connect(lambda checked=False: soon(context, lang))
    return button


def _session_controller(context):
    try:
        return context.controllers.require("session")
    except Exception:                                        # noqa: BLE001
        return None


# ---------------------------------------------------------------- bubbles

def clock_text(moment: datetime) -> str:
    return moment.strftime("%I:%M %p").lstrip("0")


def bubble_html(kind, text, ui_dir, extra_html="", footer_html="", stamp="", avatar_url="") -> str:
    """User and assistant bubbles of the reference design (Qt rich text: no rounded corners are possible here)."""
    body = chat_render.rich_body_html(text, TEXT, ui_dir) if str(text or "").strip() else ""
    ticks = f' <span style="color:{TICKS};">✓✓</span>' if (kind == "user" and stamp) else ""
    meta = (f'<p align="right" style="margin:3px 0 0 0;color:{META};font-size:8pt;">{stamp}{ticks}</p>' if stamp else "")
    cell = f"{extra_html}{body}{meta}{footer_html or ''}"
    spacer = '<p style="margin:0;font-size:3pt;">&nbsp;</p>'
    if kind == "user":
        return (f'<table align="right" width="72%" cellspacing="0" cellpadding="10" bgcolor="{USER_BUBBLE}" '
                f'style="margin:7px 4px;border:1px solid {BUBBLE_BORDER};"><tr><td>{cell}</td></tr></table>{spacer}')
    avatar = (f'<td width="52" valign="top"><img src="{avatar_url}" width="40" height="40"></td>' if avatar_url else "")
    return (f'<table width="100%" cellspacing="0" cellpadding="0" style="margin:7px 0;"><tr>{avatar}'
            f'<td valign="top"><table width="78%" cellspacing="0" cellpadding="10" bgcolor="{ASSISTANT_BUBBLE}" '
            f'style="border:1px solid {BUBBLE_BORDER};"><tr><td>{cell}</td></tr></table></td></tr></table>{spacer}')


def _install_bubbles(controller) -> None:
    from . import main_window_session as session_module     # add_chat looks message_html up in this module at call time
    original = session_module.message_html
    if getattr(original, "_kira_dashboard", False):
        return

    def wrapped(kind, name, text, ui_dir="rtl", extra_html="", footer_html="", accent=None):
        if kind not in ("user", "assistant"):
            return original(kind, name, text, ui_dir, extra_html, footer_html, accent)
        restoring = bool(getattr(controller, "_suppress_conversation_refresh", False))   # set while history is painted
        stamp = "" if restoring else clock_text(datetime.now())
        return bubble_html(kind, text, ui_dir, extra_html, footer_html, stamp, AVATAR_URL if kind == "assistant" else "")

    wrapped._kira_dashboard = True
    session_module.message_html = wrapped


def _avatar_for_view(context, session) -> None:
    _soon, character_pixmap = _shell_helpers()
    view = getattr(session, "view", None)
    if view is None:
        return
    pixmap = character_pixmap(context, session.cid, 80)
    if pixmap is None:                                       # no picture: a purple disc, so the <img> is never broken
        pixmap = QPixmap(80, 80)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(QColor("#3b2380"))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(0, 0, 80, 80)
        painter.end()
    view.document().addResource(QTextDocument.ImageResource, QUrl(AVATAR_URL), pixmap)


def _wrap_session_views(context, controller) -> None:
    original = getattr(controller, "_ensure_session_ui_resources", None)
    if callable(original):
        def ensured(session, profile, *args, **kwargs):
            result = original(session, profile, *args, **kwargs)
            try:
                _avatar_for_view(context, session)
            except Exception:                                # noqa: BLE001 - the avatar picture is optional
                _LOG.debug("Could not register the chat avatar", exc_info=True)
            return result

        controller._ensure_session_ui_resources = ensured
    for session in tuple(getattr(getattr(context, "state", None), "sessions", {}).values()):
        _avatar_for_view(context, session)                   # sessions created before the skin was applied


def _wrap_date_chip(context, controller, lang) -> None:
    original = getattr(controller, "add_chat", None)
    if not callable(original):
        return
    chip = ("<table align=\"center\" cellspacing=\"0\" cellpadding=\"6\" bgcolor=\"#150c2e\" style=\"margin:4px 0 8px 0;\">"
            f"<tr><td><span style=\"color:#cbbcff;\">{'امروز' if lang == 'fa' else 'Today'}</span></td></tr></table>")

    def added(kind, text, name=None, images=None):
        view = getattr(getattr(context, "session", None), "view", None)
        if view is not None and view.document().isEmpty():
            view.append(chip)                                # the first message of a conversation starts under "Today"
        return original(kind, text, name=name, images=images)

    controller.add_chat = added


# ---------------------------------------------------------------- header

def _build_header(context, lang) -> None:
    title = getattr(context.views, "title", None)
    header = title.parentWidget() if title is not None else None
    layout = header.layout() if header is not None else None
    if layout is None:
        return
    title.hide()                                             # the reference header has no title; setText keeps working
    chip = QLabel("امروز" if lang == "fa" else "Today", header)
    chip.setObjectName("todayChip")
    layout.insertStretch(0, 1)
    layout.insertWidget(1, chip)
    layout.insertStretch(2, 1)
    for glyph in ("🔍", "⚙"):
        layout.addWidget(_display_tool(context, lang, glyph, "headerIcon", header))


# ---------------------------------------------------------------- composer

def _detach(layout, widget) -> None:
    if layout is not None and widget is not None:
        layout.removeWidget(widget)


def _build_composer(context, lang) -> None:
    views = context.views
    composer = getattr(views, "chat_composer", None)
    surface = getattr(composer, "input_surface", None)
    layout = surface.layout() if surface is not None else None
    if layout is None or getattr(views, "input", None) is None:
        return
    bar = next((layout.itemAt(i).layout() for i in range(layout.count()) if layout.itemAt(i).layout() is not None), None)
    surface.setLayoutDirection(Qt.LeftToRight)               # the reference pill reads left to right: ✦ first, send last

    spark = QToolButton(surface)
    spark.setObjectName("sparkBtn")
    spark.setText("✦")
    spark.setCheckable(True)
    spark.setCursor(Qt.PointingHandCursor)
    spark.setFocusPolicy(Qt.NoFocus)
    spark.setToolTip("ابزارها" if lang == "fa" else "Tools")
    emoji = _display_tool(context, lang, "☺", "emojiBtn", surface)

    tray = QWidget(surface)
    tray.setObjectName("composerTray")
    tray_layout = QHBoxLayout(tray)
    tray_layout.setContentsMargins(4, 0, 4, 0)
    tray_layout.setSpacing(6)
    for name in ("route_badge", "search_btn", "game_mode_btn", "mic_btn", "voice_btn"):
        widget = getattr(views, name, None)
        _detach(bar, widget)
        if widget is not None:
            tray_layout.addWidget(widget)
    expand = getattr(composer, "expand_btn", None)
    expand_host = expand.parentWidget() if expand is not None else None
    if expand is not None:
        tray_layout.addWidget(expand)
    if expand_host is not None and expand_host is not surface:
        expand_host.hide()
    tray_layout.addStretch(1)
    tray.hide()
    spark.toggled.connect(tray.setVisible)

    field = views.input
    layout.removeWidget(field)
    field.setStyleSheet("background: transparent; border: none;")
    attach, stop, send = getattr(composer, "attach_btn", None), getattr(views, "gen_stop_btn", None), getattr(views, "send_btn", None)
    pill = QHBoxLayout()
    pill.setContentsMargins(6, 4, 6, 4)
    pill.setSpacing(8)
    pill.addWidget(spark)
    pill.addWidget(field, 1)
    pill.addWidget(emoji)
    for widget in (attach, stop, send):
        _detach(bar, widget)
        if widget is not None:
            pill.addWidget(widget)
    layout.insertLayout(0, pill)
    layout.addWidget(tray)


# ---------------------------------------------------------------- portrait

class _Portrait(QFrame):
    """The big picture card of the right column, with the character name over its lower edge."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("dashPortrait")
        self.setMinimumHeight(300)
        self._pixmap = QPixmap()
        self._name = ""

    def show_character(self, character_id: str, name: str) -> bool:
        path = Path(ROOT) / "assets" / "dashboard" / f"{character_id}_portrait.png"
        self._pixmap = QPixmap(str(path)) if path.is_file() else QPixmap()
        self._name = name
        self.update()
        return not self._pixmap.isNull()

    def paintEvent(self, _event) -> None:                    # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(0, 0, w, h), 20, 20)
        painter.setClipPath(clip)
        if not self._pixmap.isNull():
            scaled = self._pixmap.scaled(self.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            painter.drawPixmap((w - scaled.width()) // 2, 0, scaled)   # top-aligned: faces sit in the upper part
        fade = QLinearGradient(0, h * 0.55, 0, h)
        fade.setColorAt(0, QColor(10, 5, 25, 0))
        fade.setColorAt(1, QColor(10, 5, 25, 235))
        painter.fillRect(self.rect(), fade)
        painter.setPen(QColor("#ffffff"))
        font = painter.font()
        font.setPointSize(18)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(16, h - 40, f"{self._name} ✦")
        font.setPointSize(10)
        font.setBold(False)
        painter.setFont(font)
        painter.setPen(QColor("#b9a3f5"))
        painter.drawText(16, h - 18, "Always here for you")


def _sync_portrait(context, portrait) -> None:
    state = getattr(context, "state", None)
    session = getattr(state, "front", None) or getattr(state, "cur", None)
    cid = str(getattr(session, "cid", "") or "kira")
    try:
        name = str(context.services.character_service.display_name(context.services.settings))
    except Exception:                                        # noqa: BLE001
        name = cid.capitalize()
    has_picture = portrait.show_character(cid, name)
    portrait.setVisible(has_picture)
    avatar = getattr(context.views, "avatar", None)
    if avatar is not None:
        avatar.setVisible(not has_picture)                   # no picture for this character: keep the animated avatar


def _build_portrait(context, parts) -> None:
    card = getattr(context.views, "avatar_card", None)
    layout = card.layout() if card is not None else None
    if layout is None:
        return
    portrait = _Portrait(card)
    layout.insertWidget(0, portrait)
    parts["portrait"] = portrait
    _sync_portrait(context, portrait)


# ---------------------------------------------------------------- entry point

def _wrap_theme(context, controller, page, parts) -> None:
    original = getattr(controller, "apply_chat_theme", None)
    if not callable(original):
        return

    def themed(*args, **kwargs):
        result = original(*args, **kwargs)
        page.setStyleSheet(page.styleSheet() + STYLE)        # last, so it wins over the theme and over chat_shell's skin
        if parts.get("portrait") is not None:
            _sync_portrait(context, parts["portrait"])       # a character switch calls this: show that character's picture
        return result

    controller.apply_chat_theme = themed


def apply_dashboard_chat(context) -> bool:
    """Apply the chat surfaces once per chat page. Call after chat_shell.apply_chat_shell()."""
    views = getattr(context, "views", None)
    page = getattr(views, "chat_page", None)
    if page is None:
        return False
    if getattr(page, "_kira_dashboard_chat", False):
        return True
    page._kira_dashboard_chat = True
    settings = getattr(getattr(context, "services", None), "settings", None)
    lang = str(settings.get("ui_lang", "en")) if hasattr(settings, "get") else "en"
    controller = _session_controller(context)
    parts: dict = {}
    page.setStyleSheet(page.styleSheet() + STYLE)
    steps = (
        ("composer", lambda: _build_composer(context, lang)),
        ("header", lambda: _build_header(context, lang)),
        ("portrait", lambda: _build_portrait(context, parts)),
        ("bubbles", lambda: _install_bubbles(controller)),
        ("avatar pictures", lambda: _wrap_session_views(context, controller)),
        ("date chip", lambda: _wrap_date_chip(context, controller, lang)),
        ("style survives theme changes", lambda: _wrap_theme(context, controller, page, parts)),
    )
    for name, step in steps:
        try:
            step()
        except Exception:                                    # noqa: BLE001 - a skin problem must never break the app
            _LOG.exception("Dashboard chat step %r failed", name)
    return True
