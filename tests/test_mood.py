import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from kira import mood
from kira.emotion.runtime import EmotionalRuntime


class MoodStateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "kira_mood.json"
        self.path_patch = patch.object(mood, "_path", return_value=self.path)
        self.path_patch.start()
        runtime = EmotionalRuntime(path=self.path, clock=lambda: 1000.0)
        self.runtime_patch = patch.object(mood, "_emotional_runtime", runtime)
        self.runtime_patch.start()
        self.runtime_cache_patch = patch.object(mood, "_RUNTIME_CACHE", {"kira": runtime})
        self.runtime_cache_patch.start()
        self.active_character_patch = patch.object(mood, "_ACTIVE_CHARACTER_ID", "kira")
        self.active_character_patch.start()
        self.migrated_ids_patch = patch.object(mood, "_RUNTIME_MIGRATED_IDS", set())
        self.migrated_ids_patch.start()
        self.migrated_patch = patch.object(mood, "_runtime_migrated", False)
        self.migrated_patch.start()

    def tearDown(self):
        self.migrated_ids_patch.stop()
        self.active_character_patch.stop()
        self.runtime_cache_patch.stop()
        self.migrated_patch.stop()
        self.runtime_patch.stop()
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

    def test_repeated_explicit_style_feedback_teaches_personality_slowly(self):
        initial = mood.current(now=1000)["personality_traits"]["teasing"]
        mood.on_user_message("این شوخی خوب بود", now=1000)
        first = mood.current(now=1000)["personality_traits"]["teasing"]
        self.assertEqual(first, initial)
        mood.on_user_message("همین لحن شوخ رو دوست دارم", now=1000 + 9 * 3600)
        later = mood.current(now=1000 + 9 * 3600)["personality_traits"]["teasing"]
        self.assertGreater(later, initial)

    def test_mood_prompt_recalls_memories_relevant_to_the_current_message(self):
        mood.on_user_message("فردا امتحان مهم دارم و نگرانم", now=1000)
        mood.on_user_message("برای سفر کیش خیلی هیجان دارم", now=1001)
        block = mood.build_block("chat", now=1002, query="امتحان فردا")
        self.assertIn("فردا امتحان", block)
        self.assertNotIn("سفر کیش", block)

    def test_mood_prompt_has_one_authoritative_emotion_and_energy_snapshot(self):
        mood.on_user_message("فردا امتحان مهم دارم و نگرانم", now=1000)

        block = mood.build_block("chat", now=1000, query="امتحان")

        self.assertEqual(block.count("Persistent emotional state:"), 1)
        self.assertEqual(block.count("Energy:"), 1)
        self.assertNotIn("Mood now:", block)

    def test_reply_text_reaches_emotional_memory_through_legacy_facade(self):
        mood.on_reply(["sad"], intensity=70, now=1000, text="از اینکه تنها ماندی ناراحتم")

        state = mood.current(now=1000)

        self.assertTrue(state["emotional_memories"])
        self.assertIn("تنها", state["emotional_memories"][-1]["text"])


if __name__ == "__main__":
    unittest.main()
