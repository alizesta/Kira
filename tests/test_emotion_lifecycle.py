import unittest

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

    def test_user_message_observation_is_independent_of_assistant_status(self):
        self.assertTrue(should_observe_message("user", "cancelled", observe=True))
        self.assertFalse(should_observe_message("user", "complete", observe=False))


if __name__ == "__main__":
    unittest.main()
