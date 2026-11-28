"""Neon companion dashboard skin for the main chat page.

Layout (matches the reference design): left column = brand, navigation, profile card, Quick People (the character tabs),
conversations; centre = greeting, three stat cards, the chat card; right = the character panel (avatar, news) plus an action row,
a playlist card and a quote card.

Everything is built from the widgets VoiceSettingsController.build_chat_tab() already created (moved, never recreated, so every
signal and view reference keeps working) plus new widgets. Elements that have no feature behind them yet (Our Bond, Today's
Vibe, playlist, quote, Home/Voice Call/Memories/Gallery/Journal, Call/Voice/Surprise, the header icons) are display-only: a click
shows "coming soon" in the status line. Kira's Mood is real: it follows the mood service.

Every icon is a neon SVG from assets/icons rendered by ui_icons.make_icon (same bloom everywhere); no emoji or text glyph is used
as an icon any more, except the character badges of Quick People.

Each step is independent; a missing widget skips that step and an error is logged and leaves that part of the old layout alone.
Two controller methods overwrite what the skin sets, so they are wrapped on the controller INSTANCE (the class is untouched):
apply_chat_theme (replaces the page stylesheet), refresh_conversation_list / refresh_tab_buttons (rebuild rows and button text).
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from datetime import datetime

import math

from PySide6.QtCore import QEvent, QObject, QPoint, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QIcon, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QGraphicsDropShadowEffect, QSizePolicy,
    QBoxLayout, QButtonGroup, QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QToolButton, QVBoxLayout, QWidget,
)

from ..config import ROOT
from ..ui_icons import make_icon
from . import dash_theme

_LOG = logging.getLogger("kira.ui")
KIRA_PORTRAIT = ROOT / "assets" / "dashboard" / "kira_portrait.jpg"
_FACE_CROP = {"ren": (0.17, 0.08, 0.66), "mika": (0.26, 0.17, 0.50)}                    # (x, y, side) of the face square as fractions of the picture width


def _portrait_file(character_id, context=None):
    """The big picture of a character: assets/dashboard/<id>_portrait.jpg|png first, then its profile artwork (custom characters), or None."""
    for suffix in ("jpg", "png"):
        path = ROOT / "assets" / "dashboard" / f"{character_id}_portrait.{suffix}"
        if path.is_file():
            return path
    if context is not None:
        try:
            service = context.services.character_service
            profile = service.all_profiles(context.services.settings).get(character_id) or {}
            resolver = getattr(service, "portrait_file", None)
            found = resolver(profile, ROOT) if callable(resolver) else None
            return Path(found) if found else None
        except Exception:                                  # noqa: BLE001 - artwork is optional
            _LOG.debug("No profile portrait for %s", character_id, exc_info=True)
    return None


def _portrait_texts(character_id, fa):
    if character_id == "ren":
        return ("Ren", "بازار هیچ‌وقت نمی‌خوابه" if fa else "Markets never sleep")
    if character_id == "mika":
        return ("Mika", "سلامتت اولویت منه" if fa else "Your health comes first")
    if character_id == "kira":
        return ("Kira ✦", "همیشه اینجام برات" if fa else "Always here for you")
    return (str(character_id).capitalize(), "")
LEFT_WIDTH = 250
_STAMP = re.compile(r"\d{4}-\d{2}-\d{2} (\d{2}:\d{2})")
_ICONS = {"chat", "mic", "settings", "user", "home", "heart", "image", "book"}      # names make_icon() knows; the other navigation glyphs are plain text

# key, icon name or glyph, English, Persian, tab key to open (None = display only)
NAV = (
    ("home", "home", "Home", "خانه", "tab_chat"),
    ("chat", "chat", "Chat", "گفتگو", "tab_chat"),
    ("call", "mic", "Voice Call", "تماس صوتی", None),
    ("memories", "heart", "Memories", "خاطرات", None),
    ("gallery", "image", "Gallery", "گالری", None),
    ("journal", "book", "AIWU", "AIWU", None),
    ("settings", "settings", "Settings", "تنظیمات", "tab_general"),
)

STYLE = """
QWidget#chatPage { background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #09050f, stop:1 #140a2b); }
QScrollArea#dashLeftScroll, QWidget#dashLeft { background: transparent; border: none; }
QLabel#dashBrand { color: #c4a6ff; font-size: 26px; font-weight: 800; letter-spacing: 2px; }
QLabel#dashBrandSub { color: #c9b8f5; font-size: 12px; font-weight: 500; padding: 0 2px 4px 2px; }
QPushButton#navItem { background: transparent; color: #cbbcff; border: none; border-radius: 12px; padding: 10px 14px;
    text-align: %ALIGN%; font-size: 14px; }
QPushButton#navItem:hover { background: #1a1038; }
QPushButton#navItem:checked { color: #ffffff; background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #4b2bb8, stop:1 #6d3fe0); }
QFrame#dashProfile, QFrame#dashPlaylist, QFrame#dashQuote, QFrame#statCard, QFrame#dashActions {
    background: rgba(18, 10, 38, 178); border: 1px solid rgba(91, 63, 150, 150); border-radius: 16px; }
