import unittest

from kira.emotion.lifecycle import should_observe_assistant_message


class AssistantObservationPolicyTests(unittest.TestCase):
    def test_only_complete_assistant_replies_can_update_long_term_state(self):
        self.assertTrue(should_observe_assistant_message("complete"))
        self.assertTrue(should_observe_assistant_message(None))
        self.assertTrue(should_observe_assistant_message(""))
        for status in ("cancelled", "interrupted", "failed", "partial", "pending"):
            with self.subTest(status=status):
                self.assertFalse(should_observe_assistant_message(status))


if __name__ == "__main__":
    unittest.main()
