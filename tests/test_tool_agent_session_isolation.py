"""Regression tests for per-character ToolAgent and system-access state."""
from contextvars import ContextVar
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from kira.tools.agent import Pending, ToolAgent, ToolPlan
from kira.tools.sysaccess import AccessManager
from kira.webintel.session import CANCEL, DEFAULT_BUDGET, SessionScopedResearchStore


class ToolAgentSessionIsolationTests(unittest.TestCase):
    def setUp(self):
        self.access = AccessManager(SimpleNamespace())
        self.agent = ToolAgent.__new__(ToolAgent)
        self.agent.settings = {"agent_planning": True, "agent_mode": "on"}
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

    def test_task_cancel_releases_only_the_matching_session_confirmation(self):
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as temp:
            self.agent._init_autonomy(temp)
            plan = self.agent.tasks.new("remove a file", session_id="kira")
            self.agent._pending_by_session["kira"] = Pending(
                "delete_file", {"path": "safe.txt"}, "delete file",
                plan_id=plan.id, session_id="kira",
            )
            self.agent._pending_new_sessions.add("kira")
            self.agent._pending_by_session["ren"] = Pending(
                "delete_file", {"path": "other.txt"}, "delete another file",
                plan_id="ren-plan", session_id="ren",
            )
            self.agent._pending_new_sessions.add("ren")

            reply = self.agent.handle_task_command("لغو کار", session_id="kira")

            self.assertIn("وظیفه لغو شد", reply)
            self.assertEqual(plan.status, "cancelled")
            self.assertNotIn("kira", self.agent._pending_by_session)
            self.assertNotIn("kira", self.agent._pending_new_sessions)
            self.assertIn("ren", self.agent._pending_by_session)
            self.assertIn("ren", self.agent._pending_new_sessions)

    def test_webintel_research_storage_is_independent_and_persistent_per_character(self):
        owner = ContextVar("test_webintel_owner", default="")
        with TemporaryDirectory() as temp:
            store = SessionScopedResearchStore(temp, owner.get)

            owner.set("kira")
            kira_session = store.start("Kira research", dict(DEFAULT_BUDGET))
            kira_session.status = "paused"
            store.save()

            owner.set("ren")
            self.assertIsNone(store.current())
            store.start("Ren research", dict(DEFAULT_BUDGET))
            store.save()

            owner.set("kira")
            self.assertEqual(store.current().topic, "Kira research")
            restarted = SessionScopedResearchStore(temp, owner.get)
            self.assertEqual(restarted.current().topic, "Kira research")

            owner.set("ren")
            self.assertEqual(restarted.current().topic, "Ren research")
            restarted.clear()
            self.assertIsNone(restarted.current())

            owner.set("kira")
            self.assertEqual(restarted.current().topic, "Kira research")

    def test_webintel_cancel_event_is_scoped_to_active_owner(self):
        CANCEL.clear_all()
        try:
            CANCEL.activate("brand-new-owner")
            self.assertFalse(CANCEL.is_set())
            CANCEL.set()
            self.assertTrue(CANCEL.is_set())
            CANCEL.deactivate("brand-new-owner")

            CANCEL.cancel_session("kira")
            CANCEL.activate("ren")
            self.assertFalse(CANCEL.is_set())
            CANCEL.set()
            self.assertTrue(CANCEL.is_set())
            CANCEL.deactivate("ren")

            CANCEL.activate("kira")
            self.assertTrue(CANCEL.is_set())
            CANCEL.clear()
            self.assertFalse(CANCEL.is_set())
            CANCEL.deactivate("kira")
        finally:
            CANCEL.deactivate("ren")
            CANCEL.deactivate("kira")
            CANCEL.clear_all()

    def test_plan_carries_its_character_identity(self):
        plan = ToolPlan({"files"}, session_id="mika")
        self.assertEqual(plan.session_id, "mika")


if __name__ == "__main__":
    unittest.main()
