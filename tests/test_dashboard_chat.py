import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QLineEdit, QTextBrowser, QToolButton, QVBoxLayout, QWidget,
)

from kira.ui import dashboard_chat

_APP = QApplication.instance() or QApplication([])


class BubbleTests(unittest.TestCase):
    def test_assistant_bubble_has_avatar_text_and_time(self):
        html = dashboard_chat.bubble_html("assistant", "Hey there", "ltr", stamp="8:18 PM", avatar_url=dashboard_chat.AVATAR_URL)
        self.assertIn(dashboard_chat.AVATAR_URL, html)
        self.assertIn("Hey there", html)
        self.assertIn("8:18 PM", html)
        self.assertNotIn("✓✓", html)

    def test_user_bubble_is_right_aligned_with_double_tick(self):
        html = dashboard_chat.bubble_html("user", "Hey Kira", "ltr", stamp="8:18 PM")
        self.assertIn('align="right"', html)
        self.assertIn("✓✓", html)
        self.assertIn("#c4b5fd", html)

    def test_message_without_a_time_shows_no_time_and_no_tick(self):
        html = dashboard_chat.bubble_html("user", "old message", "ltr", stamp="")
        self.assertNotIn("✓✓", html)

    def test_text_is_escaped(self):
        self.assertIn("&lt;b&gt;", dashboard_chat.bubble_html("assistant", "<b>", "ltr"))

    def test_clock_text(self):
        self.assertEqual(dashboard_chat.clock_text(datetime(2026, 11, 27, 20, 18)), "8:18 PM")

    def test_installed_message_html_skips_the_time_while_history_is_painted(self):
        from kira.ui import main_window_session as session_module

        calls = []

        def original(*args):
            calls.append(args)
            return "ORIGINAL"

        controller = SimpleNamespace(_suppress_conversation_refresh=True)
        with mock.patch.object(session_module, "message_html", original):
            dashboard_chat._install_bubbles(controller)
            installed = session_module.message_html
            self.assertEqual(installed("system", "", "hi", "ltr"), "ORIGINAL")      # system/error keep the old look
            self.assertNotIn("✓✓", installed("user", "", "old", "ltr"))
            controller._suppress_conversation_refresh = False
            self.assertIn("✓✓", installed("user", "", "new", "ltr"))
            self.assertIn(dashboard_chat.AVATAR_URL, installed("assistant", "", "reply", "ltr"))


def context_with(**views):
    status = QLabel()
    return SimpleNamespace(
        views=SimpleNamespace(status=status, **views),
        state=SimpleNamespace(front=SimpleNamespace(cid="kira"), cur=SimpleNamespace(cid="kira")),
        services=SimpleNamespace(
            settings={"ui_lang": "en"},
            character_service=SimpleNamespace(display_name=lambda settings: "Kira"),
        ),
    ), status


class ComposerTests(unittest.TestCase):
    def build(self):
        surface = QFrame()
        layout = QVBoxLayout(surface)
        expand_host = QWidget(surface)
        expand = QToolButton(expand_host)
        QHBoxLayout(expand_host).addWidget(expand)
        layout.addWidget(expand_host)
        field = QLineEdit(surface)
        layout.addWidget(field, 1)
        bar = QHBoxLayout()
        layout.addLayout(bar)
        buttons = {name: QToolButton(surface) for name in (
            "route_badge", "attach_btn", "search_btn", "game_mode_btn", "mic_btn", "voice_btn", "gen_stop_btn", "send_btn")}
        for button in buttons.values():
            bar.addWidget(button)
        composer = SimpleNamespace(input_surface=surface, expand_btn=expand, attach_btn=buttons["attach_btn"])
        aliases = {k: v for k, v in buttons.items() if k != "attach_btn"}
        context, status = context_with(chat_composer=composer, input=field, **aliases)
        return context, SimpleNamespace(surface=surface, layout=layout, bar=bar, field=field, buttons=buttons,
                                        expand_host=expand_host, expand=expand, status=status)

    def test_composer_becomes_one_pill_and_the_old_toolbar_moves_into_a_tray(self):
        context, p = self.build()
        dashboard_chat._build_composer(context, "en")
        pill = p.layout.itemAt(0).layout()
        pill_widgets = [pill.itemAt(i).widget() for i in range(pill.count())]
        self.assertIn(p.field, pill_widgets)
        self.assertIn(p.buttons["send_btn"], pill_widgets)
        self.assertIn(p.buttons["attach_btn"], pill_widgets)
        tray = p.surface.findChild(QWidget, "composerTray")
        self.assertTrue(tray.isHidden())
        for name in ("route_badge", "search_btn", "game_mode_btn", "mic_btn", "voice_btn"):
            self.assertIs(p.buttons[name].parentWidget(), tray, name)
        self.assertIs(p.expand.parentWidget(), tray)
        self.assertTrue(p.expand_host.isHidden())

    def test_spark_button_opens_the_tray_and_emoji_is_display_only(self):
        context, p = self.build()
        dashboard_chat._build_composer(context, "en")
        tray = p.surface.findChild(QWidget, "composerTray")
        spark = p.surface.findChild(QToolButton, "sparkBtn")
        spark.setChecked(True)
        self.assertFalse(tray.isHidden())
        spark.setChecked(False)
        self.assertTrue(tray.isHidden())
        p.surface.findChild(QToolButton, "emojiBtn").click()
        self.assertEqual(p.status.text(), "Coming soon")