QFrame#avatarCard { background: rgba(15, 8, 36, 168); border: 1px solid rgba(91, 63, 150, 150); border-radius: 20px; }
QFrame#chatCard { background: rgba(18, 10, 38, 92); border: 1px solid rgba(91, 63, 150, 135); border-radius: 20px; }
QLabel#dashSection { color: #9a86c9; font-size: 12px; padding: 2px 6px; }
QLabel#dashName { color: #f4f0ff; font-size: 15px; font-weight: 600; }
QLabel#dashOnline { color: #46e08a; font-size: 11px; }
QLabel#dashQuoteText { color: #d9ccff; font-size: 13px; }
QLabel#dashHeart { color: #a855f7; font-size: 16px; }
QLabel#dashIcon { background: transparent; border: none; }
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
QPushButton#dashAction:checked { background: #2c1a63; border: 1px solid #8b5cf6; }
QPushButton#dashAction[compact="true"] { padding: 6px 3px; font-size: 11px; }
QPushButton#charTab[compact="true"] { padding: 3px 6px; }
QPushButton#navItem[compact="true"] { padding: 2px 14px; }
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
        painter.setPen(QPen(dash_theme.qcolor("#2a1a52"), 5))
        painter.drawEllipse(rect)
        arc = QPen(dash_theme.qcolor("#8b5cf6"), 5)
        arc.setCapStyle(Qt.RoundCap)
        painter.setPen(arc)
        painter.drawArc(rect, 90 * 16, -int(360 * 16 * self._percent / 100))
        painter.setPen(dash_theme.qcolor("#f1ecff"))
        font = painter.font()
        font.setPointSize(9)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(self.rect(), Qt.AlignCenter, f"{self._percent}%")


_INTENSE = {"angry", "frustrated", "annoyed", "excited", "jealous", "laughing", "surprised", "tsundere", "disgusted", "arrogant"}
_ANXIOUS = {"fearful", "shy", "embarrassed", "confused", "guilty", "lonely", "protective", "thinking"}
_SLOW = {"sad", "bored", "disappointed", "nostalgic", "calm", "content", "relieved", "neutral", "grateful"}


def wave_shape(emotion: str, intensity: int) -> tuple[float, float, float]:
    """(amplitude 0-1, waves across the card, speed) for Kira's tone: anger = big waves, worry = small, dense ones."""
    strength = max(0.0, min(1.0, intensity / 100.0))
    emotion = (emotion or "neutral").lower()
    if emotion in _INTENSE:
        return 0.55 + 0.45 * strength, 3.0 + 2.0 * strength, 0.22 + 0.2 * strength
    if emotion in _ANXIOUS:
        return 0.18 + 0.2 * strength, 7.0 + 5.0 * strength, 0.2 + 0.15 * strength
    if emotion in _SLOW:
        return 0.2 + 0.2 * strength, 1.4 + 0.6 * strength, 0.05 + 0.04 * strength
    return 0.35 + 0.25 * strength, 2.2 + 1.2 * strength, 0.1 + 0.08 * strength


