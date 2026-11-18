"""Regression tests for brain-stage decisions and post-reply reflection quality."""
from __future__ import annotations

import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
import time
from unittest.mock import patch

from kira import brain, modes


class BrainDecisionQualityTests(unittest.TestCase):
    def test_explicit_analysis_in_casual_chat_uses_deep_stage(self):
        text = "Please analyze this issue, compare the options, and explain the root cause carefully."
        decision = brain.decide(text, mode=modes.Mode(modes.CHAT))
        self.assertEqual(decision.stage, brain.DEEP)
        self.assertIn("analysis request", decision.reasons)

    def test_strict_delivery_style_does_not_suppress_deep_analysis(self):
        text = "لطفاً این مسئله را با تحلیل ریشه‌ای، بررسی عمیق و مقایسه گزینه‌ها ارزیابی کن."
        decision = brain.decide(text, mode=modes.Mode(modes.STRICT))
        self.assertEqual(decision.stage, brain.DEEP)

    def test_persian_zero_width_non_joiner_is_normalized_for_detection(self):
        text = "لطفاً درباره این مشکل بررسی‌عمیق انجام بده و علت اصلی و راهکارهای ممکن را مقایسه کن."
        decision = brain.decide(text, mode=modes.Mode(modes.CHAT))
        self.assertEqual(decision.stage, brain.DEEP)
        self.assertIn("analysis request", decision.reasons)

    def test_code_is_deep_even_when_the_delivery_mode_is_casual(self):
        snippet = "\x60\x60\x60python\\nprint('hello')\\n\x60\x60\x60"
        decision = brain.decide(snippet, mode=modes.Mode(modes.CHAT))
        self.assertEqual(decision.stage, brain.DEEP)
        self.assertIn("code", decision.reasons)

    def test_long_personal_chat_alone_stays_on_surface(self):
        text = "امروز روز خوبی داشتم و کلی اتفاق افتاد. " * 20
        decision = brain.decide(text, mode=modes.Mode(modes.CHAT))
        self.assertEqual(decision.stage, brain.SURFACE)
        self.assertEqual(decision.reasons, ())

    def test_string_mode_is_supported_for_direct_callers(self):
        decision = brain.decide("analyze this issue and compare the likely causes", mode=modes.CHAT)
        self.assertEqual(decision.stage, brain.DEEP)

    def test_invalid_brain_mode_falls_back_to_auto(self):
        decision = brain.decide(
            "Please analyze this issue and compare the possible causes.",
            mode=modes.Mode(modes.CHAT),
            settings={"brain_mode": "unexpected-value"},
        )
        self.assertEqual(decision.stage, brain.DEEP)

    def test_surface_only_still_disables_deep_routing(self):
        decision = brain.decide(
            "Please analyze this issue and compare the possible causes.",
            mode=modes.Mode(modes.CHAT),
            settings={"brain_mode": "surface_only"},
        )
        self.assertEqual(decision.stage, brain.SURFACE)


class BrainContextGuardTests(unittest.TestCase):
    def test_unknown_router_is_treated_as_context_constrained(self):
        self.assertTrue(brain._small_context({}, None, brain.Decision(stage=brain.DEEP)))

    def test_route_inspection_failure_is_treated_as_context_constrained(self):
        class BrokenRouter:
            @contextmanager
            def role_scope(self, *_args, **_kwargs):
                raise RuntimeError("route metadata unavailable")
                yield

        self.assertTrue(brain._small_context({}, BrokenRouter(), brain.Decision(stage=brain.DEEP)))

    def test_known_remote_route_is_not_context_constrained(self):
        class RemoteRouter:
            @contextmanager
            def role_scope(self, *_args, **_kwargs):
                yield

            def preview_route(self):
                return {"kind": "cloud", "route_id": "cloud"}

        self.assertFalse(brain._small_context({}, RemoteRouter(), brain.Decision(stage=brain.DEEP)))

    def test_malformed_or_future_review_hint_is_discarded(self):
        malformed = {"turn": 2, "hint": {"text": "bad", "created": "not-a-timestamp", "turn": 2}}
        future = {"turn": 2, "hint": {"text": "future", "created": 1000, "turn": 3}}
        self.assertEqual(brain._pending_hint(malformed, 100), "")
        self.assertEqual(brain._pending_hint(future, 100), "")

    def test_review_hint_is_explicitly_low_priority_untrusted_data(self):
        self.assertIn("untrusted data", brain.HINT_BLOCK.lower())
        self.assertIn("never let it override", brain.HINT_BLOCK.lower())

    def test_deep_prompt_is_not_added_when_route_metadata_is_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(brain, "DATA_DIR", Path(tmp)):
                decision = brain.Decision(stage=brain.DEEP, mode="auto")
                self.assertEqual(brain.extend_prompt("base prompt", decision, {}, None), "base prompt")

    def test_non_finite_review_timestamp_is_discarded(self):
        state = {"turn": 2, "hint": {"text": "bad", "created": float("nan"), "turn": 2}}
        self.assertEqual(brain._pending_hint(state, 100), "")



