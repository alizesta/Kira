"""Regression tests for explicit web-search opt-out across every entry point."""
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from kira import websearch
from kira.app.web_search import WebSearchApplicationService
from kira.tools.registry import ToolError
from kira.tools.webtools import _gate


class ExplicitWebOptOutTests(unittest.TestCase):
    def test_negated_search_and_casual_now_message_never_trigger_search(self):
        for message in (
            "الان صدامو می‌شنوی",
            "بابا تو نت سرچ نکن",
            "وقتی بهت می‌گم الان داخل نت سرچ نکن",
            "فعلاً وب نرو",
            "دیگه جستجو نکن",
        ):
            with self.subTest(message=message):
                self.assertEqual(websearch.plan(message), (None, False))

    def test_topical_current_information_still_triggers_search(self):
        self.assertIsNotNone(websearch.plan("قیمت دلار الان چنده؟")[0])
        self.assertIsNotNone(websearch.plan("آخرین اخبار فناوری چیست؟")[0])

    def test_application_opt_out_overrides_auto_force_and_tool_plan(self):
        service = WebSearchApplicationService()
        with patch("kira.app.web_search.websearch.plan") as planner:
            self.assertEqual(
                service.plan_request(
                    "بابا تو نت سرچ نکن",
                    {"web_search": True},
                    SimpleNamespace(strong=False, web=True),
                    force_web=True,
                ),
                (None, False),
            )
            planner.assert_not_called()

    def test_web_tool_execution_gate_rejects_negated_search(self):
        ctx = SimpleNamespace(
            user_text=lambda: "وقتی بهت می‌گم الان داخل نت سرچ نکن",
            enabled=lambda: True,
        )
        with self.assertRaises(ToolError):
            _gate(ctx)

    def test_web_tool_execution_gate_keeps_explicit_search_available(self):
        ctx = SimpleNamespace(user_text=lambda: "سرچ کن قیمت دلار", enabled=lambda: True)
        _gate(ctx)


if __name__ == "__main__":
    unittest.main()
