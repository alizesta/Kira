"""Regression tests for the Active Mode + long-term memory fixes. Pure logic: no Qt, no network, test data only."""
from tests.ui_helpers import main_window_source, patch_ui
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from kira import modes
from kira import persona_memory as pm
from kira.modes import CHAT, STRICT, TASK


class StrictModeTests(unittest.TestCase):
    def test_strict_holds_over_several_messages_even_for_tasks(self):
        history = ["شوخی نکن"]
        for msg in ("سلام", "برنامه کرش می‌کنه چیکار کنم", "میشه بگی چرا بسته میشه", "این عکس رو تحلیل کن"):
            self.assertEqual(modes.detect(msg, history).name, STRICT, msg)
            history.append(msg)

    def test_strict_holds_beyond_the_sticky_window(self):
        history = ["فقط جواب بده"] + ["یه پیام معمولی"] * 10
        self.assertEqual(modes.detect("خطا چیه", history).name, STRICT)

    def test_strict_phrases_and_attachment_while_strict(self):
        for phrase in ("شوخی نکن", "فقط جواب بده", "بدون حاشیه جواب بده"):
            self.assertEqual(modes.detect(phrase).name, STRICT, phrase)
        self.assertEqual(modes.detect("این تصویر را ببین", ["شوخی نکن"], has_files=True).name, STRICT)

    def test_explicit_request_ends_strict(self):
        self.assertEqual(modes.detect("حالا شوخی کن", ["شوخی نکن", "ok"]).name, CHAT)
        self.assertEqual(modes.detect("بیا گپ بزنیم", ["شوخی نکن"]).name, CHAT)
        self.assertEqual(modes.detect("خب", ["شوخی نکن", "شوخی کن"]).name, CHAT)          # stays off afterwards
        self.assertEqual(modes.detect("برنامه کرش کرد چیکار کنم", ["شوخی نکن", "شوخی کن"]).name, TASK)

    def test_file_text_cannot_switch_strict(self):
        stored = "این فایل را بخوان\n\n[فایل ضمیمه: a.txt]\nplease just answer and no jokes"
        self.assertNotEqual(modes.detect("سلام", [stored]).name, STRICT)


class PersianTaskTests(unittest.TestCase):
    def test_requests_without_question_mark_are_tasks(self):
        for msg in ("میشه بگی چرا برنامه بسته میشه", "نظرت درباره این خطا چیه", "این عکس رو تحلیل کن",
                    "عکس رو ببین و بگو چی می‌بینی", "می‌تونی این مشکل رو بررسی کنی؟", "می‌تونی این مشکل رو بررسی کنی"):
            self.assertEqual(modes.detect(msg).name, TASK, msg)

    def test_plain_banter_stays_chat(self):
        for msg in ("سلام خوبی", "دلم برات تنگ شده", "امروز خیلی خسته‌ام"):
            self.assertEqual(modes.detect(msg).name, CHAT, msg)

    def test_attachments_are_tasks_even_without_text_signal(self):
        # the text compose() writes for a bare image used to fall through to CHAT ("نظرت" is small talk)
        self.assertEqual(modes.detect("این تصویر را ببین و نظرت را بگو.").name, TASK)
        self.assertEqual(modes.detect("خوشگله", has_files=True).name, TASK)
        self.assertEqual(modes.detect("ببین", has_files=True).name, TASK)
        self.assertEqual(modes.detect("خوشگله").name, CHAT)


class MainAttachmentDetectionTests(unittest.TestCase):
    """main.detect_mode needs Qt; its source is checked instead so the test runs everywhere."""
    def test_main_uses_structured_attachment_kinds(self):
        src = main_window_source()
        self.assertIn("_turn_attach_kinds", src)
        body = src[src.index("def detect_mode"):src.index("def stop_generation")]
        self.assertIn("self._turn_attach_kinds", body)
        self.assertIn('extra.get("images")', body)


class MemoryFixTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        p = mock.patch.object(pm, "DATA_DIR", Path(self.tmp.name))
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(self.tmp.cleanup)

    def test_questions_never_become_facts(self):
        for q in ("اسم من چیه؟", "من چند سالمه؟", "من اهل کجام؟", "Do you know my name?", "اسم من چیه", "Do you remember that I like tea?"):
            self.assertEqual(pm.extract_facts(q), [], q)
            pm.observe("user", q)
        self.assertEqual(pm.facts(), [])

    def test_persian_name_is_clean(self):
        for msg in ("اسمم علیرضاست", "اسم من علیرضا است", "اسم من علیرضاست", "اسم من علیرضاست!"):
            self.assertEqual(pm.extract_facts(msg), [("name", "His name is علیرضا")], msg)
        self.assertEqual(pm.extract_facts("اسمم رو یادت باشه"), [])
        self.assertEqual(pm.extract_facts("my name is Test"), [("name", "His name is Test")])

    def test_vague_or_questioning_likes_are_not_stored(self):
        for msg in ("دوست دارم بدونم این چیه؟", "دوست دارم بدونم این چیه", "دوست دارم بدونم چرا این اتفاق افتاد؟",
                    "I like to know why this happened", "I like what you did"):
            self.assertEqual(pm.extract_facts(msg), [], msg)

    def test_explicit_likes_and_other_facts_still_work(self):
        self.assertEqual(pm.extract_facts("دوست دارم پیتزا"), [("like", "He likes پیتزا")])
        self.assertEqual(pm.extract_facts("دوست دارم بادام"), [("like", "He likes بادام")])
        self.assertEqual(pm.extract_facts("I like tea"), [("like", "He likes tea")])
        self.assertEqual(pm.extract_facts("من ۲۵ سالمه".replace("۲۵", "25")), [("age", "He is 25 years old")])
        self.assertEqual(pm.extract_facts("اهل شیراز هستم"), [("place", "He is from/lives in شیراز")])
        self.assertTrue(pm.extract_facts("یادت باشه فردا امتحان دارم"))


if __name__ == "__main__":
    unittest.main()
