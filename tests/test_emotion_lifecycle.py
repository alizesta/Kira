import unittest

from kira.emotion.lifecycle import should_observe_assistant_message, should_observe_message, stream_speech_action


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


class StreamSpeechLifecycleTests(unittest.TestCase):
    def test_streamed_audio_is_ended_not_replayed_after_success(self):
        self.assertEqual(stream_speech_action("complete", True), "end")
        self.assertEqual(stream_speech_action("complete", False), "speak")

    def test_cancel_and_interruption_have_distinct_audio_cleanup(self):
        self.assertEqual(stream_speech_action("cancelled", True), "stop")
        self.assertEqual(stream_speech_action("interrupted", True), "end")
        self.assertEqual(stream_speech_action("failed", True), "end")
        self.assertEqual(stream_speech_action("failed", False), "none")


if __name__ == "__main__":
    unittest.main()
