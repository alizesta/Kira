"""Neon companion dashboard skin for the main chat page.

Layout (matches the reference design): left column = brand, navigation, profile card, Quick People (the character tabs),
conversations; centre = greeting, three stat cards, the chat card; right = the character panel (avatar, news) plus an action row,
a playlist card and a quote card.

Everything is built from the widgets VoiceSettingsController.build_chat_tab() already created (moved, never recreated, so every
signal and view reference keeps working) plus new widgets. Elements that have no feature behind them yet (Our Bond, Today's
Vibe, playlist, quote, Home/Voice Call/Memories/Gallery/Journal, Call/Voice/Surprise, the header icons) are display-only: a click
shows "coming soon" in the status line. Kira's Mood is real: it follows the mood service.

Each step is independent; a missing widget skips that step and an error is logged and leaves that part of the old layout alone.
Two controller methods overwrite what the skin sets, so they are wrapped on the controller INSTANCE (the class is untouched):
apply_chat_theme (replaces the page stylesheet), refresh_conversation_list / refresh_tab_buttons (rebuild rows and button text).
"""
from __future__ import annotations

import logging
import re
from datetime import datetime

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QBoxLayout, QButtonGroup, QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from ..config import ROOT
from ..ui_icons import make_icon

_LOG = logging.getLogger("kira.ui")
LEFT_WIDTH = 250
_STAMP = re.compile(r"\d{4}-\d{2}-\d{2} (\d{2}:\d{2})")
_ICONS = {"chat", "mic", "settings", "user"}      # names make_icon() knows; the other navigation glyphs are plain text

# key, icon name or glyph, English, Persian, tab key to open (None = display only)
NAV = (
    ("home", "⌂", "Home", "خانه", "tab_chat"),
    ("chat", "chat", "Chat", "گفتگو", "tab_chat"),
    ("call", "mic", "Voice Call", "تماس صوتی", None),
    ("memories", "♡", "Memories", "خاطرات", None),
    ("gallery", "▣", "Gallery", "گالری", None),
    ("journal", "✎", "Journal", "دفتر خاطرات", None),
    ("settings", "settings", "Settings", "تنظیمات", "tab_general"),
)

