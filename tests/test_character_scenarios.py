import tempfile
import unittest
from pathlib import Path

from kira.character.decision import BASE_TRAITS, DecisionEngine
from kira.emotion.library import Library
from kira.emotion.runtime import EmotionalRuntime


class CharacterScenarioTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.runtime = EmotionalRuntime(
            Library.load(), Path(self.temp.name) / "state.json", clock=lambda: 1000.0
        )
        self.decisions = DecisionEngine()

    def tearDown(self):
        self.temp.cleanup()

    def test_stress_then_recovery_and_playful_reconnection(self):
        stressed = self.runtime.on_user_message(
            "فردا امتحان مهم دارم و خیلی استرس دارم", ["stressed"], now=1000
        )
        initial = self.decisions.decide("امتحان دارم", stressed, "chat")
        self.assertIn(initial.behaviour, ("gentle", "focused", "protective", "quiet"))

        self.runtime.on_user_message("🤣🤣", ["joke"], now=1000 + 3600)
        self.runtime.on_reply(["laughing"], 68, now=1000 + 3601)
        later = self.runtime.snapshot(now=1000 + 3601)
        self.assertIn("laughing", later["emotions"])
        self.assertGreater(later["behavior_scores"].get("playful", 0), 0)
        self.assertTrue(later["memories"])

    def test_relationship_changes_slowly_over_many_turns(self):
        start = self.runtime.snapshot(now=1000)["relationship"]
        for i in range(100):
            self.runtime.on_user_message("ممنون، دمت گرم", ["thanks"], now=1001 + i * 60)
        end = self.runtime.snapshot(now=1001 + 99 * 60)["relationship"]
        self.assertGreater(end["closeness"], start["closeness"])
        self.assertLess(end["closeness"] - start["closeness"], 20)
        self.assertLessEqual(max(end.values()), 100)

    def test_feedback_adapts_style_without_erasing_core_identity(self):
        now = 1000
        for i in range(12):
            now += 9 * 3600
            self.runtime.observe_feedback("liked_teasing", "این شوخی خوب بود", now=now)
        state = self.runtime.snapshot(now=now)
        learned = state["personality_traits"]
        self.assertGreater(learned["teasing"], BASE_TRAITS["teasing"])
        self.assertLessEqual(learned["teasing"], BASE_TRAITS["teasing"] + 0.12)
        self.assertAlmostEqual(learned["empathy"], BASE_TRAITS["empathy"])

    def test_recalled_memory_is_relevant_to_current_topic(self):
        self.runtime.on_user_message("فردا امتحان مهمی دارم", ["stressed"], now=1000)
        self.runtime.on_user_message("برای سفر تابستانی هیجان دارم", ["excited"], now=2000)
        state = self.runtime.snapshot(now=2001, query="امتحان")
        self.assertTrue(state["recalled_memories"])
        self.assertIn("امتحان", state["recalled_memories"][0]["text"])

    def test_decision_is_repeatable_for_the_same_character_state(self):
        state = self.runtime.snapshot(now=1000)
        one = self.decisions.decide("سلام", state, "chat")
        two = self.decisions.decide("سلام", state, "chat")
        self.assertEqual(one.behaviour, two.behaviour)
        self.assertEqual(one.intensity, two.intensity)


if __name__ == "__main__":
    unittest.main()
