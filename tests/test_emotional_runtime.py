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


if __name__ == "__main__":
    unittest.main()
