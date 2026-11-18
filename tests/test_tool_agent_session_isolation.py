"""Regression tests for per-character ToolAgent and system-access state."""
from contextlib import contextmanager
from types import SimpleNamespace
import unittest

from kira.tools.agent import ToolAgent, ToolPlan
from kira.tools.sysaccess import AccessManager


class ToolAgentSessionIsolationTests(unittest.TestCase):
    def setUp(self):
        self.access = AccessManager(SimpleNamespace())
        self.agent = ToolAgent.__new__(ToolAgent)
        self.agent.registry = SimpleNamespace(access=self.access)
        self.agent._init_session_turn_states()
        self.agent._pending_by_session = {}
        self.agent._pending_new_sessions = set()

    def test_tool_turn_state_is_isolated_by_character(self):
        with self.agent._use_session("kira"):
            self.agent._turn_id = 4
            self.agent._turn_cache["read_file{}"] = "kira-result"
            self.agent._memos.append((1.0, "Kira-only note"))
            self.agent._last_cats = {"files"}
            self.agent._last_used_turn = 4
            self.agent.last_results = ["kira-result"]
            self.agent._cancel.set()

        with self.agent._use_session("ren"):
            self.assertEqual(self.agent._turn_session_id, "ren")
            self.assertEqual(self.agent._turn_id, 0)
            self.assertEqual(self.agent._turn_cache, {})
            self.assertEqual(list(self.agent._memos), [])
            self.assertEqual(self.agent._last_cats, set())
            self.assertEqual(self.agent._last_used_turn, -99)
            self.assertEqual(self.agent.last_results, [])
            self.assertFalse(self.agent._cancel.is_set())

        with self.agent._use_session("kira"):
            self.assertEqual(self.agent._turn_id, 4)
            self.assertEqual(self.agent._turn_cache["read_file{}"], "kira-result")
            self.assertEqual(list(self.agent._memos), [(1.0, "Kira-only note")])
            self.assertEqual(self.agent._last_cats, {"files"})
            self.assertEqual(self.agent.last_results, ["kira-result"])
            self.assertTrue(self.agent._cancel.is_set())

    def test_system_access_intent_taint_and_grants_are_isolated(self):
        web_tool = SimpleNamespace(
            name="web_read",
            level=1,
            categories=("web",),
            permission=0,
            domain="",
            backend="",
            intent_rx=None,
            intent_alt=None,
            verifies_result=False,
        )
        result = SimpleNamespace(
            status="ok", ms=1, args={"url": "https://example.test"},
            text="external page content",
        )
        policy = self.access.policy_for(web_tool)

        with self.access.use_session("kira"):
            self.access.begin_turn("open the browser")
            self.access.record(web_tool, policy, result)
            self.access.grant("write_file", {"path": "safe.txt"})
            self.assertEqual(self.access.user_text, "open the browser")
            self.assertTrue(self.access.tainted)

        with self.access.use_session("ren"):
            self.assertEqual(self.access.user_text, "")
            self.assertFalse(self.access.tainted)
            self.assertFalse(self.access.consume_grant("write_file", {"path": "safe.txt"}))
            self.access.begin_turn("read my documents")
            self.assertEqual(self.access.user_text, "read my documents")
            self.assertFalse(self.access.tainted)

        with self.access.use_session("kira"):
            self.assertTrue(self.access.tainted)
            self.assertTrue(self.access.consume_grant("write_file", {"path": "safe.txt"}))
            self.assertFalse(self.access.consume_grant("write_file", {"path": "safe.txt"}))

    def test_scoped_stop_does_not_cancel_another_character(self):
        self.agent.request_cancel("ren")
        with self.agent._use_session("kira"):
            self.assertFalse(self.agent._cancel.is_set())
        with self.agent._use_session("ren"):
            self.assertTrue(self.agent._cancel.is_set())

    def test_plan_carries_its_character_identity(self):
        plan = ToolPlan({"files"}, session_id="mika")
        self.assertEqual(plan.session_id, "mika")


if __name__ == "__main__":
    unittest.main()
