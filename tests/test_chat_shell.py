import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import (
    QApplication, QBoxLayout, QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton, QScrollArea,
    QToolButton, QVBoxLayout, QWidget,
)

from kira.ui import chat_shell

_APP = QApplication.instance() or QApplication([])


def build(lang="en"):
    """The widget structure VoiceSettingsController.build_chat_tab() creates, reduced to what the skin touches."""
    page = QWidget()
    outer = QVBoxLayout(page)
    tabs = QFrame()
    tabs_row = QHBoxLayout(tabs)
    outer.addWidget(tabs)
    body = QHBoxLayout()
    outer.addLayout(body, 1)
    avatar_card = QFrame()
    QVBoxLayout(avatar_card)
    body.addWidget(avatar_card)
    area = QWidget(page)
    area_layout = QHBoxLayout(area)
    body.addWidget(area, 1)
    sidebar = QFrame(area)
    sidebar.setFixedWidth(154)
    conversation_list = QListWidget(sidebar)
    QVBoxLayout(sidebar).addWidget(conversation_list, 1)
    chat_card = QFrame(area)
    area_layout.addWidget(sidebar)
    area_layout.addWidget(chat_card, 1)

    calls = SimpleNamespace(tabs=[], mood={"emotion": "calm", "behavior": "relaxed"})

    def refresh_conversation_list():
        """Like SessionController.refresh_conversation_list: rebuilds one active row with an options button."""
        conversation_list.clear()
        item = QListWidgetItem()
        item.setToolTip("Last activity: 2026-11-27 16:32:10")
        conversation_list.addItem(item)
        row = QWidget(conversation_list)
        row.setProperty("active", True)
        row_layout = QHBoxLayout(row)
        row_layout.addWidget(QPushButton("chat", row), 1)
        row_layout.addWidget(QToolButton(row), 0)
        conversation_list.setItemWidget(item, row)

    session = SimpleNamespace(
        go_tab=calls.tabs.append,
        apply_chat_theme=lambda: page.setStyleSheet("THEME { color: red; }"),
        refresh_conversation_list=refresh_conversation_list,
        refresh_tab_buttons=lambda: None,
        update_mood_indicator=lambda: None,
    )

    def missing_avatar(profile, root):
        raise FileNotFoundError

    character_service = SimpleNamespace(
        all_profiles=lambda settings: {}, display_name=lambda settings: "Kira", avatar_file=missing_avatar,
    )
    status = QLabel()
    views = SimpleNamespace(
        chat_page=page, avatar_card=avatar_card, char_tabs_row=tabs_row, conversation_list=conversation_list,
        char_tab_buttons={"kira": QPushButton("Kira")}, status=status, tab_keys=["tab_chat", "tab_general"],
    )
    context = SimpleNamespace(
        views=views,
        state=SimpleNamespace(cur=SimpleNamespace(cid="kira")),
        services=SimpleNamespace(
            settings={"ui_lang": lang}, character_service=character_service,
            mood_service=SimpleNamespace(current=lambda character_id="": dict(calls.mood)),
        ),
        controllers=SimpleNamespace(require=lambda name: session),
    )
    return context, SimpleNamespace(
        page=page, tabs=tabs, tabs_row=tabs_row, body=body, avatar_card=avatar_card, area=area, area_layout=area_layout,
        sidebar=sidebar, chat_card=chat_card, session=session, list=conversation_list, status=status, calls=calls,
    )


def texts(widget):
    return [label.text() for label in widget.findChildren(QLabel)]