STYLE = """
QWidget#chatPage { background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #09050f, stop:1 #140a2b); }
QScrollArea#dashLeftScroll, QWidget#dashLeft { background: transparent; border: none; }
QLabel#dashBrand { color: #c4a6ff; font-size: 26px; font-weight: 800; letter-spacing: 2px; }
QLabel#dashBrandSub { color: #9a86c9; font-size: 11px; }
QPushButton#navItem { background: transparent; color: #cbbcff; border: none; border-radius: 12px; padding: 10px 14px;
    text-align: %ALIGN%; font-size: 14px; }
QPushButton#navItem:hover { background: #1a1038; }
QPushButton#navItem:checked { color: #ffffff; background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #4b2bb8, stop:1 #6d3fe0); }
QFrame#dashProfile, QFrame#dashPlaylist, QFrame#dashQuote, QFrame#statCard, QFrame#dashActions {
    background: #120a26; border: 1px solid #2a1a52; border-radius: 16px; }
QFrame#avatarCard { background: #0f0824; border: 1px solid #2a1a52; border-radius: 20px; }
QFrame#chatCard { border: 1px solid #241548; border-radius: 20px; }
QLabel#dashSection { color: #9a86c9; font-size: 12px; padding: 2px 6px; }
QLabel#dashName { color: #f4f0ff; font-size: 15px; font-weight: 600; }
QLabel#dashOnline { color: #46e08a; font-size: 11px; }
QLabel#dashQuoteText { color: #d9ccff; font-size: 13px; }
QLabel#dashHeart { color: #a855f7; font-size: 16px; }
QPushButton#charTab { background: transparent; border: none; border-radius: 12px; padding: 6px 10px; color: #e9e3ff;
    text-align: %ALIGN%; font-size: 14px; min-height: 40px; }
QPushButton#charTab:hover { background: #170d33; }
QPushButton#charTab:checked { background: #1a1038; border: 1px solid #3b2380; }
QPushButton#charAddButton { background: transparent; border: 1px dashed #3b2380; border-radius: 12px; color: #b9a3f5; }
QPushButton#charAddButton:hover { background: #170d33; }
QFrame#conversationSidebar { background: transparent; border: none; }
QFrame#conversationSidebar QPushButton#newChatButton { background: #1a1038; color: #e8ebff; border: 1px solid #3b2380;
    border-radius: 12px; padding: 8px 12px; font-weight: 600; }
QFrame#conversationSidebar QPushButton#newChatButton:hover { background: #24144d; }
QLabel#conversationListTitle { color: #9a86c9; padding: 4px 8px; font-size: 12px; }
QListWidget#conversationList { background: transparent; border: none; outline: none; }
QListWidget#conversationList::item, QListWidget#conversationList::item:hover,
QListWidget#conversationList::item:selected { padding: 0; margin: 1px 0; background: transparent; }
QWidget#conversationRow { background: transparent; border-radius: 10px; }
QWidget#conversationRow:hover { background: #170d33; }
QWidget#conversationRow[active="true"] { background: #1a1038; }
QPushButton#conversationOpenButton { background: transparent; border: none; color: #d9ccff; text-align: %ALIGN%; padding: 0 8px; }
QPushButton#conversationOpenButton:hover { color: #ffffff; }
QToolButton#conversationMenuButton { color: #9a86c9; border: none; }
QToolButton#conversationMenuButton:hover { color: #ffffff; }
QLabel#conversationTime { color: #9a86c9; font-size: 11px; padding: 0 2px; }
QLabel#conversationDot { color: #a855f7; font-size: 10px; }
QLabel#dashGreeting { color: #f4f0ff; font-size: 24px; font-weight: 600; }
QLabel#dashGreetingSub { color: #9a86c9; font-size: 13px; }
QPushButton#roundIcon { background: #150c2e; border: 1px solid #2a1a52; border-radius: 19px; color: #cbbcff;
    min-width: 38px; max-width: 38px; min-height: 38px; max-height: 38px; }
QPushButton#roundIcon:hover { background: #24144d; }
QLabel#statTitle { color: #b9a3f5; font-size: 12px; }
QLabel#statValue { color: #f4f0ff; font-size: 15px; font-weight: 600; }
QLabel#statSub { color: #8f7bc0; font-size: 11px; }
QPushButton#dashAction { background: #170d33; border: 1px solid #2a1a52; border-radius: 12px; color: #e9e3ff; padding: 8px 6px; }
QPushButton#dashAction:hover { background: #24144d; }
QLabel#dashCover { background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #5b2fd6, stop:1 #1b0f3f); border-radius: 10px; }
QLabel#dashTrackTitle { color: #f4f0ff; font-size: 13px; font-weight: 600; }
QLabel#dashTrackSub { color: #9a86c9; font-size: 11px; }
QPushButton#dashPlay { background: transparent; border: 2px solid #8b5cf6; border-radius: 17px; color: #ffffff;
    min-width: 30px; max-width: 30px; min-height: 30px; max-height: 30px; }
"""


# ---------------------------------------------------------------- small custom widgets / helpers

class _Ring(QWidget):
    """Circular progress used by the "Our Bond" card (display only)."""

    def __init__(self, percent: int, parent=None) -> None:
        super().__init__(parent)
        self._percent = max(0, min(100, int(percent)))
        self.setFixedSize(56, 56)

    def paintEvent(self, _event) -> None:                  # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(5, 5, self.width() - 10, self.height() - 10)
        painter.setPen(QPen(QColor("#2a1a52"), 5))
        painter.drawEllipse(rect)
        arc = QPen(QColor("#8b5cf6"), 5)
        arc.setCapStyle(Qt.RoundCap)
        painter.setPen(arc)
        painter.drawArc(rect, 90 * 16, -int(360 * 16 * self._percent / 100))
        painter.setPen(QColor("#f1ecff"))
        font = painter.font()
        font.setPointSize(9)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(self.rect(), Qt.AlignCenter, f"{self._percent}%")


