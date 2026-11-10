import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from kira import mood


class MoodStateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "kira_mood.json"
        self.path_patch = patch.object(mood, "_path", return_value=self.path)
        self.path_patch.start()

    def tearDown(self):
        self.path_patch.stop()
        self.temp.cleanup()

    def test_joke_updates_emotion_and_behavior_separately(self):
        detected = mood.on_user_message("🤣🤣", now=1000)
        state = mood.current(now=1000)

        self.assertIn("joke", detected)
        self.assertGreater(state["behavior_scores"]["playful"], mood.BEHAVIOR_REST["playful"])
        self.assertGreaterEqual(state["energy"], 0)
        self.assertIn("behavior", state)

    def test_energy_recovers_during_idle_time(self):
        mood.on_user_message("سلام", now=1000)
        before = mood.current(now=1000)["energy"]
        after = mood.current(now=4600)["energy"]

        self.assertGreater(after, before)
        self.assertLessEqual(after, 100)

    def test_reply_can_set_new_primary_emotion_and_behavior(self):
        mood.on_reply(["fearful"], intensity=70, now=1000)
        state = mood.current(now=1000)

        self.assertEqual(state["emotion"], "fearful")
        self.assertGreater(state["behavior_scores"].get("reserved", 0), 0)

    def test_legacy_mood_file_loads_with_safe_defaults(self):
        self.path.write_text(json.dumps({
            "scores": {"happy": 42},
            "updated": 1000,
            "last_chat": 1000,
            "user_states": [],
            "away_hours": 0,
        }), encoding="utf-8")

        state = mood.current(now=1000)

        self.assertEqual(state["emotion"], "happy")
        self.assertEqual(state["energy"], int(round(mood.ENERGY_START)))
        self.assertIn("playful", state["behavior_scores"])

    def test_strict_prompt_does_not_expose_mood_state(self):
        self.assertEqual(mood.build_block("strict", now=1000), "")


if __name__ == "__main__":
    unittest.main()
