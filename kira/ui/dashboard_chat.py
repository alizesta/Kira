"""Chat surfaces of the dashboard skin: message bubbles, the "Today" chip, header icons, the composer pill, the typing box and the portrait card.

Companion of chat_shell (which builds the three columns). Same rules: widgets that already exist are moved, never recreated;
every step is independent and logged on failure; controller methods that would overwrite the skin are wrapped on the controller
INSTANCE only.

* Bubbles: the session module's `message_html` is replaced by a version that draws the reference bubbles (avatar next to the
  assistant, time under the text, double tick under the user's). Qt rich text cannot round a table, so the bubble tables are
  transparent and a painter behind the text (_BubbleUnderlay, an event filter on the chat viewport) draws the rounded shapes; the
  table's cellpadding (11 = user, 12 = assistant) tells it which bubble it is looking at. Messages restored from history carry no
  time, because their real time is unknown here.
* Composer: one pill [✦][input][emoji][attach][stop][send]. The old toolbar (route chip, search, Eye Mode, microphone, voice,
  expand editor) is moved into a tray that the ✦ button opens, so no feature is lost.
* Typing box: "<name> is typing..." above the composer while the front chat is thinking.
* Portrait: assets/dashboard/<character id>_portrait.png. A character without that file keeps the animated avatar. Kira's own
  portrait (assets/dashboard/kira_portrait.jpg) belongs to chat_shell; when it exists this module never touches the avatar's
  visibility for a character without a PNG, so the two cannot fight.
* News panel: the compact news panel is hidden on this page (the reference has none); the News page in Settings is unchanged.
* Column widths follow the window like the reference (left 16.6 %, right 25.7 %).
"""
from __future__ import annotations

import re
import logging
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QRectF, QSize, QTimer, QUrl, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QTextDocument, QTextTable
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QScrollArea, QToolButton, QWidget

from .. import chat_render
from ..config import ROOT
from ..ui_icons import make_icon

_LOG = logging.getLogger("kira.ui")
AVATAR_URL = "kira-avatar://self"
USER_BUBBLE, ASSISTANT_BUBBLE, BUBBLE_BORDER = "#1f1445", "#171034", "#2b1b57"
USER_PAD, ASSISTANT_PAD = 11, 12                       # cellpadding of the bubble tables: how the underlay tells them apart
BUBBLE_RADIUS = 16
TEXT, META, TICKS = "#f1ecff", "#8f7bc0", "#8b5cf6"
AVATAR_SIZE = 52
LEFT_RATIO, RIGHT_RATIO = 0.166, 0.257                 # column widths of the reference (255 and 395 of 1536 px)