class _Sparkline(QWidget):
    """The living wave of the "Kira's Mood" card: it follows the tone of Kira's current emotion."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumSize(120, 34)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setFixedHeight(40)
        self._shape = wave_shape("calm", 40)
        self._amp = self._shape[0]
        self._freq = self._shape[1]
        self._phase = 0.0
        glow = QGraphicsDropShadowEffect(self)               # real bloom around the whole line, not only the painted halo passes
        glow.setOffset(0, 0)
        glow.setBlurRadius(22)
        glow.setColor(QColor(dash_theme.second("#a78bfa")))
        self.setGraphicsEffect(glow)
        self._timer = QTimer(self)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self._tick)

    def set_mood(self, emotion: str, intensity: int = 40) -> None:
        self._shape = wave_shape(emotion, intensity)

    def showEvent(self, event) -> None:                    # noqa: N802 - Qt API
        self._timer.start()
        super().showEvent(event)

    def hideEvent(self, event) -> None:                    # noqa: N802 - Qt API
        self._timer.stop()
        super().hideEvent(event)

    def _tick(self) -> None:
        amp, freq, speed = self._shape
        self._amp += (amp - self._amp) * 0.08               # glide between moods instead of jumping
        self._freq += (freq - self._freq) * 0.08
        self._phase += speed
        self.update()

    def paintEvent(self, _event) -> None:                  # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        inset = 9                                           # keep the line and its glow inside the card
        w, h = self.width() - 2 * inset, self.height()
        amp = max(self._amp, 0.55)                          # never a flat line, even for a neutral mood
        path = QPainterPath()
        for x in range(0, w + 1, 2):
            t = x / max(1, w)
            envelope = math.sin(math.pi * t) ** 0.5          # calm at both ends like a pulse line
            y = h / 2 + math.sin(t * self._freq * 2 * math.pi + self._phase) * amp * (h / 2 - 9) * envelope
            y += math.sin(t * self._freq * 3.1 * math.pi - self._phase * 1.3) * amp * 3 * envelope
            path.moveTo(x + inset, y) if x == 0 else path.lineTo(x + inset, y)
        base = dash_theme.second("#a78bfa")                  # neon heartbeat line: wide soft bloom passes, then a bright core
        for width, alpha in ((14, 34), (10, 60), (7, 110), (4.4, 200)):
            glow = QColor(base)
            glow.setAlpha(alpha)
            painter.setPen(QPen(glow, width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            painter.drawPath(path)
        core = QColor(base).lighter(175)
        painter.setPen(QPen(core, 2.4, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        painter.drawPath(path)


class _Portrait(QWidget):
    """Kira's picture with her name over the bottom, like the right card of the reference."""

    def __init__(self, path, caption: str, subtitle: str, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("kiraPortrait")
        self._pixmap = QPixmap(str(path))
        self._caption, self._subtitle = caption, subtitle
        self._top = True
        self.setMinimumSize(150, 190)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def update_content(self, path, caption: str, subtitle: str) -> None:
        self._pixmap = QPixmap(str(path))
        self._caption, self._subtitle = caption, subtitle
        self.update()

    def paintEvent(self, _event) -> None:                  # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(self.rect()), 18, 18)
        painter.setClipPath(clip)
        if not self._pixmap.isNull():
            scaled = self._pixmap.scaled(self.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            painter.drawPixmap((self.width() - scaled.width()) // 2, 0, scaled)   # keep the face, crop the bottom
        fade = QLinearGradient(0, self.height() * 0.6, 0, self.height())
        fade.setColorAt(0, dash_theme.rgba(10, 6, 24, 0))
        fade.setColorAt(1, dash_theme.rgba(10, 6, 24, 215))
        painter.fillRect(self.rect(), fade)
        painter.setPen(dash_theme.qcolor("#ffffff"))
        font = painter.font()
        font.setPixelSize(26)
        font.setWeight(font.Weight.DemiBold)
        painter.setFont(font)
        painter.drawText(16, self.height() - 38, self._caption)
        font.setPixelSize(13)
        font.setWeight(font.Weight.Normal)
        painter.setFont(font)
        painter.setPen(dash_theme.qcolor("#c4b5fd"))
        painter.drawText(16, self.height() - 16, self._subtitle)



class _CharacterChatBackground(QWidget):
    """Paint the active character's profile background behind the chat shell."""

    def __init__(self, page) -> None:
        super().__init__(page)
        self.setObjectName("characterChatBackground")
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setFocusPolicy(Qt.NoFocus)
        self._pixmap = QPixmap()
        page.installEventFilter(self)
        self.setGeometry(page.rect())
        self.lower()
        self.hide()

    def eventFilter(self, watched, event):  # noqa: N802 - Qt API
        if watched is self.parentWidget() and event.type() == QEvent.Resize:
            self.setGeometry(watched.rect())
        return False

    def sync(self, context) -> None:
        cid = _active_cid(context)
        try:
            service = context.services.character_service
            profile = service.all_profiles(context.services.settings).get(cid) or {}
            resolver = getattr(service, "chat_background_file", None)
            path = resolver(profile, ROOT) if callable(resolver) else None
            pixmap = QPixmap(str(path)) if path else QPixmap()
        except Exception:  # noqa: BLE001 - optional artwork must not break the chat
            _LOG.debug("Could not resolve %s chat background", cid, exc_info=True)
            pixmap = QPixmap()
        self._pixmap = pixmap
        self.setVisible(not pixmap.isNull())
        self.lower()
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt API
        if self._pixmap.isNull():
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        scaled = self._pixmap.scaled(
            self.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation
        )
        x = (self.width() - scaled.width()) // 2
        y = (self.height() - scaled.height()) // 2
        painter.drawPixmap(x, y, scaled)
        painter.fillRect(self.rect(), QColor(8, 4, 24, 142))


def _sync_chat_background(context) -> None:
    page = getattr(getattr(context, "views", None), "chat_page", None)
    if page is None:
        return
    background = getattr(page, "_character_chat_background", None)
    if background is None:
        background = _CharacterChatBackground(page)
        page._character_chat_background = background
    background.setGeometry(page.rect())
    background.sync(context)



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


def _icon_label(icon_name: str, size: int, colour: str = "#b9a2ff") -> QLabel:
    """A neon SVG icon (assets/icons/<icon_name>.svg, same bloom as every button icon) as a plain label."""
    label = QLabel()
    label.setObjectName("dashIcon")
    label.setFixedSize(size + 4, size + 4)
    label.setAlignment(Qt.AlignCenter)
    dash_theme.set_pixmap(label, icon_name, size, normal=colour)
    return label


_BADGES = {"kira": "star", "ren": "bull", "mika": "snake"}


def _is_fa(context) -> bool:
    try:
        return context.services.settings.get("ui_lang", "en") == "fa"
    except Exception:                                      # noqa: BLE001
        return False


def _character_pixmap(context, character_id, size):
    """Round avatar picture of one character, or None when it has no readable picture."""
    try:
        service = context.services.character_service
        profile = service.all_profiles(context.services.settings).get(character_id) or {}
        picture = service.avatar_file(profile, ROOT)
        own = _portrait_file(character_id)
        if own is not None:                                   # the character's dashboard picture: face crop
            full = QPixmap(str(own))
            crop = _FACE_CROP.get(character_id)
            if crop is not None:
                fx, fy, fside = crop
                side = int(full.width() * fside)
                full = full.copy(int(full.width() * fx), int(full.width() * fy), side, side)
                source = full.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                offset = 0
            else:
                source = full.scaledToWidth(size, Qt.SmoothTransformation)
                offset = -int(size * 0.12)
            result = QPixmap(size, size)
            result.fill(Qt.transparent)
            painter = QPainter(result)
            painter.setRenderHint(QPainter.Antialiasing)
            clip = QPainterPath()
            clip.addEllipse(0, 0, size, size)
            painter.setClipPath(clip)
            painter.drawPixmap(0, offset, source)
            painter.end()
            return result
        source = QPixmap(str(picture))
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


class _Waveform(QWidget):
    """The thin bar waveform under the playlist title (decorative)."""

    _BARS = (3, 6, 4, 9, 5, 12, 7, 4, 10, 14, 8, 5, 11, 6, 3, 8, 13, 9, 5, 7, 4, 10, 6, 3, 8, 12, 7, 4, 9, 5, 3, 6, 4, 8, 5, 3)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedHeight(18)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def paintEvent(self, _event) -> None:                  # noqa: N802 - Qt API
        painter = QPainter(self)
        step = max(4, self.width() // len(self._BARS))
        for index, bar in enumerate(self._BARS):
            x = index * step
            if x + 2 > self.width():
                break
            painter.fillRect(x, self.height() - bar, 2, bar, QColor("#8b5cf6" if index < 14 else "#4a3b86"))


class _BellButton(QPushButton):
    """Round bell icon with the small red "new" dot of the reference."""

    def paintEvent(self, event) -> None:                   # noqa: N802 - Qt API
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(dash_theme.qcolor("#ff4d8d"))
        painter.drawEllipse(self.width() - 14, 6, 8, 8)


def _bind_call(context, button, fa) -> None:
    """Call = a live Gemini Live voice conversation (the Voice page's live toggle), shown as pressed while the call is on."""
    page = getattr(context.views, "voice_page", None)
    toggle = getattr(page, "live_toggle", None)
    if toggle is None:
        button.clicked.connect(lambda checked=False: _soon(context, "fa" if fa else "en"))
        return
    button.setCheckable(True)
    button.setToolTip("تماس زنده با Gemini Live" if fa else "Live call with Gemini Live")
    idle, active = ("تماس", "پایان") if fa else ("Call", "End")
    button.setChecked(toggle.isChecked())
    button.setText(active if toggle.isChecked() else idle)
    button.clicked.connect(lambda checked=False: toggle.setChecked(bool(checked)))

    def mirror(on) -> None:
        button.blockSignals(True)
        button.setChecked(bool(on))
        button.setText(active if on else idle)
        button.blockSignals(False)

    toggle.toggled.connect(mirror)


def _bind_voice(context, button, fa) -> None:
    """Voice = read Kira's replies aloud (the composer's speaker toggle); pressing it on also reads the last reply."""
    speaker = getattr(context.views, "voice_btn", None)
    if speaker is None:
        button.clicked.connect(lambda checked=False: _soon(context, "fa" if fa else "en"))
        return
    button.setCheckable(True)
    button.setToolTip("خواندن پاسخ‌ها با صدا" if fa else "Read replies aloud")
    button.setChecked(speaker.isChecked())

    def pressed(checked=False) -> None:
        if speaker.isChecked() != bool(checked):
            speaker.click()                                # same path as the composer's speaker button
        if checked:
            _speak_last_reply(context)

    button.clicked.connect(pressed)
    speaker.toggled.connect(lambda on: (button.blockSignals(True), button.setChecked(bool(on)), button.blockSignals(False)))


def _speak_last_reply(context) -> None:
    try:
        current = context.state.cur
        history = context.services.chat_application_service.recent_messages(
            8, character_id=current.cid, conversation_id=current.conversation_id)
        last = next((str(m.get("content") or "") for m in reversed(history) if m.get("role") == "assistant"), "")
        if last.strip():
            context.services.voice_application_service.speak(last)
    except Exception:                                      # noqa: BLE001 - reading aloud is optional
        _LOG.debug("Could not read the last reply aloud", exc_info=True)


def _surprise(context, lang) -> None:
    """Surprise: Kira drops a short line, idea or tiny fact into the chat (offline, no model call)."""
    from .surprises import next_surprise
    controller = _session_controller(context)
    try:
        controller.add_chat("assistant", next_surprise(lang))
    except Exception:                                      # noqa: BLE001 - a skin problem must never break the app
        _LOG.exception("Surprise could not be shown")


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
    dash_theme.set_character(_active_cid(context))
    raw_style = STYLE.replace("%ALIGN%", "left")
    style = dash_theme.css(raw_style)
    if not page.objectName():
        page.setObjectName("chatPage")
    page.setStyleSheet(page.styleSheet() + style)
    _sync_chat_background(context)
    controller = _session_controller(context)
    parts = {}
    steps = (
        ("layout", lambda: _build_layout(context, controller, parts, lang)),
        ("right column", lambda: _build_right(avatar_card, context, lang, parts)),
        ("tagline", lambda: _hide_tagline(avatar_card)),
        ("avatar side", lambda: _avatar_on_the_right(page, avatar_card, lang)),
        ("style survives theme changes", lambda: _wrap_theme(context, controller, page, raw_style)),
        ("character pictures", lambda: _wrap_tabs(context, controller)),
        ("conversation rows", lambda: _wrap_rows(controller, conversation_list)),
        ("mood card", lambda: _wrap_mood(context, controller, parts)),
        ("top bar", lambda: _hide_bar_on_chat(context)),
    )
    for name, step in steps:
        try:
            step()
        except Exception:                                  # noqa: BLE001 - a skin problem must never break the app
            _LOG.exception("Chat shell step %r failed", name)
    QTimer.singleShot(0, lambda: resize_chat_shell(context))
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
    rtl = Qt.LeftToRight
    area_layout.setDirection(QBoxLayout.Direction.LeftToRight)
    page.setLayoutDirection(Qt.LeftToRight)
    sidebar.setLayoutDirection(Qt.LeftToRight)
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
    parts["mood_card"] = _build_mood_card(context, parts, lang)      # lives under Kira's picture; Our Bond / Today's Vibe are gone
    center_layout.addWidget(chat_card, 1)
    parts["chat_card"] = chat_card
    panel = getattr(views, "news_feed_panel", None)
    if panel is not None:                                  # the characters' news feed lives in Journal
        for guard in [c for c in panel.children() if type(c).__name__ == "_HideGuard"]:
            panel.removeEventFilter(guard)
            guard.deleteLater()
        panel.setParent(center)
        center_layout.addWidget(panel, 1)
        panel.setMaximumSize(16777215, 16777215)
        panel.setMinimumWidth(0)
        panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        panel.hide()
        parts["news_panel"] = panel
    area_layout.addWidget(left, 0)
    area_layout.addWidget(center, 1)


def _build_left(context, controller, parts, sidebar, tabs_frame, tabs_row, lang) -> QWidget:
    fa = lang == "fa"
    scroll = QScrollArea()
    scroll.setObjectName("dashLeftScroll")
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    scroll.setFixedWidth(LEFT_WIDTH)
    scroll.viewport().setAutoFillBackground(False)
    column = QWidget()
    column.setObjectName("dashLeft")
    column.setLayoutDirection(Qt.LeftToRight)
    layout = QVBoxLayout(column)
    layout.setContentsMargins(8, 8, 8, 8)
    layout.setSpacing(6)

    brand = QHBoxLayout()                                  # cat-face logo, KIRA, sparkle: like the reference
    brand.setSpacing(8)
    brand.addWidget(_icon_label("cat", 34, "#c4a6ff"))
    brand.addWidget(_label("KIRA", "dashBrand"))
    brand.addWidget(_icon_label("sparkle", 18, "#c4a6ff"), 0, Qt.AlignTop)
    brand.addStretch(1)
    layout.addLayout(brand)
    brand_sub = _label("دستیار هوشمند تو" if fa else "Your AI Companion", "dashBrandSub")
    brand_sub.setWordWrap(True)
    brand_sub.setLayoutDirection(Qt.LeftToRight)
    brand_sub.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    layout.addWidget(brand_sub)
    layout.addLayout(_build_nav(context, controller, parts, lang))
    parts["profile"] = _build_profile(context, parts, lang)     # the Kira/Online card is no longer shown; the conversation list takes its place
    sidebar.setMinimumWidth(0)
    sidebar.setMaximumWidth(16777215)
    sidebar.setMinimumHeight(150)
    sidebar.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)   # its inner rows must not widen the column
    new_chat = getattr(context.views, "new_chat_btn", None)
    if new_chat is not None:
        new_chat.hide()                                    # the Chat item above already starts a conversation view
    _add_new_chat_plus(context, sidebar, new_chat, fa)
    layout.addWidget(sidebar, 1)
    if tabs_frame is not None:
        layout.addWidget(_label("افراد سریع" if fa else "Quick People", "dashSection"))
        tabs_frame.setMinimumWidth(0)
        tabs_frame.setLayoutDirection(Qt.LeftToRight)
        if tabs_row is not None:
            tabs_row.setDirection(QBoxLayout.Direction.TopToBottom)     # one character per row, like the reference
        layout.addWidget(tabs_frame)
    scroll.setWidget(column)
    scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    scroll.verticalScrollBar().setStyleSheet("QScrollBar:vertical { width: 0px; }")   # scrolls by wheel, takes no room
    holder = QWidget()
    holder.setObjectName("dashLeftHolder")
    holder.setFixedWidth(LEFT_WIDTH + 5)
    holder.setLayoutDirection(Qt.LeftToRight)
    holder_layout = QVBoxLayout(holder)
    holder_layout.setContentsMargins(0, 0, 0, 8)
    holder_layout.setSpacing(6)
    holder_layout.addWidget(scroll, 1)
    return holder


def _add_new_chat_plus(context, sidebar, new_chat, fa) -> None:
    """A "+" icon at the end of the Conversations title row starts a new chat (the old wide button is hidden)."""
    title = getattr(context.views, "conversation_list_title", None)
    box = sidebar.layout() if sidebar is not None else None
    if title is None or box is None or new_chat is None or box.indexOf(title) < 0:
        return
    plus = QToolButton(sidebar)
    plus.setObjectName("newChatPlus")
    plus.setCursor(Qt.PointingHandCursor)
    plus.setFocusPolicy(Qt.NoFocus)
    plus.setToolTip("چت جدید" if fa else "New chat")
    dash_theme.set_icon(plus, "plus", 18, normal="#c4a6ff", hover="#ffffff")
    plus.setFixedSize(28, 28)
    dash_theme.set_style(plus, "QToolButton#newChatPlus { background: rgba(139,92,246,0.14); border: 1px solid #6d4bc2; border-radius: 14px; }"
                       "QToolButton#newChatPlus:hover { background: rgba(167,139,250,0.30); border-color: #c4b5fd; }")
    plus.clicked.connect(lambda checked=False: new_chat.click())
    index = box.indexOf(title)
    box.removeWidget(title)
    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 4, 0)
    row.addWidget(title, 1)
    row.addWidget(plus, 0, Qt.AlignVCenter)
    box.insertLayout(index, row)


def _settings_button(context, lang) -> QPushButton:
    """Bottom-left gear: opens the same menu the hamburger bar used to hold."""
    button = QPushButton(("⚙  تنظیمات" if lang == "fa" else "⚙  Settings"))
    button.setObjectName("dashSettings")
    button.setCursor(Qt.PointingHandCursor)
    button.setFocusPolicy(Qt.NoFocus)
    button.setFixedHeight(40)

    def open_menu() -> None:
        menu = getattr(context.views, "nav_menu", None)
        if menu is not None:
            menu.exec(button.mapToGlobal(QPoint(0, -menu.sizeHint().height())))

    button.clicked.connect(lambda checked=False: open_menu())
    return button


def _hide_bar_on_chat(context) -> None:
    """The hamburger bar is only shown on the other pages; on the chat page the gear replaces it."""
    views = context.views
    menu_button, tabs = getattr(views, "menu_btn", None), getattr(views, "tabs", None)
    bar = menu_button.parentWidget() if menu_button is not None else None
    if bar is None or tabs is None:
        return
    chat_index = list(views.tab_keys).index("tab_chat")

    def sync(index=None) -> None:
        bar.setVisible(tabs.currentIndex() != chat_index)

    tabs.currentChanged.connect(sync)
    sync()


def _build_nav(context, controller, parts, lang) -> QVBoxLayout:
    fa = lang == "fa"
    layout = QVBoxLayout()
    layout.setSpacing(4)
    group = QButtonGroup(layout)
    buttons = {}
    keys = list(getattr(context.views, "tab_keys", []) or [])

    def activate(tab_key, key=None):
        card, panel = parts.get("chat_card"), parts.get("news_panel")
        if card is not None and panel is not None:
            journal = key == "journal"
            card.setVisible(not journal)
            panel.setVisible(journal)
            if journal:
                session = getattr(context.state, "front", None) or getattr(context.state, "cur", None)
                character_id = str(getattr(session, "cid", "") or "kira")
                open_for_character = getattr(panel, "open_for_character", None)
                if callable(open_for_character):
                    open_for_character(character_id)
                else:
                    panel.set_character(character_id)
                    panel.refresh_view()
                buttons["journal"].setChecked(True)
                return
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
        button.setFixedHeight(40)
        button.setLayoutDirection(Qt.LeftToRight)   # shell controls remain LTR in every locale
        if glyph in _ICONS:
            dash_theme.set_icon(button, glyph, 22, normal="#b9a2ff", hover="#ffffff", checked="#ffffff", disabled="#52617B")
            button.setText(" " + text)
        else:
            button.setText(f"{glyph}   {text}")
        button.clicked.connect(lambda checked=False, target=tab_key, name=key: activate(target, name))
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
    session = getattr(context.state, "front", None) or getattr(context.state, "cur", None)
    cid = str(getattr(session, "cid", "") or "kira")
    pixmap = _character_pixmap(context, cid, 52)
    if pixmap is not None:
        picture.setPixmap(pixmap)
    else:
        dash_theme.set_pixmap(picture, "sparkle", 26, normal="#c4a6ff")
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
    outer.addWidget(_icon_label("heart", 20, "#a855f7"), 0, Qt.AlignRight)
    return card


def _build_greeting(context, lang) -> QWidget:
    fa = lang == "fa"
    box = QWidget()
    row = QHBoxLayout(box)
    row.setContentsMargins(4, 0, 4, 0)
    texts = QVBoxLayout()
    texts.setSpacing(2)
    title_row = QHBoxLayout()                              # greeting text followed by the neon heart of the reference
    title_row.setSpacing(8)
    title_row.addWidget(_label(greeting_text(lang, datetime.now().hour), "dashGreeting"))
    title_row.addWidget(_icon_label("heart", 24, "#a855f7"))
    title_row.addStretch(1)
    texts.addLayout(title_row)
    texts.addWidget(_label("امیدوارم روزت مهربان بوده باشه." if fa else "Hope your day was kind to you.", "dashGreetingSub"))
    row.addLayout(texts, 1)
    # The chat header is intentionally quiet: no bell, music or moon controls.

    return box


def _stat_card(title_icon, title, with_arrow) -> tuple[QFrame, QVBoxLayout, QHBoxLayout]:
    """A stat card: a neon icon (name of assets/icons/<name>.svg, or "" for none), the title and an optional arrow."""
    card = _frame("statCard")
    card.setMinimumHeight(96)
    outer = QVBoxLayout(card)
    outer.setContentsMargins(12, 10, 12, 10)
    outer.setSpacing(4)
    head = QHBoxLayout()
    head.setSpacing(6)
    if title_icon:
        head.addWidget(_icon_label(title_icon, 18))
    head.addWidget(_label(title, "statTitle"))
    head.addStretch(1)
    if with_arrow:
        head.addWidget(_icon_label("chevron_right", 14, "#8f7bc0"))
    outer.addLayout(head)
    body = QHBoxLayout()
    texts = QVBoxLayout()
    texts.setSpacing(1)
    body.addLayout(texts, 1)
    outer.addLayout(body, 1)
    return card, texts, body


def _build_mood_card(context, parts, lang) -> QFrame:
    fa = lang == "fa"
    try:
        name = str(context.services.character_service.display_name(context.services.settings))
    except Exception:                                      # noqa: BLE001
        name = "Kira"
    mood, texts, body = _stat_card("", f"حال {name}" if fa else f"{name}'s Mood", False)
    mood.setMinimumHeight(0)
    mood.setFixedHeight(104)
    mood.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)     # follows the picture column's width (200-300 px)
    face = getattr(context.views, "mood_emotion_icon", None)
    if face is not None:                                    # the cat face stands before the title (the old static emoji is gone)
        face.setParent(None)
        face.setStyleSheet("border: none; background: transparent; padding: 0px;")
        mood.layout().itemAt(0).layout().insertWidget(0, face)
    bolt = getattr(context.views, "mood_indicator", None)
    if bolt is not None:
        bolt.setParent(None)                               # the lightning bolt is not shown any more
        bolt.hide()
    parts["mood_title"] = _label("آرام" if fa else "Calm", "statValue")
    parts["mood_sub"] = _label("آسوده" if fa else "Relaxed", "statSub")
    texts.addWidget(parts["mood_title"])
    texts.addWidget(parts["mood_sub"])
    parts["sparkline"] = _Sparkline()
    parts["sparkline"].setMinimumWidth(120)
    body.setStretch(0, 0)                                   # the texts take only what they need; the neon wave gets the rest of the card
    body.addWidget(parts["sparkline"], 1)
    return mood


def _build_right(avatar_card, context, lang, parts=None) -> None:
    fa = lang == "fa"
    layout = avatar_card.layout()
    if layout is None:
        return
    avatar_card.setLayoutDirection(Qt.LeftToRight)
    if True:
        # Show exactly one large Kira portrait and retain AvatarView for Ren/Mika.
        stale_portraits = [
            widget for widget in avatar_card.findChildren(QWidget)
            if widget.objectName() == "kiraPortrait" or type(widget).__name__ == "_Portrait"
        ]
        for duplicate in stale_portraits:
            layout.removeWidget(duplicate)
            duplicate.hide()
            duplicate.setParent(None)
            duplicate.deleteLater()
        portrait = _Portrait(KIRA_PORTRAIT, *_portrait_texts("kira", fa), avatar_card)
        layout.insertWidget(0, portrait, 1)
        avatar_card.kira_portrait = portrait
    _sync_portrait(context)
    actions = _frame("dashActions")
    actions_row = QHBoxLayout(actions)
    actions_row.setContentsMargins(8, 8, 8, 8)
    actions_row.setSpacing(6)
    for icon, english, persian in (("phone", "Call", "تماس"), ("waveform", "Voice", "صدا"), ("gift", "Surprise", "سورپرایز")):
        if icon in ("gift", "phone", "waveform"):
            button = QPushButton(persian if fa else english, actions)
            button.setObjectName("dashAction")
            button.setCursor(Qt.PointingHandCursor)
            button.setFocusPolicy(Qt.NoFocus)
            if icon == "gift":
                button.clicked.connect(lambda checked=False: _surprise(context, lang))
            elif icon == "phone":
                _bind_call(context, button, fa)
            else:
                _bind_voice(context, button, fa)
        else:
            button = _display_button(context, lang, persian if fa else english, "dashAction", actions)
        dash_theme.set_icon(button, icon, 20, normal="#b18aff", hover="#ffffff")
        actions_row.addWidget(button)
    layout.addWidget(actions)

    mood = (parts or {}).get("mood_card")
    if mood is not None:
        layout.addWidget(mood)                              # Kira's Mood sits where the playlist used to be

    quote = _frame("dashQuote")
    quote_layout = QVBoxLayout(quote)
    quote_layout.setContentsMargins(12, 10, 12, 10)
    quote_layout.setSpacing(4)
    text = _label("لازم نیست بی‌نقص باشی تا برام مهم باشی." if fa
                  else "You don't have to be perfect to be important to me.", "dashQuoteText")
    text.setWordWrap(True)
    quote_layout.addWidget(text)
    quote_layout.addWidget(_icon_label("heart", 20, "#a855f7"), 0, Qt.AlignRight)
    layout.addWidget(quote)


def _hide_tagline(avatar_card) -> None:
    for label in avatar_card.findChildren(QLabel, "hint"):
        label.hide()


def _sync_portrait(context) -> None:
    """Characters with a dashboard picture show it in the big card; the others keep their own animated avatar."""
    views = context.views
    portrait = getattr(getattr(views, "avatar_card", None), "kira_portrait", None)
    avatar = getattr(views, "avatar", None)
    if avatar is None:
        return
    cid = _active_cid(context)

    picture = _portrait_file(cid, context)
    if portrait is not None and picture is not None:
        portrait.update_content(picture, *_portrait_texts(cid, _is_fa(context)))
        portrait.setVisible(True)
        avatar.setVisible(False)
    else:
        if portrait is not None:
            portrait.setVisible(False)
        avatar.show()                                      # no picture for this character: keep its animated avatar


def _active_cid(context) -> str:
    try:
        return str(context.services.character_service.active_id(context.services.settings) or "kira").strip().lower()
    except Exception:                                      # noqa: BLE001 - legacy/test hosts may not expose active_id
        state = getattr(context, "state", None)
        session = getattr(state, "cur", None) or getattr(state, "front", None)
        return str(getattr(session, "cid", "") or "kira").strip().lower()


def _compact_for_size(context, page, avatar_card) -> None:
    """In a window that is not maximised the cards shrink instead of running into each other."""
    height = page.height()
    short, tiny = height < 820, height < 690
    nav_height = 30 if tiny else 35 if short else 40
    for button in page.findChildren(QPushButton, "navItem"):
        button.setFixedHeight(nav_height)
        button.setIconSize(QSize(18, 18) if tiny else QSize(20, 20) if short else QSize(22, 22))
        button.setProperty("compact", "true" if short else "false")
        button.style().unpolish(button)
        button.style().polish(button)
    sidebar = getattr(context.views, "conversation_list", None)
    while sidebar is not None and sidebar.parentWidget() is not None and sidebar.parentWidget().objectName() != "dashLeft":
        sidebar = sidebar.parentWidget()                   # climb to the column's direct child: the whole history block
    if sidebar is not None and sidebar.parentWidget() is not None:
        sidebar.setMinimumHeight(0)
        sidebar.setMaximumHeight(16777215 if not short else 150)
    tab_icon = 30 if tiny else 36 if short else 48
    for button in dict(getattr(context.views, "char_tab_buttons", {}) or {}).values():
        button.setIconSize(QSize(tab_icon, tab_icon))
        button.setMinimumHeight(tab_icon + 6)
        button.setMaximumHeight(tab_icon + 14)
        button.setProperty("compact", "true" if short else "false")
        button.style().unpolish(button)
        button.style().polish(button)
    narrow = avatar_card is not None and avatar_card.width() < 285
    for button in page.findChildren(QPushButton, "dashAction"):
        button.setProperty("compact", "true" if narrow else "false")
        button.setIconSize(QSize(16, 16) if narrow else QSize(20, 20))
        button.style().unpolish(button)
        button.style().polish(button)
    mood = page.findChild(QFrame, "statCard")
    if mood is not None:
        mood.setFixedHeight(84 if short else 104)


def resize_chat_shell(context, available_width=None) -> None:
    """Reflow the chat shell using the chat page's width, not the whole window width."""
    views = getattr(context, "views", None)
    page = getattr(views, "chat_page", None)
    avatar_card = getattr(views, "avatar_card", None)
    if page is None:
        return
    try:
        width = int(available_width if available_width is not None else page.width())
    except (TypeError, ValueError):
        width = int(page.width())
    if width <= 0:
        return

    # The main app navigation already consumes part of the window. Measure only
    # the remaining chat page so the right portrait never steals the chat column.
    show_character_panel = width >= 900
    if avatar_card is not None:
        if show_character_panel:
            avatar_card.setFixedWidth(max(185, min(250, int(width * 0.23))))
            avatar_card.show()
        else:
            avatar_card.setFixedWidth(0)
            avatar_card.hide()

    left_width = max(150, min(LEFT_WIDTH, int(width * 0.24)))
    left_holder = page.findChild(QWidget, "dashLeftHolder")
    left_scroll = page.findChild(QScrollArea, "dashLeftScroll")
    if left_scroll is not None:
        left_scroll.setFixedWidth(left_width)
    if left_holder is not None:
        left_holder.setFixedWidth(left_width + 5)

    # The conversation list fills its column (8 px margins on each side); chat receives the rest.
    conversation_list = getattr(views, "conversation_list", None)
    history_panel = conversation_list.parentWidget() if conversation_list is not None else None
    if history_panel is not None:
        history_width = max(90, left_width - 16)             # the list fills its column (8 px margins on each side)
        history_panel.setMinimumWidth(0)
        history_panel.setMaximumWidth(history_width)
        history_panel.setMinimumWidth(history_width)

    _compact_for_size(context, page, avatar_card)

    center = page.findChild(QWidget, "dashCenter")
    if center is not None:
        center.setMinimumWidth(0)
        center.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        chat_card = center.findChild(QFrame, "chatCard")
        if chat_card is not None:
            chat_card.setMinimumWidth(0)
            chat_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)