class ChatShellTests(unittest.TestCase):
    def test_missing_chat_page_is_a_no_op(self):
        context = SimpleNamespace(views=SimpleNamespace(), services=SimpleNamespace(settings={}), controllers=None)
        self.assertFalse(chat_shell.apply_chat_shell(context))

    def test_three_columns_are_built_from_the_existing_widgets(self):
        context, p = build()
        self.assertTrue(chat_shell.apply_chat_shell(context))
        left = p.area.findChild(QScrollArea, "dashLeftScroll")
        center = p.area.findChild(QWidget, "dashCenter")
        self.assertIsNotNone(left)
        self.assertEqual(p.area_layout.count(), 2)
        self.assertTrue(left.isAncestorOf(p.tabs))             # Quick People = the character tabs
        self.assertTrue(left.isAncestorOf(p.sidebar))          # conversations stay reachable
        self.assertIs(p.chat_card.parentWidget(), center)
        self.assertEqual(p.tabs_row.direction(), QBoxLayout.Direction.TopToBottom)
        self.assertEqual(p.sidebar.maximumWidth(), 16777215)

    def test_english_layout_puts_the_character_panel_on_the_right(self):
        context, p = build("en")
        chat_shell.apply_chat_shell(context)
        self.assertIs(p.body.itemAt(p.body.count() - 1).widget(), p.avatar_card)

    def test_persian_layout_keeps_shell_ltr_and_character_panel_on_the_right(self):
        context, p = build("fa")
        chat_shell.apply_chat_shell(context)
        self.assertIs(p.body.itemAt(p.body.count() - 1).widget(), p.avatar_card)
        self.assertEqual(p.area_layout.direction(), QBoxLayout.Direction.LeftToRight)

    def test_navigation_opens_real_tabs_and_marks_the_rest_as_coming_soon(self):
        context, p = build()
        chat_shell.apply_chat_shell(context)
        buttons = {b.text().strip(): b for b in p.page.findChildren(QPushButton, "navItem")}
        self.assertTrue(buttons["Chat"].isChecked())
        buttons["Settings"].click()
        self.assertEqual(p.calls.tabs, [1])
        self.assertTrue(buttons["Chat"].isChecked())           # the chat page stays the current page
        buttons["Memories"].click()
        self.assertEqual(p.status.text(), "Coming soon")

    def test_display_only_widgets_say_coming_soon(self):
        context, p = build()
        chat_shell.apply_chat_shell(context)
        for name in ("dashAction",):
            p.status.clear()
            p.page.findChildren(QPushButton, name)[0].click()
            self.assertEqual(p.status.text(), "Coming soon", name)

    def test_greeting_follows_the_time_of_day(self):
        self.assertEqual(chat_shell.greeting_text("en", 8), "Good morning, darling")
        self.assertEqual(chat_shell.greeting_text("en", 19), "Good evening, darling")
        self.assertEqual(chat_shell.greeting_text("en", 2), "Good night, darling")
        self.assertEqual(chat_shell.greeting_text("fa", 19), "عصر بخیر، عزیزم")

    def test_skin_survives_the_theme_replacing_the_stylesheet(self):
        context, p = build()
        chat_shell.apply_chat_shell(context)
        p.session.apply_chat_theme()
        sheet = p.page.styleSheet()
        self.assertLess(sheet.index("THEME"), sheet.index("navItem"))      # the skin is last, so it wins

    def test_active_row_gets_time_and_dot_after_every_rebuild(self):
        context, p = build()
        chat_shell.apply_chat_shell(context)
        for _ in range(2):
            p.session.refresh_conversation_list()
            row = p.list.itemWidget(p.list.item(0))
            self.assertEqual(row.findChild(QLabel, "conversationTime").text(), "16:32")
            self.assertEqual(len(row.findChildren(QLabel, "conversationDot")), 1)

    def test_mood_card_follows_the_real_mood(self):
        context, p = build()
        chat_shell.apply_chat_shell(context)
        p.calls.mood = {"emotion": "happy", "behavior": "energetic"}
        p.session.update_mood_indicator()
        self.assertIn("Happy", texts(p.avatar_card))
        self.assertIn("Energetic", texts(p.avatar_card))

    def test_applying_twice_changes_nothing(self):
        context, p = build()
        chat_shell.apply_chat_shell(context)
        chat_shell.apply_chat_shell(context)
        self.assertEqual(len(p.area.findChildren(QScrollArea, "dashLeftScroll")), 1)
        self.assertEqual(p.area_layout.count(), 2)


if __name__ == "__main__":
    unittest.main()