STYLE = """
QFrame#chatInputSurface { background: rgba(18, 10, 38, 190); border: 1px solid #6d4bc2; border-radius: 26px; min-height: 62px; }
QWidget#composerTray { background: transparent; }
QToolButton#sparkBtn { background: #1a1038; border: 2px solid #5b2fd6; border-radius: 22px; color: #c4a6ff; font-size: 18px;
    min-width: 40px; max-width: 40px; min-height: 40px; max-height: 40px; }
QToolButton#sparkBtn:checked { background: #3b2380; color: #ffffff; }
QToolButton#emojiBtn { background: transparent; border: none; color: #cbbcff; font-size: 20px; }
QToolButton#sendBtn:hover { background: rgba(139, 92, 246, 0.22); border-color: #c4b5fd; }
QToolButton#sendBtn { background: rgba(139, 92, 246, 0.14); border: 2px solid #9b7aff;
    border-radius: 22px; min-width: 44px; max-width: 44px; min-height: 44px; max-height: 44px; }
QLabel#todayChip { background: #150c2e; border: 1px solid #2a1a52; border-radius: 12px; color: #cbbcff; padding: 4px 16px; }
QToolButton#headerIcon { background: transparent; border: none; color: #cbbcff; font-size: 16px; padding: 4px; }
QFrame#dashTyping { background: #120a26; border: 1px solid #2a1a52; border-radius: 14px; margin: 4px 14px; }
QLabel#dashTypingText { color: #b9a3f5; font-size: 13px; }
QPushButton#dashSettings { background: transparent; border: 1px solid #2a1b55; border-radius: 12px; color: #c4b5fd; text-align: left; padding: 0 14px; }
QPushButton#dashSettings:hover { background: #170d33; }
QPushButton#navItem { font-size: 15px; font-weight: 400; }
QLabel#dashGreeting { font-size: 28px; }
QFrame#statCard { min-height: 112px; }
QLabel#statValue { font-size: 17px; }
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


def _character_name(context, fallback="Kira") -> str:
    try:
        return str(context.services.character_service.display_name(context.services.settings))
    except Exception:                                        # noqa: BLE001
        return fallback


# ---------------------------------------------------------------- bubbles

def clock_text(moment: datetime | str) -> str:
    if isinstance(moment, str):
        value = moment.strip()
        if not value:
            return ""
        try:
            moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return ""
    if moment.tzinfo is not None:
        moment = moment.astimezone()
    return moment.strftime("%I:%M %p").lstrip("0")


def bubble_html(kind, text, ui_dir, extra_html="", footer_html="", stamp="", avatar_url="") -> str:
    """User and assistant bubbles of the reference design. The tables are transparent: _BubbleUnderlay paints the rounded shapes."""
    body = chat_render.rich_body_html(text, TEXT, ui_dir) if str(text or "").strip() else ""
    ticks = f' <span style="color:{TICKS};">✓✓</span>' if (kind == "user" and stamp) else ""
    stamp_html = f'<span style="color:#c4b5fd;font-size:9pt;font-weight:600;">{stamp}{ticks}</span>' if stamp else ""
    # one row under the text: the time on the left, the action icons completely on the right
    if footer_html or stamp_html:
        cells = re.search(r"<tr>(.*)</tr>", footer_html or "", re.S)
        icons = cells.group(1) if cells else ""
        meta = (f'<table width="100%" cellspacing="0" cellpadding="0" style="margin-top:7px; direction:ltr;"><tr>'
                f'<td align="left" valign="middle" style="white-space:nowrap;">{stamp_html}</td><td width="100%">&nbsp;&nbsp;</td>{icons}</tr></table>')
    else:
        meta = ""
    cell = f"{extra_html}{body}{meta}"
    spacer = '<p style="margin:0;font-size:3pt;">&nbsp;</p>'
    if kind == "user":
        return (f'<table width="100%" cellspacing="0" cellpadding="0" style="margin:7px 0;"><tr><td align="right">'
                f'<table align="right" cellspacing="0" cellpadding="{USER_PAD}">'
                f'<tr><td>{cell}</td></tr></table></td></tr></table>{spacer}')
    avatar = (f'<td width="{AVATAR_SIZE + 10}" valign="top"><img src="{avatar_url}" width="{AVATAR_SIZE}" height="{AVATAR_SIZE}"></td>'
              if avatar_url else "")
    return (f'<table width="100%" cellspacing="0" cellpadding="0" style="margin:7px 0;"><tr>{avatar}'
            f'<td valign="top"><table cellspacing="0" cellpadding="{ASSISTANT_PAD}">'
            f'<tr><td>{cell}</td></tr></table></td></tr></table>{spacer}')


def _bubble_tables(frame):
    """Every bubble table of a QTextDocument frame tree (nested ones too)."""
    for child in frame.childFrames():
        if isinstance(child, QTextTable) and round(child.format().cellPadding()) in (USER_PAD, ASSISTANT_PAD):
            yield child
        yield from _bubble_tables(child)


BUBBLE_PAD_X, BUBBLE_PAD_TOP, BUBBLE_PAD_BOTTOM = 16, 14, 10


def _content_rect(document, layout, table):
    """Union of the text blocks inside one bubble table: the bubble is drawn around what is really there."""
    block = document.findBlock(table.firstPosition())
    end = table.lastPosition()
    rect = None
    while block.isValid() and block.position() <= end:
        part = layout.blockBoundingRect(block)
        if part.height() > 0:
            rect = part if rect is None else rect.united(part)
        block = block.next()
    return rect


class _BubbleUnderlay(QObject):
    """Paints the rounded bubble shapes behind the text of one chat view (QTextBrowser), on every repaint."""

    def __init__(self, view) -> None:
        super().__init__(view.viewport())
        self._view = view
        view.viewport().installEventFilter(self)

    def eventFilter(self, obj, event):                       # noqa: N802 - Qt API
        if event.type() == QEvent.Paint and obj is self._view.viewport():
            try:
                self._paint()
            except Exception:                                # noqa: BLE001 - without the underlay the text is still readable
                _LOG.debug("Could not paint the bubble shapes", exc_info=True)
        return False

    def _paint(self) -> None:
        view = self._view
        viewport = view.viewport()
        layout = view.document().documentLayout()
        dx, dy = -view.horizontalScrollBar().value(), -view.verticalScrollBar().value()
        visible = QRectF(viewport.rect())
        painter = QPainter(viewport)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(QColor(BUBBLE_BORDER), 1))
        for table in _bubble_tables(view.document().rootFrame()):
            frame = layout.frameBoundingRect(table)
            rect = _content_rect(view.document(), layout, table)
            if rect is None:
                rect = frame
            else:                                            # block rects are as wide as the line box; the table knows the real width
                rect = QRectF(rect.left(), rect.top(), frame.width() - 2 * table.format().cellPadding(), rect.height())
            rect = rect.adjusted(-BUBBLE_PAD_X, -BUBBLE_PAD_TOP, BUBBLE_PAD_X, BUBBLE_PAD_BOTTOM).translated(dx, dy)
            if not rect.intersects(visible):
                continue
            painter.setBrush(QColor(USER_BUBBLE if round(table.format().cellPadding()) == USER_PAD else ASSISTANT_BUBBLE))
            painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), BUBBLE_RADIUS, BUBBLE_RADIUS)
        painter.end()


def _install_underlay(view) -> None:
    if getattr(view, "_kira_underlay", None) is None:
        view._kira_underlay = _BubbleUnderlay(view)
        view.document().setDocumentMargin(16)               # room so the rounded corners are not cut by the view edge


def _install_bubbles(controller) -> None:
    from . import main_window_session as session_module     # add_chat looks message_html up in this module at call time
    original = session_module.message_html
    if getattr(original, "_kira_dashboard", False):
        return

    def wrapped(kind, name, text, ui_dir="rtl", extra_html="", footer_html="", accent=None):
        if kind not in ("user", "assistant"):
            return original(kind, name, text, ui_dir, extra_html, footer_html, accent)
        restoring = bool(getattr(controller, "_suppress_conversation_refresh", False))   # set while history is painted
        if restoring:
            stamp = clock_text(getattr(controller, "_history_message_created_at", "") or "")
        else:
            stamp = clock_text(datetime.now())
        return bubble_html(kind, text, ui_dir, extra_html, footer_html, stamp, AVATAR_URL if kind == "assistant" else "")

    wrapped._kira_dashboard = True
    session_module.message_html = wrapped


def _avatar_for_view(context, session) -> None:
    _soon, character_pixmap = _shell_helpers()
    view = getattr(session, "view", None)
    if view is None:
        return
    pixmap = character_pixmap(context, session.cid, 2 * AVATAR_SIZE)
    if pixmap is None:                                       # no picture: a purple disc, so the <img> is never broken
        pixmap = QPixmap(2 * AVATAR_SIZE, 2 * AVATAR_SIZE)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(QColor("#3b2380"))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(0, 0, pixmap.width(), pixmap.height())
        painter.end()
    view.document().addResource(QTextDocument.ImageResource, QUrl(AVATAR_URL), pixmap)
    _install_underlay(view)


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
    header.setLayoutDirection(Qt.LeftToRight)                # same icon order in Persian and English
    title.hide()                                             # the reference header has no title; setText keeps working
    chip = QLabel("امروز" if lang == "fa" else "Today", header)
    chip.setObjectName("todayChip")
    layout.insertStretch(0, 1)
    layout.insertWidget(1, chip)
    layout.insertStretch(2, 1)
    _add_model_chip(context, header, layout)
    for icon in ("search", "sliders"):                       # search and filter of the reference, as neon icons (display only)
        button = _display_tool(context, lang, "", "headerIcon", header)
        button.setIcon(make_icon(icon, normal="#b9a2ff", hover="#ffffff"))
        button.setIconSize(QSize(22, 22))
        layout.addWidget(button)


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
    spark.setIcon(make_icon("eye", normal="#c4b5fd", hover="#ffffff", checked="#ffffff"))   # Eye Vision
    spark.setIconSize(QSize(22, 22))
    spark.setCheckable(True)
    spark.setCursor(Qt.PointingHandCursor)
    spark.setFocusPolicy(Qt.NoFocus)
    spark.setToolTip("ابزارها" if lang == "fa" else "Tools")
    emoji = _display_tool(context, lang, "", "emojiBtn", surface)
    emoji.setIcon(make_icon("smile", normal="#b18aff", hover="#ffffff"))
    emoji.setIconSize(QSize(24, 24))

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
    if send is not None:                                     # neon send button: white neon plane on a glowing violet disc
        send.setIcon(make_icon("send_centered", normal="#c4a6ff", hover="#ffffff", disabled="#62558a"))
        send.setIconSize(QSize(26, 26))
        send.setStyleSheet("QToolButton { background: rgba(139,92,246,0.14); border: 1px solid #8b6de0; border-radius: 22px; } QToolButton:hover { background: rgba(167,139,250,0.28); border-color: #d8c8ff; }")
    if attach is not None:
        attach.setIcon(make_icon("paperclip", normal="#c4a6ff", hover="#ffffff", disabled="#62558a"))
        attach.setIconSize(QSize(21, 21))
        attach.setStyleSheet("QToolButton { color: #c4a6ff; background: rgba(139,92,246,0.10); border: 1px solid rgba(139,92,246,0.42); border-radius: 18px; } QToolButton:hover { background: rgba(167,139,250,0.24); border-color: #c4a6ff; }")
    for widget in (attach, stop, send):
        _detach(bar, widget)
        if widget is not None:
            pill.addWidget(widget)
    layout.insertLayout(0, pill)
    layout.addWidget(tray)


# ---------------------------------------------------------------- typing box

class _Typing(QFrame):
    """Three pulsing dots and "<name> is typing..." above the composer."""

    def __init__(self, text: str, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("dashTyping")
        row = QHBoxLayout(self)
        row.setContentsMargins(12, 6, 12, 6)
        row.setSpacing(8)
        self._dots = QLabel(self)
        self._text = QLabel(text, self)
        self._text.setObjectName("dashTypingText")
        row.addWidget(self._dots)
        row.addWidget(self._text)
        row.addStretch(1)
        self._phase = 0
        self._timer = QTimer(self)
        self._timer.setInterval(380)
        self._timer.timeout.connect(self._tick)
        self.hide()

    def _tick(self) -> None:
        self._phase = (self._phase + 1) % 3
        self._dots.setText(" ".join(
            f'<span style="color:{"#a855f7" if i == self._phase else "#4b2bb8"};">●</span>' for i in range(3)))

    def set_active(self, active: bool) -> None:
        if active:
            if not self._timer.isActive():
                self._phase = -1
                self._tick()
                self._timer.start()
            self.show()
        else:
            self._timer.stop()
            self.hide()


def _build_typing(context, lang, parts) -> None:
    composer = getattr(context.views, "chat_composer", None)
    host = composer.parentWidget() if composer is not None else None
    layout = host.layout() if host is not None else None
    if layout is None:
        return
    name = _character_name(context)
    typing = _Typing(f"{name} در حال نوشتن است…" if lang == "fa" else f"{name} is typing…", host)
    layout.insertWidget(layout.indexOf(composer), typing)
    parts["typing"] = typing


def _wrap_status(context, controller, parts) -> None:
    original = getattr(controller, "set_status", None)
    typing = parts.get("typing")
    if not callable(original) or typing is None:
        return

    def status(key, **kwargs):
        result = original(key, **kwargs)
        state = getattr(context, "state", None)
        if getattr(state, "cur", None) is getattr(state, "front", None):      # same rule as @front_only
            typing.set_active(key == "st_thinking")
        return result

    controller.set_status = status


# ---------------------------------------------------------------- news panel

class _HideGuard(QObject):
    """Keeps one widget hidden even when its owner calls show() again."""

    def __init__(self, widget) -> None:
        super().__init__(widget)
        self._widget = widget
        widget.installEventFilter(self)

    def eventFilter(self, obj, event):                       # noqa: N802 - Qt API
        if obj is self._widget and event.type() == QEvent.Show:
            QTimer.singleShot(0, self._widget.hide)
        return False


def _hide_news(context) -> None:
    card = getattr(context.views, "avatar_card", None)
    if card is None:
        return
    for child in card.children():
        if isinstance(child, QWidget) and "news" in type(child).__name__.lower():
            child.hide()
            _HideGuard(child)


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
    has_picture = portrait.show_character(cid, _character_name(context, cid.capitalize()))
    portrait.setVisible(has_picture)
    avatar = getattr(context.views, "avatar", None)
    if avatar is None:
        return
    shell_portrait = getattr(getattr(context.views, "avatar_card", None), "kira_portrait", None)
    if has_picture:
        avatar.setVisible(False)                             # this character has a PNG portrait: it replaces the animated avatar
    elif shell_portrait is None:
        avatar.setVisible(True)                              # no picture at all: keep the animated avatar
    # else chat_shell owns the switch between Kira's JPG portrait and the other characters' animated avatar


def _build_portrait(context, parts) -> None:
    card = getattr(context.views, "avatar_card", None)
    layout = card.layout() if card is not None else None
    if layout is None:
        return
    portrait = _Portrait(card)
    layout.insertWidget(0, portrait)
    parts["portrait"] = portrait
    _sync_portrait(context, portrait)


# ---------------------------------------------------------------- column widths

def _fit_columns(context) -> None:
    """The reference's proportions: left column 16.6 % and right column 25.7 % of the window (never below a usable size)."""
    width = int(context.host.width())
    if width < 640:                                          # the session controller hides the character panel below this
        return
    card = getattr(context.views, "avatar_card", None)
    if card is not None and not card.isHidden():
        card.setFixedWidth(max(280, min(440, round(width * RIGHT_RATIO))))
    page = getattr(context.views, "chat_page", None)
    left = page.findChild(QScrollArea, "dashLeftScroll") if page is not None else None
    if left is not None:
        left.setFixedWidth(max(220, min(280, round(width * LEFT_RATIO))))


