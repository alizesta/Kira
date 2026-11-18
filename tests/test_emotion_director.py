import unittest

from kira.emotion.director import EmotionDirector
from kira.emotion.library import Library


class EmotionDirectorLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.now = 100.0
        self.director = EmotionDirector(Library.load(), clock=lambda: self.now)

    def _has_entry(self, *, source, tag=None):
        return any(
            entry.source == source and (tag is None or entry.tag == tag)
            for entry in self.director.engine.entries
        )

    def test_streamed_reply_tag_does_not_finish_generation_early(self):
        self.director.event("response_started", now=100.0)
        meta = self.director.parse_reply("[happy:65]\nسلام، خوشحالم می‌بینمت.")
        
        result = self.director.on_reply(meta, now=101.0)

        self.assertEqual(result, "applied")
        self.assertTrue(self._has_entry(source="event", tag="response_started"))
        self.assertTrue(self._has_entry(source="response"))

        self.director.event("response_finished", now=102.0)

        self.assertFalse(self._has_entry(source="event", tag="response_started"))
        self.assertTrue(self._has_entry(source="response"))

    def test_cancelled_response_discards_partial_emotion_and_thinking_event(self):
        self.director.event("response_started", now=100.0)
        self.director.on_reply(
            self.director.parse_reply("[happy:65]\nسلام"), now=101.0
        )

        self.director.event("response_cancelled", now=102.0)

        self.assertFalse(self._has_entry(source="event", tag="response_started"))
        self.assertFalse(self._has_entry(source="response"))
        self.assertIsNone(self.director.engine.pending)

    def test_failed_response_discards_partial_emotion_and_uses_failure_reaction(self):
        self.director.event("response_started", now=100.0)
        self.director.on_reply(
            self.director.parse_reply("[happy:65]\nسلام"), now=101.0
        )

        self.director.event("response_failed", now=102.0)

        self.assertFalse(self._has_entry(source="event", tag="response_started"))
        self.assertFalse(self._has_entry(source="response"))
        self.assertTrue(self._has_entry(source="event", tag="response_failed"))


if __name__ == "__main__":
    unittest.main()
