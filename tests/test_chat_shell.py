import os
import unittest
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPropertyAnimation
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton, QToolButton, QVBoxLayout, QWidget,
)

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

    opened, deleted = [], []

    def refresh_conversation_list():
        """Like SessionController.refresh_conversation_list: rebuilds one active row with an options button."""
        conversation_list.clear()
        item = QListWidgetItem()
        item.setToolTip("آخرین فعالیت: 2026-11-27 16:32:10")
        conversation_list.addItem(item)
        row = QWidget(conversation_list)
        row.setProperty("active", True)
        row_layout = QHBoxLayout(row)
        row_layout.addWidget(QPushButton("chat", row), 1)
        row_layout.addWidget(QToolButton(row), 0)
        conversation_list.setItemWidget(item, row)
        return True

    session = SimpleNamespace(
        go_tab=opened.append,
        delete_conversation=deleted.append,
        apply_chat_theme=lambda: page.setStyleSheet("THEME { color: red; }"),
        refresh_conversation_list=refresh_conversation_list,
    )
    views = SimpleNamespace(
        chat_page=page, avatar_card=avatar_card, char_tabs_row=tabs_row,
        conversation_list=conversation_list, title=title, tab_keys=["tab_chat", "tab_general"],
    )
    context = SimpleNamespace(
        views=views,
        state=SimpleNamespace(cur=SimpleNamespace(conversation_id="c1")),
        services=SimpleNamespace(settings=settings if settings is not None else {"ui_lang": "fa"}),
        controllers=SimpleNamespace(require=lambda name: session),
    )
    parts = SimpleNamespace(page=page, tabs=tabs, avatar_card=avatar_card, sidebar=sidebar, header=header,
                            opened=opened, deleted=deleted, session=session, list=conversation_list)
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

    def test_closed_panel_stays_closed_when_a_window_resize_shows_it_again(self):
        context, p = build()
        chat_shell.apply_chat_shell(context)
        p.page.show()
        p.avatar_card.show()                               # what SessionController.resizeEvent does on every resize
        QTest.qWait(30)
        self.assertTrue(p.avatar_card.isHidden())
        p.page.close()

    def test_sidebar_is_widened_and_gets_a_footer(self):
        context, p = build()
        chat_shell.apply_chat_shell(context)
        self.assertEqual(p.sidebar.maximumWidth(), chat_shell.SIDEBAR_WIDTH)
        self.assertFalse(context.views.conversation_list.alternatingRowColors())
        self.assertIsNotNone(p.sidebar.findChild(QFrame, "sidebarProfile"))
        p.sidebar.findChild(QPushButton, "sidebarSettingsButton").click()
        self.assertEqual(p.opened, [1])

    def test_delete_button_deletes_the_open_conversation(self):
        context, p = build()
        chat_shell.apply_chat_shell(context)
        p.sidebar.findChild(QPushButton, "sidebarDeleteButton").click()
        self.assertEqual(p.deleted, ["c1"])

    def test_skin_survives_the_theme_replacing_the_stylesheet(self):
        context, p = build()
        chat_shell.apply_chat_shell(context)
        p.session.apply_chat_theme()
        sheet = p.page.styleSheet()
        self.assertIn("THEME", sheet)
        self.assertIn("conversationSidebar", sheet)
        self.assertLess(sheet.index("THEME"), sheet.index("conversationSidebar"))   # the skin is last, so it wins

    def test_active_row_gets_time_and_dot_after_every_rebuild(self):
        context, p = build()
        chat_shell.apply_chat_shell(context)
        for _ in range(2):
            p.session.refresh_conversation_list()
            row = p.list.itemWidget(p.list.item(0))
            self.assertEqual(row.findChild(QLabel, "conversationTime").text(), "16:32")
            self.assertEqual(len(row.findChildren(QLabel, "conversationDot")), 1)

    def test_applying_twice_changes_nothing(self):
        context, p = build()
        chat_shell.apply_chat_shell(context)
        chat_shell.apply_chat_shell(context)
        self.assertEqual(len(p.header.findChildren(QToolButton, "avatarPanelToggle")), 1)
        self.assertEqual(len(p.sidebar.findChildren(QFrame, "sidebarFooter")), 1)


if __name__ == "__main__":
    unittest.main()
