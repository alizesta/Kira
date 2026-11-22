"""Regression tests for strict tool arguments and planned-step execution guards."""
import threading
import unittest
from types import SimpleNamespace

from kira.tools.autonomy import AutonomyMixin
from kira.tools.registry import (
    ACTION, BAD_ARGS, OK, Param, Tool, ToolError, ToolRegistry, ToolResult,
)
from kira.tools.tasks import AWAITING, DONE, REVIEW, RUNNING, SKIPPED, Step, TaskPlan


class PlanStructureValidationTests(unittest.TestCase):
    class _Registry:
        def get(self, _name):
            return SimpleNamespace(level=1)

    def _parse(self, steps):
        import json
        from kira.tools.planner import parse_plan
        raw = "<kira_plan>" + json.dumps({"goal": "test", "steps": steps}) + "</kira_plan>"
        return parse_plan(raw, self._Registry(), max_steps=8)

    def test_duplicate_step_ids_are_rejected_instead_of_renumbered(self):
        with self.assertRaisesRegex(ValueError, "duplicated"):
            self._parse([
                {"id": 1, "title": "first", "tool": "open_app"},
                {"id": 1, "title": "second", "tool": "open_app"},
            ])

    def test_zero_and_negative_step_ids_are_rejected(self):
        for invalid_id in (0, -1):
            with self.subTest(step_id=invalid_id):
                with self.assertRaisesRegex(ValueError, "positive integer"):
                    self._parse([{"id": invalid_id, "title": "invalid", "tool": "open_app"}])

    def test_forward_dependency_cannot_be_satisfied_by_later_completed_step(self):
        plan = TaskPlan("t-order", "Respect declared order")
        first = Step(10, "First", "open_app", depends_on=[20])
        later = Step(20, "Later", "open_app", status=DONE)
        plan.steps.extend([first, later])
        self.assertEqual(plan.deps_unmet(first), [20])

    def test_falsey_non_list_dependencies_are_rejected(self):
        for malformed in (None, False, 0, ""):
            with self.subTest(dependencies=malformed):
                with self.assertRaisesRegex(ValueError, "dependencies must be a list"):
                    self._parse([{
                        "id": 1,
                        "title": "Invalid dependency container",
                        "tool": "open_app",
                        "depends_on": malformed,
                    }])

    def test_corrupt_persisted_step_ids_are_rejected(self):
        for invalid_id in (True, 1.5, 0, -2):
            with self.subTest(step_id=invalid_id):
                with self.assertRaises(ValueError):
                    Step.from_dict({"id": invalid_id})

    def test_corrupt_persisted_dependencies_are_preserved_as_blocking(self):
        step = Step.from_dict({"id": 1, "depends_on": [1.5, True, "bad"]})
        plan = TaskPlan("t-corrupt", "Fail closed")
        plan.steps.append(step)
        self.assertEqual(plan.deps_unmet(step), [0, 0, 0])


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

    def test_unknown_argument_never_reaches_tool_handler(self):
        called = []
        tool = Tool(
            "set_volume",
            "Set the system volume",
            lambda args: called.append(args) or "volume changed",
            params=(Param("percent", "integer", required=True),),
            level=ACTION,
        )
        self.registry.register(tool)
        result = self.registry.execute("set_volume", {"percent": 50, "percennt": 80})
        self.assertEqual(result.status, BAD_ARGS)
        self.assertEqual(called, [])

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

    def test_completed_skipped_and_running_steps_cannot_be_reexecuted(self):
        for status in (DONE, SKIPPED, RUNNING):
            with self.subTest(status=status):
                self.plan.steps[0].status = status
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
        dependent = Step(2, "Dependent step", "open_app", depends_on=[1])
        self.plan.steps.append(dependent)
        self.assertIsNone(self.plan.step(1))
        self.assertEqual(self.plan.deps_unmet(dependent), [1])

    def test_malformed_and_non_positive_dependencies_are_unmet(self):
        self.plan.steps[0].depends_on = ["not-an-id", 0, -1, 99]
        self.assertEqual(
            self.plan.deps_unmet(self.plan.steps[0]),
            ["not-an-id", 0, -1, 99],
        )

    def test_float_step_ids_and_dependencies_are_not_coerced(self):
        self.assertIsNone(self.plan.step(1.5))
        self.plan.steps[0].depends_on = [1.5]
        self.assertEqual(self.plan.deps_unmet(self.plan.steps[0]), [1.5])


if __name__ == "__main__":
    unittest.main()
