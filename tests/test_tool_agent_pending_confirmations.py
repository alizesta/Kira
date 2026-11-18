"""A Session must never lose or silently overwrite a pending tool confirmation."""
import unittest

from kira.tools.agent import ToolAgent
from kira.tools.registry import DENIED, NEEDS_CONFIRM, SENSITIVE, Tool, ToolRegistry


class ToolAgentPendingConfirmationTests(unittest.TestCase):
    def test_only_first_confirmation_is_pending_and_later_calls_are_explicitly_deferred(self):
        agent = ToolAgent.__new__(ToolAgent)
        agent._init_session_turn_states()
        agent.registry = ToolRegistry()
        agent._pending_by_session = {}
        agent._pending_new_sessions = set()
        executed = []

        for name in ("delete_first", "delete_second"):
            agent.registry.register(Tool(
                name=name,
                description="test protected operation",
                handler=lambda args, tool_name=name: executed.append(tool_name) or "done",
                level=SENSITIVE,
                confirm_summary=lambda args, tool_name=name: f"confirm {tool_name}: {args}",
            ))

        with agent._use_session("kira"):
            results = agent._run_calls(
                [
                    {"tool": "delete_first", "args": {"path": "first.txt"}},
                    {"tool": "delete_second", "args": {"path": "second.txt"}},
                ],
                [],
                None,
            )

        self.assertEqual(len(results), 2)
        self.assertEqual(results[0].status, NEEDS_CONFIRM)
        self.assertEqual(results[1].status, DENIED)
        self.assertIn("اجرا نشد", results[1].text)
        self.assertEqual(agent._pending_by_session["kira"].tool, "delete_first")
        self.assertTrue(agent.has_new_pending_confirmation("kira"))
        self.assertEqual(executed, [])

        confirmation = agent.handle_confirmation_reply("تأیید", session_id="kira")
        self.assertIn("done", confirmation)
        self.assertEqual(executed, ["delete_first"])
        self.assertFalse(agent.has_pending("kira"))
        self.assertEqual(agent._pending_by_session.get("kira"), None)


if __name__ == "__main__":
    unittest.main()
