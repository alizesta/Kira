import unittest
from unittest import mock

from kira.character.decision import BASE_TRAITS, BEHAVIOUR_GUIDES, DecisionEngine, decide as decide_character
from kira.character.initiative import InitiativeEngine
from kira.character.learning import detect_feedback
from kira.personas import CHARACTERS
from kira import mood
from kira.chat.context_builder import ContextBuilder, ContextRequest, latest_user_text
from kira.character.text import normalize_detection_text


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


    def test_indirect_serious_contexts_cover_health_abuse_divorce_and_financial_crisis(self):
        samples = (
            "عمل جراحی مادرم فرداست و خیلی می‌ترسم",
            "پزشک گفت سرطان دارم",
            "همسرم در خانه من را کتک می‌زند",
            "بعد از طلاق نمی‌دانم چطور زندگی را ادامه بدهم",
            "ورشکست شدیم و زیر بار بدهی سنگین مانده‌ایم",
            "دیگه بریدم، هیچ امیدی ندارم",
            "My father is having surgery tomorrow",
            "My partner is abusing me",
            "We are facing a financial crisis and eviction",
        )
        for text in samples:
            with self.subTest(text=text):
                self.assertTrue(self.engine.decide(text).serious_context)

    def test_hospitality_is_not_mistaken_for_hospital(self):
        self.assertFalse(self.engine.decide("The hospitality industry is recovering").serious_context)
        self.assertTrue(self.engine.decide("The hospital called this morning").serious_context)

    def test_arabic_and_persian_letter_variants_share_detection_normalization(self):
        self.assertEqual(normalize_detection_text("خودكشي"), "خودکشی")
        self.assertTrue(self.engine.decide("خودكشي به ذهنم رسیده").serious_context)
        self.assertEqual(mood._norm("ميترسم و نگرانم"), "میترسم و نگرانم")

    def test_colloquial_mood_detection_covers_indirect_persian_expressions(self):
        self.assertIn("down", mood.detect_user_states("دیگه بریدم، طاقتم تموم شده"))
        self.assertIn("stressed", mood.detect_user_states("زیر فشارم و نگرانی ولم نمی‌کنه"))

    def test_serious_context_remains_stronger_than_task_mode_for_every_profile(self):
        for character_id in ("kira", "ren", "mika"):
            engine = DecisionEngine(CHARACTERS[character_id]["traits"])
            decision = engine.decide(
                "عمل جراحی پدرم فرداست و می‌ترسم",
                {"emotion": "happy", "energy": 90, "user_states": ["stressed"]},
                "task",
            )
            self.assertTrue(decision.serious_context)
            self.assertIn(decision.behaviour, ("gentle", "protective", "quiet"))

    def test_compatible_secondary_behaviours_preserve_compound_traits(self):
        decision = DecisionEngine(CHARACTERS["mika"]["traits"]).decide(
            "سلام", {"emotion": "neutral", "energy": 76}
        )
        self.assertEqual(decision.behaviour, "affectionate")
        self.assertIn("gentle", decision.secondary_behaviours)
        self.assertIn("focused", decision.secondary_behaviours)
        prompt = self.engine.build_prompt(decision)
        self.assertIn("Compatible secondary tendencies", prompt)
        self.assertIn("Initiative policy (wait)", prompt)

    def test_initiative_is_expressed_as_a_concrete_prompt_policy(self):
        cases = {
            "wait": "let the user lead",
            "offer": "offer at most one directly relevant next step",
            "ask": "Ask one concise clarification",
            "act": "Take the next safe and clearly implied step",
            "proactive": "Take the next safe and clearly implied step",
            "invalid-value": "let the user lead",
        }
        for value, expected in cases.items():
            with self.subTest(initiative=value):
                decision = self.engine.decide("hello", initiative=value)
                self.assertIn(expected, self.engine.build_prompt(decision))


    def test_equal_scores_use_the_documented_stable_behaviour_order(self):
        traits = {name: 0.5 for name in BASE_TRAITS}
        engine = DecisionEngine(traits)
        first = engine.decide("سلام", {"emotion": "neutral", "energy": 76})
        for _ in range(10):
            self.assertEqual(engine.decide("سلام", {"emotion": "neutral", "energy": 76}), first)
        self.assertEqual(first.behaviour, "playful")

    def test_decisions_are_stable_for_repeated_and_small_non_boundary_perturbations(self):
        base = {"emotion": "neutral", "energy": 76, "relationship": {"tension": 0}}
        first = self.engine.decide("سلام", base)
        for _ in range(10):
            self.assertEqual(self.engine.decide("سلام", base), first)
        perturbed = self.engine.decide(
            "سلام", {"emotion": "neutral", "energy": 75, "relationship": {"tension": 0}}
        )
        self.assertEqual(perturbed.behaviour, first.behaviour)

    def test_runtime_snapshot_failure_retains_active_profile_traits_and_logs(self):
        ren_traits = CHARACTERS["ren"]["traits"]

        class BrokenRuntime:
            base_traits = ren_traits

            @staticmethod
            def snapshot(*_args, **_kwargs):
                raise OSError("state store unavailable")

        with mock.patch.object(mood, "_runtime_for", return_value=BrokenRuntime()):
            with self.assertLogs("kira.mood", level="ERROR"):
                snapshot = mood._runtime_snapshot()
        self.assertEqual(snapshot["personality_traits"], ren_traits)

    def test_runtime_construction_failure_keeps_ren_baseline_traits(self):
        ren_traits = CHARACTERS["ren"]["traits"]
        with mock.patch.object(mood, "_current_character_id", return_value="ren"), \
             mock.patch.object(mood, "_runtime_for", side_effect=OSError("runtime unavailable")):
            with self.assertLogs("kira.mood", level="ERROR"):
                snapshot = mood._runtime_snapshot()
        self.assertEqual(snapshot["personality_traits"], ren_traits)

    def test_runtime_initialization_failure_does_not_abort_prompt_generation(self):
        self.addCleanup(mood._RUNTIME_INIT_FAILURES.discard, "ren")
        with mock.patch.object(mood, "_current_character_id", return_value="ren"), \
             mock.patch.object(mood, "_runtime_for", side_effect=OSError("runtime unavailable")):
            with self.assertLogs("kira.mood", level="ERROR"):
                block = mood.build_block("chat", query="سلام")
        self.assertIn("[CHARACTER DECISION]", block)
        self.assertIn("curiosity=0.92", block)

    def test_decision_failure_is_logged_and_returns_safe_prompt(self):
        class FakeRuntime:
            @staticmethod
            def build_prompt(*_args, **_kwargs):
                return ""

        snapshot = {
            "emotion": "neutral", "intensity": 0, "secondary_emotions": [],
            "emotional_components": [], "energy": 76, "energy_label": "normal",
            "behaviors": [], "away_hours": 0, "user_states": [],
            "personality_traits": CHARACTERS["ren"]["traits"],
            "relationship": {"closeness": 28, "trust": 50, "tension": 0},
            "emotional_memories": [],
        }
        with mock.patch.object(mood, "_ensure_runtime_migration"), \
             mock.patch.object(mood, "_runtime_for", return_value=FakeRuntime()), \
             mock.patch.object(mood, "current", return_value=snapshot), \
             mock.patch("kira.character.decision.DecisionEngine.decide", side_effect=RuntimeError("engine failed")):
            with self.assertLogs("kira.mood", level="ERROR"):
                block = mood.build_block("chat", query="سلام")
        self.assertIn("[CHARACTER DECISION — SAFE FALLBACK]", block)
        self.assertIn("Never let character style change accuracy", block)

    def test_latest_history_message_reaches_the_final_provider_prompt(self):
        history = [
            {"role": "user", "content": "سلام"},
            {"role": "assistant", "content": "خوش آمدی"},
            {"role": "user", "content": "عمل جراحی پدرم فرداست و می‌ترسم"},
        ]
        query = latest_user_text(history)
        self.assertEqual(query, history[-1]["content"])

        class FakeRuntime:
            @staticmethod
            def build_prompt(*_args, **_kwargs):
                return ""

        snapshot = {
            "emotion": "neutral", "intensity": 10, "secondary_emotions": [],
            "emotional_components": [], "energy": 76, "energy_label": "normal",
            "behaviors": [], "away_hours": 0, "user_states": ["stressed"],
            "personality_traits": CHARACTERS["mika"]["traits"],
            "relationship": {"closeness": 28, "trust": 50, "tension": 0},
            "emotional_memories": [],
        }
        with mock.patch.object(mood, "_ensure_runtime_migration"), \
             mock.patch.object(mood, "_runtime_for", return_value=FakeRuntime()), \
             mock.patch.object(mood, "current", return_value=snapshot):
            mood_block = mood.build_block("chat", query=query)

        builder = ContextBuilder(lambda _settings, **kwargs: kwargs["mood_block"])
        result = builder.build(ContextRequest(
            character_id="mika", messages=history, mood=mood_block,
        ))
        self.assertIn("[CHARACTER DECISION]", result.system_prompt)
        self.assertIn("serious or sensitive context", result.system_prompt)
        self.assertIn("do not tease or flirt", result.system_prompt)
        self.assertEqual(result.character_id, "mika")

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
