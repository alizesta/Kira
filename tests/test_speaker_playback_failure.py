import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication

from kira import voice


class SpeakerPlaybackFailureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def make_speaker(self):
        sp = voice.Speaker({"local_voice_tts": False})
        self.addCleanup(sp.stop)
        return sp

    def test_failed_player_is_skipped_and_reported(self):
        sp = self.make_speaker()
        errors = []
        sp.error.connect(errors.append)
        session = sp._new_session(None, None, False)
        session.input_done = True
        session.playing = True
        player = object()
        sp._fx = player
        sp._on_player_failed(player, "bad file")
        self.assertFalse(session.playing)
        self.assertEqual(session.next_play, 1)
        self.assertTrue(errors and "bad file" in errors[0])

    def test_stale_or_started_player_is_ignored(self):
        sp = self.make_speaker()
        errors = []
        sp.error.connect(errors.append)
        session = sp._new_session(None, None, False)
        session.playing = True
        current = object()
        sp._fx = current
        sp._on_player_failed(object(), "old player")          # watchdog of a previous sentence
        sp._item_began = True
        sp._on_player_failed(current, "already audible")      # sentence is playing normally
        self.assertTrue(session.playing)
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()


class StreamedThinkTagTests(unittest.TestCase):
    def test_partial_opening_tag_is_never_visible(self):
        from kira.speech_split import strip_think
        for partial in ("<", "<t", "<thi", "<think"):
            self.assertEqual(strip_think("Hello " + partial), "Hello ")
        self.assertEqual(strip_think("a < b"), "a < b")

    def test_streamed_prefix_stays_monotonic(self):
        from kira.speech_split import strip_think
        chunks = ["<thi", "<think>plan", "<think>plan</think>Answer text."]
        seen = [strip_think(c) for c in chunks]
        self.assertEqual(seen, ["", "", "Answer text."])
