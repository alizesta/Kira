import unittest
from unittest import mock

from kira import mood
from kira.character.decision import BASE_TRAITS, BEHAVIOUR_GUIDES, DecisionEngine, decide as decide_character
from kira.character.initiative import InitiativeEngine
from kira.character.learning import detect_feedback
from kira.personas import CHARACTERS


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

    def test_indirect_sensitive_context_and_persian_normalization(self):
        for phrase in ("فردا باید جراحی کنم","دکتر گفته سرطان دارم","از خشونت خانگی می‌ترسم",
                       "بعد از طلاق در بحران مالی افتادم","مورد آزار جنسی قرار گرفتم",
                       "از بيمارستان می‌ترسم", "I am going through chemotherapy"):
            with self.subTest(phrase=phrase):
                result=self.engine.decide(phrase,{"emotion":"happy"})
                self.assertTrue(result.serious_context)
                self.assertNotIn(result.behaviour,("playful","teasing","flirty","sarcastic"))

    def test_serious_matching_uses_word_boundaries(self):
        self.assertFalse(self.engine.decide("hospitality is growing",{}).serious_context)

    def test_secondary_behaviour_preserves_compatible_traits(self):
        engine=DecisionEngine({**BASE_TRAITS,"empathy":1.0,"warmth":1.0,"carefulness":1.0,
                               "patience":1.0,"playfulness":0.0,"teasing":0.0})
        result=engine.decide("hello",{"emotion":"neutral"})
        self.assertTrue(result.secondary_behaviours)
        self.assertIn("Secondary temperament:",engine.build_prompt(result))

    def test_initiative_is_metadata_only(self):
        a=self.engine.decide("hello",{},initiative="wait")
        b=self.engine.decide("hello",{},initiative="check_in")
        self.assertEqual(a.behaviour,b.behaviour)
        self.assertEqual(b.initiative,"check_in")

    def test_mood_prompt_uses_latest_message_and_active_profile_traits(self):
        snapshot = {
            "emotion": "happy", "intensity": 80, "user_states": [], "away_hours": 0,
            "age": 0, "energy": 80, "energy_label": "normal", "behaviors": [],
            "secondary_emotions": [], "emotional_components": [], "personality_traits": {
                **BASE_TRAITS, "empathy": 1.0, "warmth": 0.95,
            }, "relationship": {}, "emotional_memories": [],
        }
        runtime = mock.Mock()
        runtime.build_prompt.return_value = "runtime mood"
        with mock.patch.object(mood, "_ensure_runtime_migration"), \
             mock.patch.object(mood, "current", return_value=snapshot), \
             mock.patch.object(mood, "_runtime_for", return_value=runtime):
            prompt = mood.build_block("task", query="من فردا جراحی دارم")
        self.assertIn("runtime mood", prompt)
        self.assertIn("[CHARACTER DECISION]", prompt)
        self.assertIn("serious-topic override", prompt)

    def test_mood_and_decision_share_arabic_persian_normalization(self):
        self.assertEqual(mood._norm("كِتاب ي"), "کتاب ی")
        self.assertEqual(mood._norm("شیمی‌درمانی"), "شیمی درمانی")

    def test_runtime_snapshot_failure_preserves_character_baseline(self):
        runtime = mock.Mock()
        runtime.base_traits = {**BASE_TRAITS, "empathy": 0.97}
        with mock.patch.object(mood, "_runtime_for", side_effect=[RuntimeError("snapshot failed"), runtime]):
            snapshot = mood._runtime_snapshot()
        self.assertEqual(snapshot["personality_traits"]["empathy"], 0.97)

    def test_decision_is_stable_under_repeated_and_small_input_perturbations(self):
        base = self.engine.decide("hello", {"emotion": "neutral", "energy": 70})
        repeated = [self.engine.decide("hello", {"emotion": "neutral", "energy": 70}) for _ in range(5)]
        self.assertTrue(all(item == base for item in repeated))
        nearby = self.engine.decide("hello", {"emotion": "neutral", "energy": 72})
        self.assertEqual(nearby.behaviour, base.behaviour)

    def test_colloquial_persian_distress_phrases_are_serious(self):
        for phrase in ("دیگه تحمل ندارم", "نمی‌تونم ادامه بدم", "از کتک‌هاش خسته شدم"):
            with self.subTest(phrase=phrase):
                self.assertTrue(self.engine.decide(phrase, {}).serious_context)

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

    def test_builtin_characters_have_distinct_baseline_decisions(self):
        expected = {"kira": "playful", "ren": "curious", "mika": "affectionate"}
        for character_id, behaviour in expected.items():
            with self.subTest(character=character_id):
                decision = DecisionEngine(CHARACTERS[character_id]["traits"]).decide(
                    "سلام", {"emotion": "neutral", "energy": 76}
                )
                self.assertEqual(decision.behaviour, behaviour)

    def test_mood_prompt_uses_the_active_profile_decision(self):
        class FakeRuntime:
            @staticmethod
            def build_prompt(*_args, **_kwargs):
                return ""

        expected = {"kira": "playful", "ren": "curious", "mika": "affectionate"}
        for character_id, behaviour in expected.items():
            snapshot = {
                "emotion": "neutral", "intensity": 10, "secondary_emotions": [],
                "emotional_components": [], "energy": 76, "energy_label": "normal",
                "behaviors": [], "away_hours": 0, "user_states": [],
                "personality_traits": CHARACTERS[character_id]["traits"],
                "relationship": {"closeness": 28, "trust": 50, "tension": 0},
                "emotional_memories": [],
            }
            with self.subTest(character=character_id), \
                 mock.patch.object(mood, "_ensure_runtime_migration"), \
                 mock.patch.object(mood, "_runtime_for", return_value=FakeRuntime()), \
                 mock.patch.object(mood, "current", return_value=snapshot):
                block = mood.build_block("chat", query="سلام")
            self.assertIn("[CHARACTER DECISION]", block)
            self.assertIn(f"Selected behaviour: {behaviour}", block)

    def test_task_and_serious_context_override_personality_flavour(self):
        for character_id in ("kira", "ren", "mika"):
            engine = DecisionEngine(CHARACTERS[character_id]["traits"])
            task = engine.decide("یک فایل بساز", {"emotion": "neutral"}, "task")
            serious = engine.decide("من خیلی افسرده‌ام", {"emotion": "happy"})
            self.assertEqual(task.behaviour, "focused")
            self.assertTrue(serious.serious_context)
            self.assertIn(serious.behaviour, ("gentle", "protective", "quiet"))

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
