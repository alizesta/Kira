import unittest

from kira.character.decision import BASE_TRAITS, BEHAVIOUR_GUIDES, DecisionEngine, decide as decide_character
from kira.character.initiative import InitiativeEngine
from kira.character.learning import detect_feedback


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

    def test_emotional_memory_changes_the_selected_behaviour(self):
        decision = self.engine.decide("hello", {
            "emotion": "neutral",
            "emotional_memories": [{"signal": "down", "impact": 100}],
        })
        self.assertEqual(decision.behaviour, "gentle")

    def test_learned_traits_are_used_by_decision_engine(self):
        decision = decide_character("hello", {
            "emotion": "happy",
            "personality_traits": {**BASE_TRAITS, "playfulness": 1.0, "teasing": 1.0},
        })
        self.assertEqual(decision.traits["playfulness"], 1.0)

    def test_feedback_detector_requires_specific_style_language(self):
        self.assertEqual(detect_feedback("این شوخی خوب بود"), "liked_teasing")
        self.assertEqual(detect_feedback("شوخی نکن"), "disliked_teasing")
        self.assertEqual(detect_feedback("فردا امتحان دارم"), None)

    def test_extended_behaviours_are_selectable_and_described(self):
        for behaviour in ("sarcastic", "clingy", "stubborn", "sulking", "cheerful", "reserved", "flirty", "energetic"):
            self.assertIn(behaviour, BEHAVIOUR_GUIDES)
        decision = self.engine.decide("عشقم", {
            "emotion": "flirty", "behaviors": [("flirty", 95)], "energy": 90,
        })
        self.assertEqual(decision.behaviour, "flirty")


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

    def test_completed_memory_is_not_selected_for_another_checkin(self):
        engine = InitiativeEngine()
        now = 20 * 86400
        items = [
            {"id": "event-1", "group": "moment", "kind": "event", "text": "exam", "ts": now - 100},
            {"id": "event-2", "group": "moment", "kind": "promise", "text": "trip", "ts": now - 200},
        ]
        selected = engine.select_candidate(items, now=now, exclude_id="event-1")
        self.assertEqual(selected["id"], "event-2")

    def test_only_recent_events_and_promises_are_initiative_candidates(self):
        engine = InitiativeEngine()
        now = 20 * 86400
        items = [
            {"group": "moment", "kind": "joke", "text": "joke", "ts": now - 10},
            {"group": "fact", "kind": "event", "text": "not a moment", "ts": now - 10},
            {"group": "moment", "kind": "event", "text": "recent exam", "ts": now - 100},
            {"group": "moment", "kind": "promise", "text": "old promise", "ts": now - 20 * 86400},
        ]
        self.assertEqual(engine.select_candidate(items, now=now)["text"], "recent exam")


if __name__ == "__main__":
    unittest.main()
