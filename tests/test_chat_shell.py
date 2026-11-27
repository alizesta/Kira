import os
import unittest
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPropertyAnimation
from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QLabel, QListWidget, QPushButton, QToolButton, QVBoxLayout, QWidget

from kira.ui import chat_shell

_APP = QApplication.instance() or QApplication([])


def build(settings=None):
    """The same widget structure that VoiceSettingsController.build_chat_tab() creates, reduced to what the shell touches."""
    page = QWidget()
    outer = QVBoxLayout(page)
    tabs = QFrame()
    tabs_row = QHBoxLayout(tabs)
    outer.addWidget(tabs)
    body = QHBoxLayout()
    outer.addLayout(body, 1)
    avatar_card = QFrame()
    QVBoxLayout(avatar_card)
    avatar_card.setFixedWidth(250)
    body.addWidget(avatar_card)
    sidebar = QFrame(page)
    sidebar.setFixedWidth(154)
    sidebar_layout = QVBoxLayout(sidebar)
    conversation_list = QListWidget(sidebar)
    conversation_list.setAlternatingRowColors(True)
    sidebar_layout.addWidget(conversation_list, 1)
    header = QFrame(page)
    header_layout = QHBoxLayout(header)
    title = QLabel("Kira", header)
    header_layout.addWidget(title)
    opened = []
    session = SimpleNamespace(go_tab=opened.append)
    views = SimpleNamespace(
        chat_page=page, avatar_card=avatar_card, char_tabs_row=tabs_row,
        conversation_list=conversation_list, title=title, tab_keys=["tab_chat", "tab_general"],
    )
    context = SimpleNamespace(
        views=views,
        services=SimpleNamespace(settings=settings if settings is not None else {"ui_lang": "fa"}),
        controllers=SimpleNamespace(require=lambda name: session),
    )
    parts = SimpleNamespace(page=page, tabs=tabs, avatar_card=avatar_card, sidebar=sidebar, header=header, opened=opened)
    return context, parts


class ChatShellTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(chat_shell, "save_settings")
        self.save = patcher.start()
        self.addCleanup(patcher.stop)

    def test_missing_chat_page_is_a_no_op(self):
        context = SimpleNamespace(views=SimpleNamespace(), services=SimpleNamespace(settings={}), controllers=None)
        self.assertFalse(chat_shell.apply_chat_shell(context))

    def test_character_tabs_move_into_the_character_panel_which_starts_closed(self):
        context, p = build()
        self.assertTrue(chat_shell.apply_chat_shell(context))
        self.assertIs(p.tabs.parentWidget(), p.avatar_card)
        self.assertTrue(p.avatar_card.isHidden())
        self.assertIsNotNone(p.header.findChild(QToolButton, "avatarPanelToggle"))

    def test_saved_open_state_is_restored(self):
        context, p = build({"ui_lang": "fa", chat_shell.SETTING_KEY: True})
        chat_shell.apply_chat_shell(context)
        self.assertFalse(p.avatar_card.isHidden())
        self.assertTrue(p.header.findChild(QToolButton, "avatarPanelToggle").isChecked())

    def test_toggle_opens_and_closes_and_persists(self):
        context, p = build()
        chat_shell.apply_chat_shell(context)
        button = p.header.findChild(QToolButton, "avatarPanelToggle")
        animation = p.avatar_card.findChild(QPropertyAnimation)
        button.setChecked(True)
        self.assertFalse(p.avatar_card.isHidden())
        self.assertTrue(context.services.settings[chat_shell.SETTING_KEY])
        animation.setCurrentTime(animation.duration())
        button.setChecked(False)
        animation.setCurrentTime(animation.duration())
        self.assertTrue(p.avatar_card.isHidden())
        self.assertFalse(context.services.settings[chat_shell.SETTING_KEY])
        self.assertEqual(self.save.call_count, 2)

    def test_sidebar_is_widened_and_gets_a_footer(self):
        context, p = build()
        chat_shell.apply_chat_shell(context)
        self.assertEqual(p.sidebar.maximumWidth(), chat_shell.SIDEBAR_WIDTH)
        self.assertFalse(context.views.conversation_list.alternatingRowColors())
        self.assertIsNotNone(p.sidebar.findChild(QFrame, "sidebarProfile"))
        p.sidebar.findChild(QPushButton, "sidebarSettingsButton").click()
        self.assertEqual(p.opened, [1])

    def test_applying_twice_changes_nothing(self):
        context, p = build()
        chat_shell.apply_chat_shell(context)
        chat_shell.apply_chat_shell(context)
        self.assertEqual(len(p.header.findChildren(QToolButton, "avatarPanelToggle")), 1)
        self.assertEqual(len(p.sidebar.findChildren(QFrame, "sidebarFooter")), 1)


if __name__ == "__main__":
    unittest.main()
