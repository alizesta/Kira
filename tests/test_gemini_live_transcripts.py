"""Unit tests for Gemini Live's incremental transcript buffering."""
from types import SimpleNamespace
import unittest

from kira.gemini_live import _append_transcript_chunk, _take_transcript


class GeminiLiveTranscriptBufferTests(unittest.TestCase):
    def setUp(self):
        self.buffers = {"user": [], "assistant": []}

    def test_chunks_are_emitted_only_after_finished(self):
        first, supports = _append_transcript_chunk(
            self.buffers, "user", SimpleNamespace(text="سلام ", finished=False)
        )
        self.assertIsNone(first)
        self.assertIs(supports, True)

        second, supports = _append_transcript_chunk(
            self.buffers, "user", SimpleNamespace(text="دنیا", finished=True)
        )
        self.assertEqual(second, "سلام دنیا")
        self.assertIs(supports, True)
        self.assertIsNone(_take_transcript(self.buffers, "user"))

    def test_roles_keep_separate_partial_buffers(self):
        user_text, _ = _append_transcript_chunk(
            self.buffers, "user", SimpleNamespace(text="سؤال ", finished=False)
        )
        assistant_text, _ = _append_transcript_chunk(
            self.buffers, "assistant", SimpleNamespace(text="پاسخ", finished=True)
        )
        user_final, _ = _append_transcript_chunk(
            self.buffers, "user", SimpleNamespace(text="من", finished=True)
        )

        self.assertIsNone(user_text)
        self.assertEqual(assistant_text, "پاسخ")
        self.assertEqual(user_final, "سؤال من")

    def test_legacy_sdk_objects_use_turn_complete_fallback(self):
        completed, supports = _append_transcript_chunk(
            self.buffers, "assistant", SimpleNamespace(text="Legacy transcript")
        )
        self.assertIsNone(completed)
        self.assertIs(supports, False)
        self.assertEqual(_take_transcript(self.buffers, "assistant"), "Legacy transcript")

    def test_empty_final_chunk_clears_whitespace_only_buffer(self):
        _append_transcript_chunk(
            self.buffers, "user", SimpleNamespace(text="   ", finished=False)
        )
        completed, _ = _append_transcript_chunk(
            self.buffers, "user", SimpleNamespace(text="", finished=True)
        )
        self.assertIsNone(completed)
        self.assertEqual(self.buffers["user"], [])


if __name__ == "__main__":
    unittest.main()