class _Sparkline(QWidget):
    """The soft wave of the "Kira's Mood" card (decorative)."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedSize(90, 34)

    def paintEvent(self, _event) -> None:                  # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        path = QPainterPath()
        path.moveTo(0, h * 0.6)
        path.cubicTo(w * 0.25, h * 0.05, w * 0.45, h * 0.95, w * 0.6, h * 0.5)
        path.cubicTo(w * 0.75, h * 0.15, w * 0.9, h * 0.4, w, h * 0.45)
        painter.setPen(QPen(QColor("#8b5cf6"), 2))
        painter.drawPath(path)


def greeting_text(lang: str, hour: int) -> str:
    part = "morning" if 5 <= hour < 12 else "afternoon" if 12 <= hour < 17 else "evening" if 17 <= hour < 22 else "night"
    if lang == "fa":
        return {"morning": "صبح بخیر", "afternoon": "ظهر بخیر", "evening": "عصر بخیر", "night": "شب بخیر"}[part] + "، عزیزم"
    return {"morning": "Good morning", "afternoon": "Good afternoon", "evening": "Good evening", "night": "Good night"}[part] + ", darling"


def _label(text, name, parent=None) -> QLabel:
    label = QLabel(text, parent)
    label.setObjectName(name)
    return label


def _frame(name, parent=None) -> QFrame:
    frame = QFrame(parent)
    frame.setObjectName(name)
    return frame


def _character_pixmap(context, character_id, size):
    """Round avatar picture of one character, or None when it has no readable picture."""
    try:
        service = context.services.character_service
        profile = service.all_profiles(context.services.settings).get(character_id) or {}
        source = QPixmap(str(service.avatar_file(profile, ROOT)))
        if source.isNull():
            return None
        source = source.scaled(size, size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        result = QPixmap(size, size)
        result.fill(Qt.transparent)
        painter = QPainter(result)
        painter.setRenderHint(QPainter.Antialiasing)
        clip = QPainterPath()
        clip.addEllipse(0, 0, size, size)
        painter.setClipPath(clip)
        painter.drawPixmap((size - source.width()) // 2, (size - source.height()) // 2, source)
        painter.end()
        return result
    except Exception:                                      # noqa: BLE001 - a missing picture must never break the window
        _LOG.debug("No avatar picture for %s", character_id, exc_info=True)
        return None


def _soon(context, lang) -> None:
    status = getattr(getattr(context, "views", None), "status", None)
    if status is not None:
        status.setText("به‌زودی" if lang == "fa" else "Coming soon")


def _display_button(context, lang, text, name, parent) -> QPushButton:
    button = QPushButton(text, parent)
    button.setObjectName(name)
    button.setCursor(Qt.PointingHandCursor)
    button.setFocusPolicy(Qt.NoFocus)
    button.clicked.connect(lambda checked=False: _soon(context, lang))
    return button


# ---------------------------------------------------------------- entry point

def apply_chat_shell(context) -> bool:
    """Apply the skin once per chat page. Returns False when the chat page is not built (yet)."""
    views = getattr(context, "views", None)
    page = getattr(views, "chat_page", None)
    avatar_card = getattr(views, "avatar_card", None)
    conversation_list = getattr(views, "conversation_list", None)
    if page is None or avatar_card is None or conversation_list is None:
        return False
    if getattr(page, "_kira_chat_shell", False):
        return True
    page._kira_chat_shell = True                          # set first: a half-applied skin must never be applied twice
    settings = getattr(getattr(context, "services", None), "settings", None)
    if not hasattr(settings, "get"):
        settings = {}
    lang = str(settings.get("ui_lang", "en"))
    style = STYLE.replace("%ALIGN%", "right" if lang == "fa" else "left")
    if not page.objectName():
        page.setObjectName("chatPage")
    page.setStyleSheet(page.styleSheet() + style)
    controller = _session_controller(context)
    parts = {}
    steps = (
        ("layout", lambda: _build_layout(context, controller, parts, lang)),
        ("right column", lambda: _build_right(avatar_card, context, lang)),
        ("avatar side", lambda: _avatar_on_the_right(page, avatar_card, lang)),
        ("style survives theme changes", lambda: _wrap_theme(controller, page, style)),
        ("character pictures", lambda: _wrap_tabs(context, controller)),
        ("conversation rows", lambda: _wrap_rows(controller, conversation_list)),
        ("mood card", lambda: _wrap_mood(context, controller, parts)),
    )
    for name, step in steps:
        try:
            step()
        except Exception:                                  # noqa: BLE001 - a skin problem must never break the app
            _LOG.exception("Chat shell step %r failed", name)
    return True


def _session_controller(context):
    try:
        return context.controllers.require("session")
    except Exception:                                      # noqa: BLE001
        return None


# ---------------------------------------------------------------- layout

def _build_layout(context, controller, parts, lang) -> None:
    views = context.views
    page = views.chat_page
    sidebar = views.conversation_list.parentWidget()
    area = sidebar.parentWidget() if sidebar is not None else None
    area_layout = area.layout() if area is not None else None
    if area_layout is None:
        return
    chat_card = next((area_layout.itemAt(i).widget() for i in range(area_layout.count())
                      if area_layout.itemAt(i).widget() not in (None, sidebar)), None)
    if chat_card is None:
        return
    rtl = Qt.RightToLeft if lang == "fa" else Qt.LeftToRight
    area_layout.removeWidget(sidebar)
    area_layout.removeWidget(chat_card)

    tabs_row = getattr(views, "char_tabs_row", None)
    tabs_frame = tabs_row.parentWidget() if tabs_row is not None else None
    if tabs_frame is not None and page.layout() is not None:
        page.layout().removeWidget(tabs_frame)             # the tab row leaves the top of the page for Quick People

    left = _build_left(context, controller, parts, sidebar, tabs_frame, tabs_row, lang)
    center = QWidget(area)
    center.setObjectName("dashCenter")
    center.setLayoutDirection(rtl)
    center_layout = QVBoxLayout(center)
    center_layout.setContentsMargins(0, 0, 0, 0)
    center_layout.setSpacing(12)
    center_layout.addWidget(_build_greeting(context, lang))
    center_layout.addWidget(_build_stats(context, parts, lang))
    center_layout.addWidget(chat_card, 1)
    area_layout.addWidget(left, 0)
    area_layout.addWidget(center, 1)


def _build_left(context, controller, parts, sidebar, tabs_frame, tabs_row, lang) -> QScrollArea:
    fa = lang == "fa"
    scroll = QScrollArea()
    scroll.setObjectName("dashLeftScroll")
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    scroll.setFixedWidth(LEFT_WIDTH)
    scroll.viewport().setAutoFillBackground(False)
    column = QWidget()
    column.setObjectName("dashLeft")
    column.setLayoutDirection(Qt.RightToLeft if fa else Qt.LeftToRight)
    layout = QVBoxLayout(column)
    layout.setContentsMargins(8, 8, 8, 8)
    layout.setSpacing(10)

    layout.addWidget(_label("KIRA ✦", "dashBrand"))
    layout.addWidget(_label("همراه هوشمند تو" if fa else "Your AI Companion", "dashBrandSub"))
    layout.addLayout(_build_nav(context, controller, parts, lang))
    layout.addWidget(_build_profile(context, parts, lang))
    if tabs_frame is not None:
        layout.addWidget(_label("افراد سریع" if fa else "Quick People", "dashSection"))
        tabs_frame.setMinimumWidth(0)
        if tabs_row is not None:
            tabs_row.setDirection(QBoxLayout.Direction.TopToBottom)     # one character per row, like the reference
        layout.addWidget(tabs_frame)
    sidebar.setMinimumWidth(0)
    sidebar.setMaximumWidth(16777215)
    sidebar.setMinimumHeight(60)
    layout.addWidget(sidebar, 1)
    scroll.setWidget(column)
    return scroll


def _build_nav(context, controller, parts, lang) -> QVBoxLayout:
    fa = lang == "fa"
    layout = QVBoxLayout()
    layout.setSpacing(4)
    group = QButtonGroup(layout)
    buttons = {}
    keys = list(getattr(context.views, "tab_keys", []) or [])

    def activate(tab_key):
        if tab_key is None:
            _soon(context, lang)
        elif controller is not None and tab_key in keys:
            controller.go_tab(keys.index(tab_key))
        buttons["chat"].setChecked(True)                   # this page is still the chat page

    for key, glyph, english, persian, tab_key in NAV:
        text = persian if fa else english
        button = QPushButton()
        button.setObjectName("navItem")
        button.setCheckable(True)
        button.setCursor(Qt.PointingHandCursor)
        button.setFocusPolicy(Qt.NoFocus)
        button.setFixedHeight(46)
        if glyph in _ICONS:
            button.setIcon(make_icon(glyph, normal="#cbbcff", hover="#ffffff", checked="#ffffff", disabled="#52617B"))
            button.setIconSize(QSize(20, 20))
            button.setText("  " + text)
        else:
            button.setText(f"{glyph}   {text}")
        button.clicked.connect(lambda checked=False, target=tab_key: activate(target))
        group.addButton(button)
        buttons[key] = button
        layout.addWidget(button)
    buttons["chat"].setChecked(True)
    parts["nav"] = buttons
    return layout


def _build_profile(context, parts, lang) -> QFrame:
    fa = lang == "fa"
    card = _frame("dashProfile")
    outer = QVBoxLayout(card)
    outer.setContentsMargins(12, 12, 12, 12)
    outer.setSpacing(8)
    top = QHBoxLayout()
    top.setSpacing(10)
    picture = QLabel()
    picture.setFixedSize(52, 52)
    cid = str(getattr(getattr(context.state, "cur", None), "cid", "") or "kira")
    pixmap = _character_pixmap(context, cid, 52)
    if pixmap is not None:
        picture.setPixmap(pixmap)
    else:
        picture.setText("✦")
        picture.setAlignment(Qt.AlignCenter)
    names = QVBoxLayout()
    try:
        name = str(context.services.character_service.display_name(context.services.settings))
    except Exception:                                      # noqa: BLE001
        name = "Kira"
    parts["profile_name"] = _label(name, "dashName")
    names.addWidget(parts["profile_name"])
    names.addWidget(_label("● " + ("آنلاین" if fa else "Online"), "dashOnline"))
    top.addWidget(picture)
    top.addLayout(names, 1)
    outer.addLayout(top)
    quote = _label("«همیشه اینجام، برای هر چیزی که لازم داری.»" if fa
                   else "“I'm always here, for whatever you need.”", "dashQuoteText")
    quote.setWordWrap(True)
    outer.addWidget(quote)
    heart = _label("♡", "dashHeart")
    heart.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
    outer.addWidget(heart)
    return card


def _build_greeting(context, lang) -> QWidget:
    fa = lang == "fa"
    box = QWidget()
    row = QHBoxLayout(box)
    row.setContentsMargins(4, 0, 4, 0)
    texts = QVBoxLayout()
    texts.setSpacing(2)
    texts.addWidget(_label(greeting_text(lang, datetime.now().hour) + " ♡", "dashGreeting"))
    texts.addWidget(_label("امیدوارم روزت مهربان بوده باشه." if fa else "Hope your day was kind to you.", "dashGreetingSub"))
    row.addLayout(texts, 1)
    for glyph in ("♫", "☾", "🔔"):
        row.addWidget(_display_button(context, lang, glyph, "roundIcon", box))
    return box


def _stat_card(title_glyph, title, with_arrow) -> tuple[QFrame, QVBoxLayout, QHBoxLayout]:
    card = _frame("statCard")
    card.setMinimumHeight(96)
    outer = QVBoxLayout(card)
    outer.setContentsMargins(12, 10, 12, 10)
    outer.setSpacing(4)
    head = QHBoxLayout()
    head.addWidget(_label(f"{title_glyph}  {title}", "statTitle"))
    head.addStretch(1)
    if with_arrow:
        head.addWidget(_label("›", "statSub"))
    outer.addLayout(head)
    body = QHBoxLayout()
    texts = QVBoxLayout()
    texts.setSpacing(1)
    body.addLayout(texts, 1)
    outer.addLayout(body, 1)
    return card, texts, body


def _build_stats(context, parts, lang) -> QWidget:
    fa = lang == "fa"
    try:
        name = str(context.services.character_service.display_name(context.services.settings))
    except Exception:                                      # noqa: BLE001
        name = "Kira"
    box = QWidget()
    row = QHBoxLayout(box)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(10)

    bond, texts, body = _stat_card("♡", "پیوند ما" if fa else "Our Bond", False)
    texts.addWidget(_label("سطح ۱۲" if fa else "Level 12", "statValue"))
    texts.addWidget(_label("متصل" if fa else "Connected", "statSub"))
    body.addWidget(_Ring(72))
    row.addWidget(bond, 1)

    mood, texts, body = _stat_card("☺", f"حال {name}" if fa else f"{name}'s Mood", True)
    parts["mood_title"] = _label("آرام" if fa else "Calm", "statValue")
    parts["mood_sub"] = _label("آسوده" if fa else "Relaxed", "statSub")
    texts.addWidget(parts["mood_title"])
    texts.addWidget(parts["mood_sub"])
    body.addWidget(_Sparkline())
    row.addWidget(mood, 1)

    vibe, texts, body = _stat_card("☆", "حال‌وهوای امروز" if fa else "Today's Vibe", True)
    texts.addWidget(_label("شب بارونی،" if fa else "Rainy night,", "statValue"))
    texts.addWidget(_label("مناسب حرف‌های عمیق." if fa else "perfect for deep talks.", "statSub"))
    body.addWidget(_label("☁", "dashHeart"))
    row.addWidget(vibe, 1)
    return box


def _build_right(avatar_card, context, lang) -> None:
    fa = lang == "fa"
    layout = avatar_card.layout()
    if layout is None:
        return
    avatar_card.setLayoutDirection(Qt.RightToLeft if fa else Qt.LeftToRight)
    actions = _frame("dashActions")
    actions_row = QHBoxLayout(actions)
    actions_row.setContentsMargins(8, 8, 8, 8)
    actions_row.setSpacing(6)
    for glyph, english, persian in (("☎", "Call", "تماس"), ("♪", "Voice", "صدا"), ("🎁", "Surprise", "سورپرایز")):
        actions_row.addWidget(_display_button(context, lang, f"{glyph} {persian if fa else english}", "dashAction", actions))
    layout.addWidget(actions)

    playlist = _frame("dashPlaylist")
    row = QHBoxLayout(playlist)
    row.setContentsMargins(10, 8, 10, 8)
    row.setSpacing(10)
    cover = _label("", "dashCover")
    cover.setFixedSize(44, 44)
    texts = QVBoxLayout()
    texts.setSpacing(1)
    texts.addWidget(_label("پلی‌لیست کیرا" if fa else "Kira's Playlist", "dashTrackSub"))
    texts.addWidget(_label("افکار نیمه‌شب" if fa else "Midnight Thoughts", "dashTrackTitle"))
    row.addWidget(cover)
    row.addLayout(texts, 1)
    row.addWidget(_display_button(context, lang, "▶", "dashPlay", playlist))
    layout.addWidget(playlist)

    quote = _frame("dashQuote")
    quote_layout = QVBoxLayout(quote)
    quote_layout.setContentsMargins(12, 10, 12, 10)
    quote_layout.setSpacing(4)
    text = _label("لازم نیست بی‌نقص باشی تا برام مهم باشی." if fa
                  else "You don't have to be perfect to be important to me.", "dashQuoteText")
    text.setWordWrap(True)
    quote_layout.addWidget(text)
    heart = _label("♡", "dashHeart")
    heart.setAlignment(Qt.AlignRight)
    quote_layout.addWidget(heart)
    layout.addWidget(quote)


def _avatar_on_the_right(page, avatar_card, lang) -> None:
    """In the Persian (right-to-left) layout the character panel is already on the right; in English it must go last."""
    if lang == "fa" or page.layout() is None:
        return
    outer = page.layout()
    for index in range(outer.count()):
        row = outer.itemAt(index).layout()
        if row is not None and row.indexOf(avatar_card) >= 0:
            row.removeWidget(avatar_card)
            row.addWidget(avatar_card)
            return


# ---------------------------------------------------------------- controller wrappers

def _wrap_theme(controller, page, style) -> None:
    original = getattr(controller, "apply_chat_theme", None)
    if not callable(original):
        return

    def themed(*args, **kwargs):
        result = original(*args, **kwargs)
        page.setStyleSheet(page.styleSheet() + style)      # the theme replaced the stylesheet: put the skin back on top
        return result

    controller.apply_chat_theme = themed


def _picture_tabs(context) -> None:
    for character_id, button in dict(getattr(context.views, "char_tab_buttons", {}) or {}).items():
        if not button.icon().isNull():
            continue
        pixmap = _character_pixmap(context, character_id, 36)
        if pixmap is not None:
            button.setIcon(QIcon(pixmap))
            button.setIconSize(QSize(36, 36))


def _wrap_tabs(context, controller) -> None:
    original = getattr(controller, "refresh_tab_buttons", None)
    if not callable(original):
        return

    def refreshed(*args, **kwargs):
        result = original(*args, **kwargs)
        try:
            _picture_tabs(context)
        except Exception:                                  # noqa: BLE001 - pictures are optional
            _LOG.exception("Could not set the character pictures")
        return result

    controller.refresh_tab_buttons = refreshed
    _picture_tabs(context)


def _decorate_rows(widget) -> None:
    """The active conversation row shows its last-activity time and a dot, like the reference design."""
    for index in range(widget.count()):
        item = widget.item(index)
        row = widget.itemWidget(item)
        layout = row.layout() if row is not None else None
        if layout is None or not row.property("active") or row.findChild(QLabel, "conversationTime"):
            continue
        position = max(0, layout.count() - 1)              # just before the options button
        match = _STAMP.search(item.toolTip() or "")
        if match:
            layout.insertWidget(position, _label(match.group(1), "conversationTime", row))
            position += 1
        layout.insertWidget(position, _label("●", "conversationDot", row))


def _wrap_rows(controller, widget) -> None:
    original = getattr(controller, "refresh_conversation_list", None)
    if not callable(original):
        return

    def refreshed(*args, **kwargs):
        result = original(*args, **kwargs)
        try:
            _decorate_rows(widget)
        except Exception:                                  # noqa: BLE001 - decoration is optional
            _LOG.exception("Could not decorate the conversation rows")
        return result

    controller.refresh_conversation_list = refreshed
    _decorate_rows(widget)


def _refresh_mood(context, parts) -> None:
    title, sub = parts.get("mood_title"), parts.get("mood_sub")
    if title is None or sub is None:
        return
    cid = str(getattr(getattr(context.state, "cur", None), "cid", "") or "")
    state = context.services.mood_service.current(character_id=cid)
    title.setText(str(state.get("emotion", "neutral") or "neutral").capitalize())
    sub.setText(str(state.get("behavior", "balanced") or "balanced").capitalize())


def _wrap_mood(context, controller, parts) -> None:
    """update_mood_indicator() is polled by the window; the Mood card follows the same real mood state."""
    original = getattr(controller, "update_mood_indicator", None)
    if not callable(original):
        return

    def updated(*args, **kwargs):
        result = original(*args, **kwargs)
        try:
            _refresh_mood(context, parts)
        except Exception:                                  # noqa: BLE001 - the card keeps its last text
            _LOG.debug("Could not refresh the mood card", exc_info=True)
        return result

    controller.update_mood_indicator = updated
