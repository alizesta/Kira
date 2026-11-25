"""Regression tests for provider worker request metadata."""
import unittest

from kira.ui.workers import StreamWorker


class StreamWorkerContractTests(unittest.TestCase):
    def test_accepts_and_preserves_conversation_id(self):
        worker = StreamWorker(
            object(),
            [{"role": "user", "content": "hello"}],
            "system",
            0.7,
            conversation_id="conversation-123",
        )
        self.assertEqual(worker.conversation_id, "conversation-123")

    def test_conversation_id_remains_optional_for_legacy_callers(self):
        worker = StreamWorker(object(), [], "system", 0.7)
        self.assertIsNone(worker.conversation_id)


if __name__ == "__main__":
    unittest.main()