def _wrap_resize(context, controller) -> None:
    original = getattr(controller, "resizeEvent", None)
    if not callable(original):
        return

    def resized(event):
        result = original(event)                             # sets the old 200-300 px width; the reference proportions follow
        try:
            _fit_columns(context)
        except Exception:                                    # noqa: BLE001 - keep the old widths when this fails
            _LOG.debug("Could not fit the dashboard columns", exc_info=True)
        return result

    controller.resizeEvent = resized
    _fit_columns(context)


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


def _add_model_chip(context, header, layout) -> None:
    """The current model/route stays visible on the main page: a chip in the chat header opens the same route menu as the tray."""
    views = context.views
    badge = getattr(views, "route_badge", None)
    if badge is None:
        return
    chip = QToolButton(header)
    chip.setObjectName("modelChip")
    chip.setCursor(Qt.ArrowCursor)
    chip.setFocusPolicy(Qt.NoFocus)
    chip.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
    chip.setIcon(make_icon("sparkle", normal="#c4a6ff", hover="#ffffff"))
    chip.setIconSize(QSize(14, 14))
    chip.setMaximumWidth(240)
    chip.setStyleSheet("QToolButton#modelChip { color: #d9ccff; background: rgba(139,92,246,0.12); border: 1px solid #5b3fb0; border-radius: 14px; padding: 4px 12px; font-size: 12px; }"
                       "QToolButton#modelChip:hover { background: rgba(167,139,250,0.26); border-color: #c4b5fd; }"
                       "QToolButton#modelChip::menu-indicator { image: none; }")

    def sync() -> None:
        text = str(badge.text() or "").replace("●", "").strip()
        chip.setText(text or "Model")
        chip.setToolTip(badge.toolTip())

    sync()
    timer = QTimer(chip)
    timer.setInterval(1500)
    timer.timeout.connect(sync)
    timer.start()
    layout.addWidget(chip)


