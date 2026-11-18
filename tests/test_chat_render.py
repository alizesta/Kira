import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from tests import helpers  # noqa: F401
from kira.chat_render import detect_direction, message_html

try:
    from PySide6.QtWidgets import QApplication, QTextEdit
    from PySide6.QtCore import Qt
    APP = QApplication.instance() or QApplication([])
    HAVE_QT = True
except Exception:                       # pragma: no cover
    HAVE_QT = False


class CodeRenderingTests(unittest.TestCase):
    def test_fenced_code_is_a_ltr_monospace_block_in_normal_replies(self):
        html_out = message_html("assistant", "Kira", "این را امتحان کن:\n```python\nif a < b:\n    print('x')\n```\nتمام")
        self.assertIn("if a &lt; b:", html_out)
        self.assertIn("Consolas", html_out)
        self.assertNotIn("```", html_out)
        self.assertEqual(html_out.count("<pre"), 1)

    def test_streaming_partial_fence_does_not_break_the_bubble(self):
        html_out = message_html("assistant", "Kira", "ببین:\n```py\nprint(1)")
        self.assertIn("print(1)", html_out)
        self.assertEqual(html_out.count("<pre"), 1)
        self.assertEqual(message_html("assistant", "Kira", "ببین ```py").count("<pre"), 0)     # no newline yet: still plain text

    def test_inline_code_is_styled_and_escaped(self):
        html_out = message_html("assistant", "Kira", "از `a<b` استفاده کن")
        self.assertIn("a&lt;b", html_out)
        self.assertNotIn("`", html_out)

    def test_text_without_code_is_unchanged(self):
        self.assertNotIn("<pre", message_html("assistant", "Kira", "سلام\nخوبی؟"))


class DirectionTests(unittest.TestCase):
    def test_detect_direction(self):
        self.assertEqual(detect_direction("سلام، حالت چطوره؟"), "rtl")
        self.assertEqual(detect_direction("How are you?"), "ltr")
        self.assertEqual(detect_direction("Python یک زبان برنامه‌نویسی است"), "rtl")   # Persian sentence with an English word
        self.assertEqual(detect_direction("123 !!!", "rtl"), "rtl")                    # no letters: UI default
        self.assertEqual(detect_direction("", "ltr"), "ltr")

    def test_html_is_escaped(self):
        h = message_html("assistant", "Kira", "<b>سلام</b> & <script>x</script>")
        self.assertNotIn("<script>", h)
        self.assertIn("&lt;b&gt;", h)
        self.assertIn("&amp;", h)

    def test_each_line_has_own_direction_and_name_follows_first_line(self):
        h = message_html("assistant", "Kira", "سلام\nHello there")
        self.assertEqual(h.count('dir="rtl"'), 2)        # name + first (Persian) line
        self.assertEqual(h.count('dir="ltr"'), 1)        # English line
        self.assertEqual(message_html("user", "تو", "Hello").count('dir="ltr"'), 2)   # Persian name, English text: both left

    def test_user_bubble_right_and_kira_left(self):
        self.assertIn('align="right" width', message_html("user", "تو", "سلام"))
        self.assertIn('align="left" width', message_html("assistant", "Kira", "سلام"))


@unittest.skipUnless(HAVE_QT, "PySide6 not installed")
class QtLayoutTests(unittest.TestCase):
    def blocks(self, kind, text):
        w = QTextEdit()
        w.setLayoutDirection(Qt.RightToLeft)
        w.append(message_html(kind, "Kira", text))
        out, b = [], w.document().begin()
        while b.isValid():
            if b.text().strip("\u00a0 "):
                out.append((b.text(), b.blockFormat().layoutDirection(), b.blockFormat().alignment()))
            b = b.next()
        return out

    def test_persian_blocks_are_rtl_and_right_aligned_even_when_widget_is_ltr(self):
        w = QTextEdit()
        w.setLayoutDirection(Qt.LeftToRight)
        w.append(message_html("assistant", "Kira", "سلام، این یک جمله‌ی فارسی است."))
        found = [b for b in self._iter(w) if "فارسی" in b.text()][0]
        self.assertEqual(found.blockFormat().layoutDirection(), Qt.RightToLeft)
        self.assertTrue(found.blockFormat().alignment() & Qt.AlignRight)

    def test_english_blocks_stay_ltr(self):
        w = QTextEdit()
        w.setLayoutDirection(Qt.RightToLeft)
        w.append(message_html("user", "تو", "This is English."))
        found = [b for b in self._iter(w) if "English" in b.text()][0]
        self.assertEqual(found.blockFormat().layoutDirection(), Qt.LeftToRight)
        self.assertTrue(found.blockFormat().alignment() & Qt.AlignLeft)

    @staticmethod
    def _iter(w):
        b = w.document().begin()
        while b.isValid():
            yield b
            b = b.next()


if __name__ == "__main__":
    unittest.main()


class BubbleSourceTests(unittest.TestCase):
    def test_bubble_and_tray_wiring_present(self):
        from pathlib import Path
        root = Path(__file__).resolve().parents[1] / "kira"
        from tests.ui_helpers import main_window_source
        main = main_window_source()
        comp = (root / "companion.py").read_text(encoding="utf-8")
        for needle in ("refresh_tray_menu", "tray_toggle_mic", "update_bubble", "bubble.commit_live", "تعویض مدل"):
            self.assertIn(needle, main)
        self.assertIn("class CompanionBubble", comp)
