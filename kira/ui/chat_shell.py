"""Skin for the main chat page: a wide conversation sidebar with a footer, and a character panel that opens and closes.

It only rearranges widgets that VoiceSettingsController.build_chat_tab() already built (nothing is recreated, so every signal and
view reference keeps working) and adds one page-level stylesheet. Every step is independent: a missing widget skips that step and
an error in one step is logged and leaves the old layout of that part untouched.
"""
from __future__ import annotations

import logging

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QToolButton, QVBoxLayout

from ..config import save_settings

_LOG = logging.getLogger("kira.ui")
SIDEBAR_WIDTH = 220
AVATAR_PANEL_WIDTH = 250
PANEL_MS = 180
SETTING_KEY = "chat_avatar_panel_open"

SHELL_STYLE = """
QFrame#conversationSidebar { background: #0f1124; border: 1px solid #1d2040; border-radius: 14px; }
QFrame#conversationSidebar QPushButton#newChatButton { background: #1a1d4d; color: #e8ebff; border: 1px solid #343a8c;
    border-radius: 10px; padding: 8px 12px; font-weight: 600; }
QFrame#conversationSidebar QPushButton#newChatButton:hover { background: #22266a; }
QLabel#conversationListTitle { color: #8f95b8; padding: 4px 8px; font-size: 12px; }
QListWidget#conversationList { background: transparent; border: none; outline: none; }
QListWidget#conversationList::item { color: #d6d9f0; padding: 10px 10px; border-radius: 10px; margin: 1px 0; }
QListWidget#conversationList::item:hover { background: #15183a; }
QListWidget#conversationList::item:selected { background: #1b1e48; color: #ffffff; }
QPushButton#sidebarSettingsButton { background: transparent; color: #c9cdea; border: none; border-radius: 10px;
    padding: 9px 10px; text-align: %ALIGN%; }
QPushButton#sidebarSettingsButton:hover { background: #15183a; }
QFrame#sidebarProfile { background: #13163a; border-radius: 12px; }
QLabel#sidebarProfileAvatar { background: #2b2f6b; border-radius: 15px; color: #e8ebff; }
QLabel#sidebarProfileName { color: #e8ebff; font-weight: 600; }
QLabel#sidebarProfileBadge { background: #3b2fd6; color: #ffffff; border-radius: 6px; padding: 1px 6px;
    font-size: 10px; font-weight: 700; }
QFrame#chatCard { background: #0d0f20; border: 1px solid #1d2040; border-radius: 16px; }
QFrame#chatHeader { background: transparent; }
QLabel#chatHeaderTitle { color: #f1f3ff; font-size: 15px; font-weight: 600; }
QToolButton#avatarPanelToggle { background: transparent; border: 1px solid #2a2e5c; border-radius: 10px;
    color: #9aa2ff; padding: 4px 8px; }
QToolButton#avatarPanelToggle:hover { background: #15183a; }
QToolButton#avatarPanelToggle:checked { background: #1b1e48; }
QFrame#avatarCard { background: #0f1124; border: 1px solid #1d2040; border-radius: 14px; }
"""


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
    page.setStyleSheet(SHELL_STYLE.replace("%ALIGN%", "right" if lang == "fa" else "left"))
    steps = (
        ("character tabs", lambda: _move_character_tabs(page, avatar_card, getattr(views, "char_tabs_row", None))),
        ("sidebar", lambda: _build_sidebar(context, views, conversation_list, settings, lang)),
        ("character panel", lambda: _install_panel_toggle(views, avatar_card, settings, lang)),
    )
    for name, step in steps:
        try:
            step()
        except Exception:                                  # noqa: BLE001 - a skin problem must never break the app
            _LOG.exception("Chat shell step %r failed", name)
    return True


def _move_character_tabs(page, avatar_card, tabs_row) -> None:
    """The character tabs live in the character panel now, so the main page starts with the sidebar and the chat card."""
    frame = tabs_row.parentWidget() if tabs_row is not None else None
    outer, card_layout = page.layout(), avatar_card.layout()
    if frame is None or outer is None or card_layout is None:
        return
    outer.removeWidget(frame)
    frame.setMinimumWidth(0)
    card_layout.insertWidget(0, frame)


