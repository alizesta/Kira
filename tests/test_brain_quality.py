"""Regression tests for brain-stage decisions and post-reply reflection quality."""
from __future__ import annotations

import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
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


class BrainReflectionQualityTests(unittest.TestCase):
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