def _pin_violet_icons(context) -> None:
    """Keep the chat page's icon buttons violet: the theme refresh recolours every `kiraIconName` button with the character's cyan accent."""
    page = getattr(getattr(context, "views", None), "chat_page", None)
    if page is None:
        return
    for button in page.findChildren(QToolButton):
        name = button.property("kiraIconName")
        if not name:
            continue
        button.setIcon(make_icon(str(name), normal="#c4a6ff", hover="#ffffff", checked="#ffffff", disabled="#62558a"))
        button.setProperty("kiraIconName", None)


def _left_align_text(context) -> None:
    """Persian labels in the dashboard chrome stay on the left (absolute); only the chat text and the composer follow the text direction."""
    page = getattr(getattr(context, "views", None), "chat_page", None)
    if page is None:
        return
    for label in page.findChildren(QLabel):
        if label.objectName() in ("dashBrandSub", "dashGreeting", "dashGreetingSub", "dashSection", "dashName", "dashOnline",
                                  "dashQuoteText", "conversationListTitle", "statTitle", "statValue", "statSub",
                                  "dashTrackTitle", "dashTrackSub"):
            label.setAlignment(Qt.AlignLeft | Qt.AlignAbsolute | Qt.AlignVCenter)


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
        ("news panel", lambda: _hide_news(context)),
        ("typing box", lambda: _build_typing(context, lang, parts)),
        ("typing follows status", lambda: _wrap_status(context, controller, parts)),
        ("bubbles", lambda: _install_bubbles(controller)),
        ("avatar pictures and bubble shapes", lambda: _wrap_session_views(context, controller)),
        ("column widths", lambda: _wrap_resize(context, controller)),
        ("style survives theme changes", lambda: _wrap_theme(context, controller, page, parts)),
        ("violet icons", lambda: _pin_violet_icons(context)),
        ("left-aligned labels", lambda: _left_align_text(context)),
    )
    for name, step in steps:
        try:
            step()
        except Exception:                                    # noqa: BLE001 - a skin problem must never break the app
            _LOG.exception("Dashboard chat step %r failed", name)
    return True