def _avatar_on_the_right(page, avatar_card, lang) -> None:
    """Keep the character panel on the physical right in every locale."""
    if page.layout() is None:
        return
    outer = page.layout()
    for index in range(outer.count()):
        row = outer.itemAt(index).layout()
        if row is not None and row.indexOf(avatar_card) >= 0:
            row.removeWidget(avatar_card)
            row.addWidget(avatar_card)
            return


# ---------------------------------------------------------------- controller wrappers

def _paint_mood_face(context) -> None:
    """Kira's mood face is a cat; Ren's is the bull of the markets."""
    face = getattr(context.views, "mood_emotion_icon", None)
    if face is not None and _active_cid(context) == "ren":
        face.setPixmap(make_icon("bull", normal="#ff5964", hover="#ffffff").pixmap(30, 30))


def _wrap_theme(context, controller, page, raw_style) -> None:
    original = getattr(controller, "apply_chat_theme", None)
    if not callable(original):
        return

    def themed(*args, **kwargs):
        result = original(*args, **kwargs)
        dash_theme.set_character(_active_cid(context))
        page.setStyleSheet(page.styleSheet() + dash_theme.css(raw_style))   # the theme replaced the stylesheet: put the skin back on top
        dash_theme.retheme(page)
        _sync_portrait(context)
        _sync_chat_background(context)
        _paint_mood_face(context)
        return result

    controller.apply_chat_theme = themed


