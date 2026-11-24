"""Regression coverage for ToolAgent's streamed access-denial retry."""
import unittest
from unittest.mock import patch

from kira.tools.agent import ToolAgent, ToolPlan


class ToolAgentDenialBufferTests(unittest.TestCase):
    def _agent(self):
        agent = ToolAgent.__new__(ToolAgent)
        return agent

    def test_unsupported_denial_is_not_emitted_before_full_catalog_retry(self):
        agent = self._agent()
        plan = ToolPlan(categories={"apps"}, schema_categories={"apps"})
        visible = []

        def first_round(*args):
            args[6]("من به کامپیوتر دسترسی ندارم.")
            return {"text": "من به کامپیوتر دسترسی ندارم.", "tools": []}

        def retry_round(*args):
            args[6]("برنامه پیدا شد.")
            return {"text": "برنامه پیدا شد.", "tools": [{"tool": "find_app", "status": "ok"}]}

        with patch.object(agent, "_direct_bridge", return_value=False), \
             patch.object(agent, "_run_once", side_effect=[first_round, retry_round]) as run_once, \
             patch.object(agent, "planning_enabled", return_value=False), \
             patch.object(agent, "_schema_categories", return_value={"apps"}):
            result = agent.run(None, [], "", 0.2, plan, on_chunk=visible.append)

        self.assertEqual(result["text"], "برنامه پیدا شد.")
        self.assertEqual(visible, ["برنامه پیدا شد."])
        self.assertEqual(run_once.call_count, 2)

    def test_non_denial_first_answer_is_emitted_after_validation(self):
        agent = self._agent()
        plan = ToolPlan(categories={"apps"}, schema_categories={"apps"})
        visible = []

        def first_round(*args):
            args[6]("سلام، چطور کمک کنم؟")
            return {"text": "سلام، چطور کمک کنم؟", "tools": []}

        with patch.object(agent, "_direct_bridge", return_value=False), \
             patch.object(agent, "_run_once", side_effect=first_round) as run_once, \
             patch.object(agent, "_schema_categories", return_value={"apps"}):
            result = agent.run(None, [], "", 0.2, plan, on_chunk=visible.append)

        self.assertEqual(result["text"], "سلام، چطور کمک کنم؟")
        self.assertEqual(visible, ["سلام، چطور کمک کنم؟"])
        run_once.assert_called_once()


if __name__ == "__main__":
    unittest.main()
