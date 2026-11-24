"""Progress lines are drawn inside the chat view and removed cleanly (no widget above the input)."""
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QTextBrowser

from kira.ui.components.kode_activity import KodeActivityPanel, apply_progress_to_view

APP = QApplication.instance() or QApplication([])


class InlineProgressTests(unittest.TestCase):
    def setUp(self):
        self.view = QTextBrowser()
        self.view.append("<p>پیام کاربر</p>")
        self.tracker = KodeActivityPanel()
        self.tracker.changed.connect(
            lambda: apply_progress_to_view(self.view, self.tracker.visible_rows(), True))

    def text(self):
        return self.view.toPlainText()

    def test_stages_are_written_in_the_chat_and_only_latest_three_are_shown(self):
        t = self.tracker
        t.start("در حال فکر کردن…")
        t.begin("در حال جست‌وجوی وب…", key="web")
        t.finish("web", "جست‌وجوی وب انجام شد")
        t.begin("در حال بررسی نتایج…")
        t.begin("در حال نوشتن پاسخ…")
        text = self.text()
        self.assertEqual(text.count("◌"), 1)
        self.assertEqual(text.count("✓"), 2)
        self.assertNotIn("در حال فکر کردن", text)
        self.assertIn("پیام کاربر", text)

    def test_removal_keeps_messages_before_and_after_the_progress_lines(self):
        t = self.tracker
        t.start("در حال فکر کردن…")
        self.view.append("<p>پیام وسط</p>")
        t.suspend()
        self.assertNotIn("◌", self.text())
        self.assertIn("پیام کاربر", self.text())
        self.assertIn("پیام وسط", self.text())

    def test_every_end_state_removes_the_lines(self):
        for end in (lambda t: t.complete("تمام"), lambda t: t.cancel("توقف"),
                    lambda t: t.fail("خطا"), lambda t: t.reset()):
            before = self.text()
            self.tracker.start("در حال فکر کردن…")
            self.assertIn("در حال فکر کردن", self.text())
            end(self.tracker)
            self.assertEqual(self.text(), before)

    def test_text_is_escaped(self):
        self.tracker.start("جست‌وجوی <b>وب</b>")
        self.assertIn("<b>وب</b>", self.text())


if __name__ == "__main__":
    unittest.main()