def _picture_tabs(context) -> None:
    for character_id, button in dict(getattr(context.views, "char_tab_buttons", {}) or {}).items():
        lines = button.text().splitlines()
        display_name = lines[0].split("  ")[0].strip() if lines else button.text().strip()
        button.setText(f"{display_name}\n\u200e● {'آنلاین' if _is_fa(context) else 'Online'}")
        badge = button.findChild(QLabel, "quickPeopleBadge")
        if badge is None:
            badge = QLabel(button)
            badge.setObjectName("quickPeopleBadge")
            badge.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        icon_name = _BADGES.get(character_id, "star")
        colour = "#ff5964" if character_id == "ren" else "#f472b6" if character_id == "mika" else "#c4a6ff"
        badge.setPixmap(make_icon(icon_name, normal=colour, hover="#ffffff").pixmap(18, 18))
        badge.setFixedSize(18, 18)
        badge.move(35, 2)
        badge.raise_()
        if button.icon().isNull():
            pixmap = _character_pixmap(context, character_id, 48)
            if pixmap is not None:
                button.setIcon(QIcon(pixmap))
                button.setIconSize(QSize(48, 48))


def _wrap_tabs(context, controller) -> None:
    original = getattr(controller, "refresh_tab_buttons", None)
    if not callable(original):
        return

    def refreshed(*args, **kwargs):
        result = original(*args, **kwargs)
        try:
            _picture_tabs(context)
            _sync_portrait(context)
            _sync_chat_background(context)
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
    wave = parts.get("sparkline")
    if wave is not None:
        wave.set_mood(str(state.get("emotion", "neutral")), int(state.get("intensity", 40) or 0))


def _wrap_mood(context, controller, parts) -> None:
    """update_mood_indicator() is polled by the window; the Mood card follows the same real mood state."""
    original = getattr(controller, "update_mood_indicator", None)
    if not callable(original):
        return

    def updated(*args, **kwargs):
        result = original(*args, **kwargs)
        try:
            _refresh_mood(context, parts)
            _paint_mood_face(context)
        except Exception:                                  # noqa: BLE001 - the card keeps its last text
            _LOG.debug("Could not refresh the mood card", exc_info=True)
        return result

    controller.update_mood_indicator = updated
