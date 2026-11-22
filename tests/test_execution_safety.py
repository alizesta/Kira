"""Regression tests for strict tool arguments and planned-step execution guards."""
import threading
import unittest
from types import SimpleNamespace

from kira.tools.autonomy import AutonomyMixin
from kira.tools.registry import (
    ACTION, BAD_ARGS, OK, Param, Tool, ToolError, ToolRegistry, ToolResult,
)
from kira.tools.tasks import AWAITING, DONE, REVIEW, Step, TaskPlan


class ToolArgumentValidationTests(unittest.TestCase):
    def setUp(self):
        self.registry = ToolRegistry()
        self.tool = Tool(
            "set_volume",
            "Set the system volume",
            lambda args: "volume changed",
            params=(Param("percent", "integer", required=True),),
            level=ACTION,
            categories=("audio",),
        )
        self.registry.register(self.tool)

    def test_unknown_argument_is_rejected(self):
        with self.assertRaisesRegex(ToolError, "پارامتر ناشناخته"):
            self.registry.clean_args(self.tool, {"percent": 50, "percennt": 80})

    def test_known_arguments_are_preserved(self):
        self.assertEqual(
            self.registry.clean_args(self.tool, {"percent": 50}),
            {"percent": 50},
        )

    def test_missing_required_argument_still_fails(self):
        with self.assertRaisesRegex(ToolError, "لازم"):
            self.registry.clean_args(self.tool, {})


class _RegistryProbe:
    def __init__(self):
        self.tool = SimpleNamespace(level=1, categories=("apps",))
        self.executed = []

    def get(self, name):
        return self.tool if name == "open_app" else None

    def execute(self, name, args):
        self.executed.append((name, args))
        return ToolResult(name, OK, "executed", args, 1)


class _AutonomyProbe(AutonomyMixin):
    def __init__(self):
        self.registry = _RegistryProbe()
        self._cancel = threading.Event()
        self._turn_session_id = "test-session"
        self._pending_by_session = {}
        self._pending_new_sessions = set()

    def has_pending(self, _session_id=None):
        return False


class PlannedStepExecutionGuardTests(unittest.TestCase):
    def setUp(self):
        self.agent = _AutonomyProbe()
        self.plan = TaskPlan("t-safety", "Complete the requested task")
        self.plan.steps.append(Step(1, "Open the requested application", "open_app"))

    def _run(self, step_id=1):
        return self.agent._run_calls_planned(
            self.plan,
            [{"tool": "open_app", "args": {"name": "Calculator"}, "step": step_id}],
            [],
            None,
            8,
        )

    def test_unknown_step_id_is_rejected(self):
        results, notes = self._run(step_id=99)
        self.assertEqual(results[0].status, BAD_ARGS)
        self.assertEqual(self.agent.registry.executed, [])
        self.assertIn("unknown step", notes[0])

    def test_tool_cannot_be_substituted_for_declared_step_tool(self):
        self.agent.registry.get = lambda _name: SimpleNamespace(level=1, categories=("files",))
        results, notes = self.agent._run_calls_planned(
            self.plan,
            [{"tool": "delete_file", "args": {"path": "x"}, "step": 1}],
            [],
            None,
            8,
        )
        self.assertEqual(results[0].status, BAD_ARGS)
        self.assertEqual(self.plan.steps[0].tool, "open_app")
        self.assertEqual(self.agent.registry.executed, [])
        self.assertIn("tool mismatch", notes[0])

    def test_step_waiting_for_review_cannot_be_executed_again(self):
        self.plan.steps[0].status = REVIEW
        results, notes = self._run()
        self.assertEqual(results[0].status, BAD_ARGS)
        self.assertEqual(self.agent.registry.executed, [])
        self.assertIn("repeat call", notes[0])

    def test_missing_dependency_blocks_execution(self):
        self.plan.steps[0].depends_on = [99]
        results, notes = self._run()
        self.assertEqual(results[0].status, BAD_ARGS)
        self.assertEqual(self.agent.registry.executed, [])
        self.assertIn("unfinished dependency", notes[0])

    def test_completed_step_cannot_be_reexecuted(self):
        self.plan.steps[0].status = DONE
        results, notes = self._run()
        self.assertEqual(results[0].status, BAD_ARGS)
        self.assertEqual(self.agent.registry.executed, [])
        self.assertIn("repeat call", notes[0])

    def test_step_id_is_required_for_planned_execution(self):
        results, notes = self.agent._run_calls_planned(
            self.plan,
            [{"tool": "open_app", "args": {"name": "Calculator"}}],
            [],
            None,
            8,
        )
        self.assertEqual(results[0].status, BAD_ARGS)
        self.assertEqual(self.agent.registry.executed, [])
        self.assertIn("invalid step id", notes[0])

    def test_non_object_arguments_are_rejected_before_binding(self):
        results, notes = self.agent._run_calls_planned(
            self.plan,
            [{"tool": "open_app", "args": ["Calculator"], "step": 1}],
            [],
            None,
            8,
        )
        self.assertEqual(results[0].status, BAD_ARGS)
        self.assertEqual(self.agent.registry.executed, [])
        self.assertIn("non-object arguments", notes[0])

    def test_confirmation_waiting_step_cannot_be_replayed(self):
        self.plan.steps[0].status = AWAITING
        results, notes = self._run()
        self.assertEqual(results[0].status, BAD_ARGS)
        self.assertEqual(self.agent.registry.executed, [])
        self.assertIn("repeat call", notes[0])

    def test_duplicate_step_ids_are_ambiguous_and_fail_closed(self):
        self.plan.steps.append(Step(1, "Duplicate step", "open_app"))
        self.assertIsNone(self.plan.step(1))
        self.assertEqual(self.plan.deps_unmet(self.plan.steps[0]), [])

    def test_malformed_and_non_positive_dependencies_are_unmet(self):
        self.plan.steps[0].depends_on = ["not-an-id", 0, -1, 99]
        self.assertEqual(
            self.plan.deps_unmet(self.plan.steps[0]),
            ["not-an-id", 0, -1, 99],
        )


if __name__ == "__main__":
    unittest.main()