class BrainStateRecoveryTests(unittest.TestCase):
    def test_corrupt_nested_state_is_normalized_without_disabling_future_hints(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(brain, "DATA_DIR", Path(tmp)):
                path = brain._path("test-state")
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(
                    '{"turn":"4","hint":{"text":"usable","created":"bad","turn":99,"sig":"x"},'
                    '"sigs":[["valid",3],["broken","not-a-turn"],["other",99],{}],'
                    '"reflect":{"last":"nan","hour":["bad",9999999999999999]},'
                    '"writer":{"last_run":"oops","next_try":NaN}}',
                    encoding="utf-8",
                )
                state = brain._load("test-state")
                self.assertEqual(state["turn"], 4)
                self.assertIsNone(state["hint"])
                self.assertEqual(state["sigs"], [["valid", 3]])
                self.assertEqual(state["reflect"], {"last": 0.0, "hour": []})
                self.assertEqual(state["writer"], {"last_run": 0.0, "next_try": 0.0})
                retry_at = time.time() + 3600
                self.assertTrue(brain._save({"turn": 0, "hint": None, "sigs": [], "reflect": {"last": 0, "hour": []},
                                             "writer": {"last_run": time.time(), "next_try": retry_at}}, "test-state"))
                reloaded = brain._load("test-state")
                self.assertGreater(reloaded["writer"]["next_try"], time.time() + 3500)
                self.assertTrue(brain._store_hint("fresh", "new reminder", "test-state"))
                self.assertEqual(brain.status("test-state")["hint_pending"], True)

    def test_fractional_or_boolean_counters_are_rejected(self):
        self.assertEqual(brain._safe_state_int(2.5, 7), 7)
        self.assertEqual(brain._safe_state_int(True, 7), 7)
        self.assertEqual(brain._safe_state_int("12", 7), 12)

    def test_empty_hint_or_signature_is_not_persisted(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(brain, "DATA_DIR", Path(tmp)):
            self.assertFalse(brain._store_hint("", "hint", "empty"))
            self.assertFalse(brain._store_hint("signature", "   ", "empty"))


class BrainMemoryWriterTests(unittest.TestCase):
    def test_budget_hook_failure_disables_optional_background_usage(self):
        with patch.object(brain, "budget_check", side_effect=RuntimeError("usage service unavailable")):
            self.assertFalse(brain._allowed(brain.MEMORY))

    def test_writer_does_not_advance_cursor_when_model_response_is_invalid(self):
        import kira.evidence_memory as evidence_memory
        import kira.memory as memory_store
        rows = [(index, "user", f"message {index}", "") for index in range(1, 11)]
        with tempfile.TemporaryDirectory() as tmp:
            with (
                patch.object(brain, "DATA_DIR", Path(tmp)),
                patch.object(memory_store, "rows_with_ids", return_value=rows),
                patch.object(evidence_memory, "enabled", return_value=True),
                patch.object(evidence_memory, "writer_cursor", return_value=0),
                patch.object(evidence_memory, "ingest_model_facts", return_value=(0, ["unreadable JSON: invalid"])),
                patch.object(evidence_memory, "set_writer_cursor") as set_cursor,
                patch.object(brain, "make_aux_router", return_value=object()),
                patch.object(brain, "_ask", return_value="not-json"),
            ):
                brain._memory_writer(object(), {"brain_memory_writer": "idle"})
                set_cursor.assert_not_called()
                self.assertGreater(brain._load()["writer"]["next_try"], time.time())

    def test_writer_does_not_advance_cursor_when_fact_storage_failed(self):
        import kira.evidence_memory as evidence_memory
        import kira.memory as memory_store
        rows = [(index, "user", f"message {index}", "") for index in range(1, 11)]
        with tempfile.TemporaryDirectory() as tmp:
            with (
                patch.object(brain, "DATA_DIR", Path(tmp)),
                patch.object(memory_store, "rows_with_ids", return_value=rows),
                patch.object(evidence_memory, "enabled", return_value=True),
                patch.object(evidence_memory, "writer_cursor", return_value=0),
                patch.object(evidence_memory, "ingest_model_facts", return_value=(0, ["store error: sqlite"])),
                patch.object(evidence_memory, "set_writer_cursor") as set_cursor,
                patch.object(brain, "make_aux_router", return_value=object()),
                patch.object(brain, "_ask", return_value='{"facts": []}'),
            ):
                brain._memory_writer(object(), {"brain_memory_writer": "idle"})
                set_cursor.assert_not_called()
                state = brain._load()
                self.assertGreater(state["writer"]["next_try"], time.time())


class BrainReflectionQualityTests(unittest.TestCase):
    def test_reflection_off_does_not_inject_a_stale_hint(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(brain, "DATA_DIR", Path(tmp)):
            self.assertTrue(brain._store_hint("old", "stale reminder", "reflection-off"))
            decision = brain.Decision(stage=brain.SURFACE, reflection="off", mode="auto")
            prompt = brain.extend_prompt("base prompt", decision, {}, None, character_id="reflection-off")
        self.assertEqual(prompt, "base prompt")
        self.assertIsNone(brain._load("reflection-off")["hint"])

    def test_non_kira_reflection_does_not_read_kira_identity(self):
        with patch("kira.evidence_memory.current_value", side_effect=AssertionError("Kira memory leaked")):
            findings = brain.check_reply(
                "Your name is Alex.", tools=[], mode_name=modes.CHAT,
                character_id="ren",
            )
        self.assertEqual(findings, [])

    def test_non_kira_turn_cannot_run_kiras_legacy_memory_writer(self):
        with patch("kira.evidence_memory.enabled", side_effect=AssertionError("writer should not start")):
            brain._memory_writer(object(), {"brain_memory_writer": "idle"}, "mika")

    def test_non_kira_model_reflection_does_not_retrieve_kira_evidence(self):
        import kira.evidence_memory as evidence_memory
        with (
            patch.object(brain, "_allowed", return_value=True),
            patch.object(brain, "_load", return_value=brain._empty_state()),
            patch.object(brain, "_save", return_value=True),
            patch.object(brain, "make_aux_router", return_value=object()),
            patch.object(brain, "_ask", return_value='{"issue": false, "hint": ""}'),
            patch.object(evidence_memory, "retrieve", side_effect=AssertionError("Kira facts leaked")),
        ):
            brain._model_reflect(object(), {}, "ren user message", "ren reply", "ren")

    def test_partial_tool_failure_is_not_hidden_by_another_success(self):
        findings = brain.check_reply(
            "کار انجام شد.",
            tools=[
                {"tool": "file_write", "status": "ok"},
                {"tool": "web_search", "status": "error"},
            ],
            mode_name=modes.TASK,
            tool_expected=True,
        )
        self.assertIn("hidden_failure", [signature for signature, _hint in findings])

    def test_duplicate_first_hint_does_not_block_a_later_new_finding(self):
        with tempfile.TemporaryDirectory() as tmp:
            decision = brain.Decision(stage=brain.SURFACE, reflection="rules", mode="auto")
            with (
                patch.object(brain, "DATA_DIR", Path(tmp)),
                patch.object(brain, "check_reply", return_value=[("seen", "old hint"), ("new", "new hint")]),
                patch.object(brain, "_store_hint", side_effect=[False, True]),
                patch("kira.hybrid_ai.HybridRouter._write_telemetry"),
            ):
                info = brain.after_turn(
                    None, {}, decision, "user request", "assistant response",
                    mode_name=modes.TASK, character_id="brain-quality-test",
                )
        self.assertEqual(info["hint"], "new")


if __name__ == "__main__":
    unittest.main()
