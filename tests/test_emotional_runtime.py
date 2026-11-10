import tempfile
import unittest
from pathlib import Path

from kira.emotion.library import Library
from kira.emotion.runtime import EmotionalRuntime


class EmotionalRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "emotional.json"
        self.library = Library.load()
        self.runtime = EmotionalRuntime(self.library, self.path, clock=lambda: 1000.0)

    def tearDown(self):
        self.temp.cleanup()

    def test_user_signal_updates_separate_emotion_and_behavior_layers(self):
        state = self.runtime.on_user_message("I am stressed", ["stressed"], now=1000)
        self.assertGreater(state["emotions"]["protective"], 0)
        self.assertGreater(dict(state["behaviors"])["focused"], 0)
        self.assertIn("relationship", state)

    def test_relationship_changes_slowly_and_is_bounded(self):
        before = self.runtime.snapshot(now=1000)["relationship"]["closeness"]
        for i in range(100):
            self.runtime.on_user_message("thanks", ["thanks"], now=1001 + i)
        after = self.runtime.snapshot(now=1100)["relationship"]["closeness"]
        self.assertGreater(after, before)
        self.assertLessEqual(after, 100)

    def test_emotional_memory_persists_across_runtime_instances(self):
        self.runtime.on_user_message("I'm worried", ["stressed"], now=1000)
        restored = EmotionalRuntime(self.library, self.path, clock=lambda: 1001.0)
        self.assertTrue(restored.snapshot(now=1001)["memories"])

    def test_energy_recovers_with_time_and_stays_bounded(self):
        self.runtime.on_user_message("hello", [], now=1000)
        low = self.runtime.snapshot(now=1000)["energy"]
        high = self.runtime.snapshot(now=50000)["energy"]
        self.assertGreaterEqual(high, low)
        self.assertLessEqual(high, 100)

    def test_combination_rules_are_shared_with_avatar_library(self):
        self.runtime.on_reply(["angry"], 80, now=1000)
        self.runtime.on_reply(["affectionate"], 80, now=1001)
        state = self.runtime.snapshot(now=1001)
        self.assertEqual(state["emotion"], "tsundere")

    def test_strict_mode_does_not_leak_emotional_context(self):
        self.assertEqual(self.runtime.build_prompt("strict", now=1000), "")

    def test_events_are_recorded_without_a_provider(self):
        state = self.runtime.trigger("response_failed", "offline provider", now=1000)
        self.assertEqual(state["recent_events"][-1]["name"], "response_failed")
        self.assertGreater(state["emotions"].get("frustrated", 0), 0)

    def test_replace_combination_preserves_underlying_emotional_components(self):
        self.runtime.on_reply(["angry"], 80, now=1000)
        self.runtime.on_reply(["affectionate"], 80, now=1001)
        state = self.runtime.snapshot(now=1001)
        self.assertEqual(state["emotion"], "tsundere")
        self.assertEqual({name for name, _ in state["emotional_components"]}, {"angry", "affectionate"})

    def test_bittersweet_emotions_can_coexist(self):
        self.runtime.on_reply(["happy"], 80, now=1000)
        self.runtime.on_reply(["sad"], 72, now=1001)
        state = self.runtime.snapshot(now=1001)
        self.assertEqual({name for name, _ in state["emotional_components"]}, {"happy", "sad"})

    def test_memory_recall_prefers_matching_user_experience(self):
        self.runtime.on_user_message("فردا امتحان مهم دارم و نگرانم", ["stressed"], now=1000)
        self.runtime.on_user_message("برای سفر جدید خیلی هیجان دارم", ["excited"], now=2000)
        state = self.runtime.snapshot(now=2001, query="امتحان فردا")
        self.assertTrue(state["recalled_memories"])
        self.assertIn("امتحان", state["recalled_memories"][0]["text"])

    def test_personality_learning_requires_repeated_explicit_feedback(self):
        before = self.runtime.snapshot(now=1000)["personality_traits"]["teasing"]
        self.runtime.observe_feedback("liked_teasing", "این شوخی خوب بود", now=1000)
        first = self.runtime.snapshot(now=1000)["personality_traits"]["teasing"]
        self.assertEqual(first, before)
        self.runtime.observe_feedback("liked_teasing", "همین لحن را دوست دارم", now=1000 + 9 * 3600)
        learned = self.runtime.snapshot(now=1000 + 9 * 3600)["personality_traits"]["teasing"]
        self.assertGreater(learned, before)
        self.assertLessEqual(learned, 0.80)

    def test_personality_learning_is_bounded_and_persistent(self):
        now = 1000
        for i in range(40):
            now += 9 * 3600
            self.runtime.observe_feedback("disliked_teasing", "شوخی نکن", now=now)
        learned = self.runtime.snapshot(now=now)["personality_traits"]["teasing"]
        self.assertGreaterEqual(learned, 0.56)
        restored = EmotionalRuntime(self.library, self.path, clock=lambda: now + 1)
        self.assertAlmostEqual(restored.snapshot(now=now + 1)["personality_traits"]["teasing"], learned)

    def test_relationship_tension_recovers_gradually(self):
        self.runtime.on_user_message("خفه شو", ["hostile"], now=1000)
        before = self.runtime.snapshot(now=1000)["relationship"]["tension"]
        after = self.runtime.snapshot(now=1000 + 86400)["relationship"]["tension"]
        self.assertLess(after, before)

    def test_last_initiative_and_memory_id_are_persistent(self):
        self.runtime.mark_initiative_sent(memory_id="exam-123", now=1000)
        restored = EmotionalRuntime(self.library, self.path, clock=lambda: 1001)
        state = restored.snapshot(now=1001)
        self.assertEqual(state["last_initiative"], 1000)
        self.assertEqual(state["last_initiative_memory_id"], "exam-123")


if __name__ == "__main__":
    unittest.main()
