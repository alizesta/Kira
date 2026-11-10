import unittest

from kira.character.decision import BASE_TRAITS, DecisionEngine
from kira.character.initiative import InitiativeEngine


class CharacterDecisionTests(unittest.TestCase):
    def setUp(self):
        self.engine = DecisionEngine()

    def test_stable_traits_do_not_change_with_mood(self):
        first = self.engine.decide("hello", {"emotion": "happy"})
        second = self.engine.decide("hello", {"emotion": "sad"})
        self.assertEqual(first.traits, second.traits)
        self.assertEqual(first.traits, BASE_TRAITS)

    def test_sensitive_context_suppresses_playful_behaviour(self):
        decision = self.engine.decide("من خیلی افسرده‌ام و حالم بده", {"emotion": "happy"})
        self.assertTrue(decision.serious_context)
        self.assertIn(decision.behaviour, ("gentle", "protective", "quiet"))

    def test_task_mode_prefers_focus(self):
        decision = self.engine.decide("یک فایل بساز", {"emotion": "happy"}, "task")
        self.assertEqual(decision.behaviour, "focused")

    def test_emotion_and_behaviour_are_independent_inputs(self):
        decision = self.engine.decide("hello", {"emotion": "jealous", "behaviors": [("tsundere", 90)]})
        self.assertEqual(decision.behaviour, "tsundere")

    def test_energy_can_reduce_playfulness(self):
        rested = self.engine.decide("hello", {"emotion": "happy", "energy": 90})
        tired = self.engine.decide("hello", {"emotion": "happy", "energy": 10})
        self.assertNotEqual(rested.behaviour, tired.behaviour)


class InitiativeTests(unittest.TestCase):
    def test_initiative_requires_opt_in_and_relevant_memory(self):
        engine = InitiativeEngine()
        self.assertFalse(engine.evaluate(now=10000, last_interaction=1, enabled=False, has_relevant_memory=True)["eligible"])
        self.assertFalse(engine.evaluate(now=10000, last_interaction=1, enabled=True, has_relevant_memory=False)["eligible"])
        self.assertTrue(engine.evaluate(now=10000, last_interaction=1, enabled=True, has_relevant_memory=True)["eligible"])

    def test_busy_and_quiet_hours_block_initiative(self):
        engine = InitiativeEngine()
        for kwargs in ({"busy": True}, {"quiet_hours": True}, {"app_active": False}):
            result = engine.evaluate(now=10000, last_interaction=1, enabled=True, has_relevant_memory=True, **kwargs)
            self.assertFalse(result["eligible"])


if __name__ == "__main__":
    unittest.main()
