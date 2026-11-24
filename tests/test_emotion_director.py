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

    def test_user_interrupt_releases_active_response_emotion(self):
        self.director.event("response_started", now=100.0)
        self.director.on_reply(
            self.director.parse_reply("[happy:65]\nسلام"), now=101.0
        )

        self.director.event("user_interrupt", now=102.0)

        self.assertFalse(self._has_entry(source="event", tag="response_started"))
        self.assertFalse(self._has_entry(source="response"))
        self.assertIsNone(self.director.engine.pending)
        self.assertTrue(self._has_entry(source="event", tag="user_interrupt"))

    def test_failed_response_discards_partial_emotion_and_uses_failure_reaction(self):
        self.director.event("response_started", now=100.0)
        self.director.on_reply(
            self.director.parse_reply("[happy:65]\nسلام"), now=101.0
        )

        self.director.event("response_failed", now=102.0)

        self.assertFalse(self._has_entry(source="event", tag="response_started"))
        self.assertFalse(self._has_entry(source="response"))
        self.assertTrue(self._has_entry(source="event", tag="response_failed"))

    def test_listening_state_drives_avatar_and_releases_when_thinking_starts(self):
        self.director.event("listening_started", now=100.0)

        listening = self.director.tick(now=100.0)
        self.assertTrue(listening.listening)
        self.assertTrue(listening.active)
        self.assertEqual(listening.dominant, "curious")
        self.assertTrue(self._has_entry(source="event", tag="listening_started"))

        self.director.event("response_started", now=101.0)
        thinking = self.director.tick(now=101.0)
        self.assertFalse(thinking.listening)
        self.assertFalse(self._has_entry(source="event", tag="listening_started"))
        self.assertTrue(self._has_entry(source="event", tag="response_started"))

    def test_speaking_and_interrupt_clear_listening(self):
        self.director.event("listening_started", now=100.0)
        self.director.event("tts_started", now=101.0)
        self.assertFalse(self.director.tick(now=101.0).listening)
        self.assertTrue(self.director.engine.speaking)

        self.director.event("listening_started", now=102.0)
        self.director.event("user_interrupt", now=103.0)
        frame = self.director.tick(now=103.0)
        self.assertFalse(frame.listening)
        self.assertFalse(frame.speaking)


if __name__ == "__main__":
    unittest.main()