def _build_sidebar(context, views, conversation_list, settings, lang) -> None:
    sidebar = conversation_list.parentWidget()
    layout = sidebar.layout() if sidebar is not None else None
    if layout is None:
        return
    sidebar.setFixedWidth(SIDEBAR_WIDTH)
    conversation_list.setAlternatingRowColors(False)
    layout.setSpacing(6)
    fa = lang == "fa"
    footer = QFrame(sidebar)
    footer.setObjectName("sidebarFooter")
    footer_layout = QVBoxLayout(footer)
    footer_layout.setContentsMargins(0, 0, 0, 0)
    footer_layout.setSpacing(6)
    settings_button = QPushButton("⚙  تنظیمات" if fa else "⚙  Settings", footer)
    settings_button.setObjectName("sidebarSettingsButton")
    settings_button.setFlat(True)
    settings_button.setCursor(Qt.PointingHandCursor)
    settings_button.setFocusPolicy(Qt.NoFocus)
    settings_button.clicked.connect(lambda checked=False: _open_settings(context))
    profile = QFrame(footer)
    profile.setObjectName("sidebarProfile")
    profile_layout = QHBoxLayout(profile)
    profile_layout.setContentsMargins(8, 6, 8, 6)
    profile_layout.setSpacing(8)
    avatar = QLabel("👤", profile)
    avatar.setObjectName("sidebarProfileAvatar")
    avatar.setFixedSize(30, 30)
    avatar.setAlignment(Qt.AlignCenter)
    name = QLabel(str(settings.get("user_name") or "Kira User"), profile)
    name.setObjectName("sidebarProfileName")
    badge = QLabel("PRO", profile)
    badge.setObjectName("sidebarProfileBadge")
    profile_layout.addWidget(avatar)
    profile_layout.addWidget(name, 1)
    profile_layout.addWidget(badge)
    footer_layout.addWidget(settings_button)
    footer_layout.addWidget(profile)
    layout.addWidget(footer)


def _open_settings(context) -> None:
    keys = list(getattr(context.views, "tab_keys", []) or [])
    if "tab_general" in keys:
        context.controllers.require("session").go_tab(keys.index("tab_general"))


def _install_panel_toggle(views, avatar_card, settings, lang) -> None:
    """A button in the chat header opens and closes the character panel (avatar, character tabs and news)."""
    title = getattr(views, "title", None)
    header = title.parentWidget() if title is not None else None
    header_layout = header.layout() if header is not None else None
    if header_layout is None:
        return                                             # no place for the button: the panel stays open as before
    button = QToolButton(header)
    button.setObjectName("avatarPanelToggle")
    button.setText("◨")
    button.setCheckable(True)
    button.setAutoRaise(True)
    button.setCursor(Qt.PointingHandCursor)
    button.setFocusPolicy(Qt.NoFocus)
    button.setToolTip("پنل کاراکتر (آواتار، تب‌ها و خبر)" if lang == "fa" else "Character panel (avatar, tabs and news)")
    header_layout.addWidget(button, 0)
    avatar_card.setMinimumWidth(0)
    avatar_card.setMaximumWidth(AVATAR_PANEL_WIDTH)
    animation = QPropertyAnimation(avatar_card, b"maximumWidth", avatar_card)   # one animation, reused: no duplicates
    animation.setDuration(PANEL_MS)
    animation.setEasingCurve(QEasingCurve.Type.OutCubic)

    def finished() -> None:
        if not button.isChecked():
            avatar_card.hide()

    animation.finished.connect(finished)

    def toggled(checked: bool) -> None:
        animation.stop()
        settings[SETTING_KEY] = bool(checked)
        try:
            save_settings(settings)
        except Exception:                                  # noqa: BLE001 - the panel still works when saving fails
            _LOG.exception("Could not save the character panel state")
        if checked:
            avatar_card.show()
            animation.setStartValue(min(avatar_card.maximumWidth(), AVATAR_PANEL_WIDTH))
            animation.setEndValue(AVATAR_PANEL_WIDTH)
        else:
            animation.setStartValue(avatar_card.width() or AVATAR_PANEL_WIDTH)
            animation.setEndValue(0)
        animation.start()

    button.toggled.connect(toggled)
    opened = bool(settings.get(SETTING_KEY, False))
    button.blockSignals(True)
    button.setChecked(opened)
    button.blockSignals(False)
    avatar_card.setVisible(opened)
