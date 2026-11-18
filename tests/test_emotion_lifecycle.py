import unittest
from pathlib import Path

from kira.emotion.lifecycle import should_observe_assistant_message, should_observe_message


class AssistantObservationPolicyTests(unittest.TestCase):
    def test_only_complete_assistant_replies_can_update_long_term_state(self):
        self.assertTrue(should_observe_assistant_message("complete"))
        self.assertTrue(should_observe_assistant_message(None))
        self.assertTrue(should_observe_assistant_message(""))
        for status in ("cancelled", "interrupted", "failed", "partial", "pending"):
            with self.subTest(status=status):
                self.assertFalse(should_observe_assistant_message(status))

    def test_local_or_cancelled_assistant_output_is_not_observed(self):
        self.assertFalse(should_observe_message("assistant", "complete", observe=False))
        self.assertFalse(should_observe_message("assistant", "cancelled", observe=True))
        self.assertFalse(should_observe_message("assistant", "interrupted", observe=True))
        self.assertFalse(should_observe_message("assistant", "failed", observe=True))
        self.assertTrue(should_observe_message("assistant", "complete", observe=True))

    def test_runtime_wires_the_observation_gate_before_memory_side_effects(self):
        source = (
            Path(__file__).resolve().parents[1]
            / "kira"
            / "ui"
            / "main_window_runtime.py"
        ).read_text(encoding="utf-8")
        gate = "should_observe = should_observe_message(role, status, observe=observe)"
        observe_call = "self.context.services.memory_service.observe(self.context.state.cur.cid, role, content)"
        self.assertIn(gate, source)
        self.assertLess(source.index(gate), source.index(observe_call))
        self.assertIn('status="cancelled", metadata={"stream": "stopped"}, persist=False, observe=False', source)
        self.assertIn('status="interrupted", metadata={"stream": "provider_interrupted"}, persist=False, observe=False', source)
        self.assertIn('self.save_message("assistant", text, observe=False)', source)

    def test_only_user_and_complete_assistant_roles_are_observed(self):
        self.assertTrue(should_observe_message("user", "complete", observe=True))
        self.assertTrue(should_observe_message("user", "cancelled", observe=True))
        self.assertFalse(should_observe_message("user", "complete", observe=False))
        for role in ("system", "tool", "developer", ""):
            with self.subTest(role=role):
                self.assertFalse(should_observe_message(role, "complete", observe=True))


if __name__ == "__main__":
    unittest.main()