class HeaderTests(unittest.TestCase):
    def test_header_gets_the_today_chip_and_search_filter_icons(self):
        header = QFrame()
        layout = QHBoxLayout(header)
        title = QLabel("Project Kira", header)
        layout.addWidget(title)
        context, status = context_with(title=title)
        dashboard_chat._build_header(context, "en")
        self.assertTrue(title.isHidden())
        self.assertEqual(header.findChild(QLabel, "todayChip").text(), "Today")
        icons = header.findChildren(QToolButton, "headerIcon")
        self.assertEqual(len(icons), 2)
        icons[0].click()
        self.assertEqual(status.text(), "Coming soon")


class PortraitTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = mock.patch.object(dashboard_chat, "ROOT", self.tmp.name)
        patcher.start()
        self.addCleanup(patcher.stop)

    def build(self):
        card = QFrame()
        QVBoxLayout(card)
        avatar = QLabel("animated avatar", card)
        card.layout().addWidget(avatar)
        context, _status = context_with(avatar_card=card, avatar=avatar)
        return context, card, avatar

    def test_without_a_picture_the_animated_avatar_stays(self):
        context, card, avatar = self.build()
        parts = {}
        dashboard_chat._build_portrait(context, parts)
        self.assertIs(card.layout().itemAt(0).widget(), parts["portrait"])
        self.assertTrue(parts["portrait"].isHidden())
        self.assertFalse(avatar.isHidden())

    def test_with_a_picture_the_portrait_replaces_the_animated_avatar(self):
        folder = Path(self.tmp.name) / "assets" / "dashboard"
        folder.mkdir(parents=True)
        picture = QPixmap(40, 60)
        picture.fill()
        self.assertTrue(picture.save(str(folder / "kira_portrait.png")))
        context, card, avatar = self.build()
        parts = {}
        dashboard_chat._build_portrait(context, parts)
        self.assertFalse(parts["portrait"].isHidden())
        self.assertTrue(avatar.isHidden())


class TypingAndBubbleRenderTests(unittest.TestCase):
    def test_typing_indicator_is_hidden_until_active_and_stops_cleanly(self):
        host = QFrame()
        host_layout = QVBoxLayout(host)
        composer = QFrame(host)
        host_layout.addWidget(composer)
        context, _status = context_with(chat_composer=composer)
        parts = {}

        dashboard_chat._build_typing(context, "fa", parts)
        typing = parts["typing"]
        self.assertTrue(typing.isHidden())

        typing.set_active(True)
        self.assertFalse(typing.isHidden())
        self.assertTrue(typing._timer.isActive())

        typing.set_active(False)
        self.assertTrue(typing.isHidden())
        self.assertFalse(typing._timer.isActive())

    def test_bubble_underlay_installs_and_paints_rounded_message_tables(self):
        view = QTextBrowser()
        view.resize(640, 480)
        dashboard_chat._install_underlay(view)
        view.setHtml(dashboard_chat.bubble_html(
            "user", "سلام کیرا", "rtl", stamp="8:18 PM"
        ))
        view.show()
        _APP.processEvents()

        tables = list(dashboard_chat._bubble_tables(view.document().rootFrame()))
        self.assertEqual(len(tables), 1)
        self.assertIsNotNone(dashboard_chat._content_rect(
            view.document(), view.document().documentLayout(), tables[0]
        ))
        self.assertIsNotNone(view._kira_underlay)
        view.repaint()
        _APP.processEvents()
        view.close()


class DateChipTests(unittest.TestCase):
    def test_first_message_of_a_conversation_starts_under_today(self):
        view = QTextBrowser()
        added = []
        controller = SimpleNamespace(add_chat=lambda kind, text, name=None, images=None: added.append((kind, text)))
        context = SimpleNamespace(session=SimpleNamespace(view=view))
        dashboard_chat._wrap_date_chip(context, controller, "en")
        controller.add_chat("assistant", "hello")
        self.assertIn("Today", view.toPlainText())
        view.append("hello")
        before = view.toPlainText()
        controller.add_chat("user", "again")
        self.assertEqual(view.toPlainText(), before)             # the chip is added only while the view is empty
        self.assertEqual(added, [("assistant", "hello"), ("user", "again")])


if __name__ == "__main__":
    unittest.main()
