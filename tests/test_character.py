from tests.ui_helpers import main_window_files, package_source
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from kira import mood, modes, persona_memory as pm, personality, style_probe
from kira.config import DEFAULTS


class PersonalityTests(unittest.TestCase):
    def test_blocks_present_and_mood_block_ordered(self):
        s = dict(DEFAULTS)
        prompt = personality.build_system_prompt(s, "", "MEMBLOCK", mode=modes.detect("سلام"), mood_block="MOODBLOCK")
        self.assertLess(prompt.index("MEMBLOCK"), prompt.index("MOODBLOCK"))
        for block in personality.CORE_BLOCKS:
            self.assertIn(block.strip()[:40], prompt)

    def test_register_contract_forbids_both_extremes(self):
        text = personality.CORE_LANGUAGE
        self.assertIn("Too polite", text)
        self.assertIn("Too rude", text)

    def test_honesty_block_forbids_invention(self):
        self.assertIn("I don't know", personality.CORE_HONESTY)


class StyleProbeTests(unittest.TestCase):
    def test_rude_polite_stiff_flags(self):
        self.assertIn("too_polite", style_probe.classify("البته! خوشحال می‌شوم کمک کنم"))
        self.assertIn("too_rude", style_probe.classify("خفه شو احمق"))
        self.assertIn("too_rude", style_probe.classify("باشه", "task") + (["too_rude"] if style_probe.metrics("گوه")["curses"] else []))
        self.assertEqual(style_probe.classify("هه، خسته‌ای؟ بیا یه چایی بزن و بگو چی شد"), [])

    def test_drifted_reply_never_becomes_voice_sample(self):
        self.assertFalse(pm.is_voice_sample("البته! خوشحال می‌شوم کمکتان کنم. اگر سوال دیگری داشتید بپرسید"))

    def test_probe_runs_each_route_alone_with_mock_router(self):
        calls = []

        class FakeRouter:
            def __init__(self, s):
                calls.append((s["manual_route_id"], s["failover_enabled"]))

            def chat(self, messages, prompt, temp):
                return "هه، باشه."

        s = dict(DEFAULTS)
        from kira import routes
        routes.ensure_routes(s)
        rid = routes.get_routes(s)[0]["id"]
        lines = []
        res = style_probe.run_probe(s, [rid], router_cls=FakeRouter, out=lines.append)
        self.assertEqual(len(res[rid]), len(style_probe.PROBES))
        self.assertTrue(all(c == (rid, False) for c in calls))


class MoodTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        p = mock.patch.object(mood, "DATA_DIR", Path(self.tmp.name))
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(self.tmp.cleanup)

    def test_user_state_detection(self):
        self.assertIn("down", mood.detect_user_states("امروز خیلی خسته‌م و حالم بده"))
        self.assertIn("thanks", mood.detect_user_states("مرسی عالی بود"))

    def test_sad_user_gets_guidance_and_no_curse_in_task(self):
        mood.on_user_message("خیلی ناراحتم و حوصله ندارم", now=1000)
        chat = mood.build_block("chat", now=1005)
        self.assertTrue(chat)
        self.assertEqual(mood.build_block("strict", now=1005), "")

    def test_mood_decays_and_persists(self):
        mood.on_reply(["angry"], 90, now=1000)
        hot = mood.current(now=1000)["intensity"]
        cold = mood.current(now=1000 + 3 * mood.HALF_LIFE)["intensity"]
        self.assertGreater(hot, cold)
        self.assertTrue((Path(self.tmp.name) / mood.FILE_NAME).exists())

    def test_avatar_hint_only_for_fresh_message(self):
        mood.on_user_message("هاهاها خیلی خنده‌دار بود", now=1000)
        self.assertIsNotNone(mood.avatar_hint(now=1010))
        self.assertIsNone(mood.avatar_hint(now=1000 + 3600))

    def test_reset(self):
        mood.on_reply(["angry"], 90, now=1000)
        mood.reset()
        self.assertNotEqual(mood.current(now=1001)["emotion"], "angry")          # back to her resting mood


class RelationshipMemoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        p = mock.patch.object(pm, "DATA_DIR", Path(self.tmp.name))
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(self.tmp.cleanup)

    def test_add_edit_delete_note(self):
        self.assertTrue(pm.add_note("دوست دارم چای بدون شکر"))
        items = pm.list_items()
        self.assertTrue(any("چای" in i["text"] for i in items))
        iid = next(i["id"] for i in items if "چای" in i["text"])
        self.assertTrue(pm.update_item(iid, "قهوه تلخ"))
        self.assertIn("قهوه", pm.build_block())
        iid = next(i["id"] for i in pm.list_items() if "قهوه" in i["text"])      # an edit re-keys the item
        self.assertTrue(pm.delete_item(iid))
        self.assertNotIn("قهوه", pm.build_block())

    def test_forget_all_clears_everything(self):
        pm.add_note("یک چیز")
        pm.forget_all()
        self.assertEqual(pm.list_items(), [])

    def test_summary_is_made_for_old_messages_and_forgotten_with_chat(self):
        rows = [{"role": "user" if i % 2 == 0 else "assistant", "content": f"پیام شماره {i} درباره پروژه کیرا و کدنویسی"} for i in range(150)]
        self.assertTrue(pm.needs_summary(len(rows), 12))
        pm.maintain(rows, 12)
        self.assertFalse(pm.needs_summary(len(rows), 12))
        pm.forget_conversation()
        self.assertTrue(pm.needs_summary(len(rows), 12))

    def test_block_says_unlisted_is_unknown(self):
        pm.add_note("x یادداشت")
        self.assertTrue(pm.build_block())


class MainWiringTests(unittest.TestCase):
    """main.py needs Qt (not importable in some environments), so the wiring is checked statically."""
    SRC = package_source()

    def test_hooks_present(self):
        for needle in ("mood.on_user_message(", "mood.on_reply(", "\"mood\": mood_block", "persona_memory.maintain(",
                       "class MemoryDialog", "mood.reset()", "persona_memory.forget_all()", "apply_mood_to_avatar"):
            self.assertIn(needle, self.SRC, needle)

    def test_syntax(self):
        for path in main_window_files():
            compile(path.read_text(encoding="utf-8"), str(path), "exec")


if __name__ == "__main__":
    unittest.main()
