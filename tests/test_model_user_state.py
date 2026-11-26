"""The model reports the user's state with an optional [user:state] reply tag (no extra request)."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from kira import mood
from kira.emotion.director import EmotionDirector
from kira.emotion.parser import USER_STATE_TAGS, extract_user_states
from kira.emotion.runtime import EmotionalRuntime


class ParserTests(unittest.TestCase):
    def setUp(self):
        self.director = EmotionDirector.from_default()

    def test_tags_match_the_states_the_mood_engine_knows(self):
        self.assertEqual(set(USER_STATE_TAGS), set(mood.USER_STATES))

    def test_tag_is_removed_from_visible_text_and_returned(self):
        meta = self.director.parse_reply("[shy:50]\n[user:down]\nبیا بغلم، چی شده؟")
        self.assertEqual(meta.user_states, ["down"])
        self.assertNotIn("user", meta.text.lower())
        self.assertTrue(meta.text.startswith("بیا بغلم"))
        self.assertEqual(meta.emotions, ["shy"])

    def test_same_line_multiple_unknown_and_none_cases(self):
        self.assertEqual(self.director.parse_reply("[happy:40] [user:praise+thanks] ممنون").user_states, ["praise", "thanks"])
        meta = self.director.parse_reply("[happy:40]\n[user:banana]\nسلام")
        self.assertEqual(meta.user_states, [])
        self.assertEqual(meta.text, "سلام")
        self.assertEqual(self.director.parse_reply("[happy:40]\nسلام").user_states, [])

    def test_partial_tag_never_flashes_while_streaming(self):
        for partial in ("سلام [u", "سلام [us", "سلام [user", "سلام [user:do"):
            text, states = extract_user_states(partial)
            self.assertEqual(text.strip(), "سلام", partial)
            self.assertEqual(states, [])

    def test_normal_brackets_are_untouched(self):
        text, states = extract_user_states("برنامه [نسخه 2] و [users] فعال است")
        self.assertEqual(text, "برنامه [نسخه 2] و [users] فعال است")
        self.assertEqual(states, [])

    def test_hint_documents_the_tag(self):
        self.assertIn("[user:state]", self.director.format_hint())


class MoodTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        path = Path(self.temp.name) / "kira_mood.json"
        runtime = EmotionalRuntime(path=Path(self.temp.name) / "runtime.json", clock=lambda: 1000.0)
        self.patches = [
            patch.object(mood, "_path", return_value=path), patch.object(mood, "_emotional_runtime", runtime),
            patch.object(mood, "_RUNTIME_CACHE", {"kira": runtime}), patch.object(mood, "_ACTIVE_CHARACTER_ID", "kira"),
            patch.object(mood, "_RUNTIME_MIGRATED_IDS", set()), patch.object(mood, "_runtime_migrated", False),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.temp.cleanup()

    def test_model_read_state_applies_at_reduced_strength(self):
        local = mood.on_user_message("خسته‌ام", now=1000)
        self.assertEqual(local, ["down"])
        self.assertEqual(mood.on_model_user_states(["down"], now=1000), [])          # already found locally: no double count
        self.assertEqual(mood.on_model_user_states(["stressed", "banana"], now=1000), ["stressed"])
        self.assertIn("stressed", mood.current(now=1000)["user_states"])

    def test_model_state_alone_changes_the_feeling_less_than_a_keyword_match(self):
        mood.on_user_message("سلام", now=1000)
        mood.on_model_user_states(["down"], now=1000)
        weak = mood._runtime_for().snapshot(1000)["emotions"]
        mood.reset()
        mood.on_user_message("دلم گرفته", now=1000)
        strong = mood._runtime_for().snapshot(1000)["emotions"]
        self.assertGreater(dict(weak).get("protective", 0), 0)
        self.assertLess(dict(weak).get("protective", 0), dict(strong).get("protective", 0))

    def test_empty_or_unknown_is_a_noop(self):
        self.assertEqual(mood.on_model_user_states([], now=1000), [])
        self.assertEqual(mood.on_model_user_states(["x"], now=1000), [])


if __name__ == "__main__":
    unittest.main()
