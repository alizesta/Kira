"""Regression tests for the Windows SAPI TTS fallback."""
import unittest
from types import SimpleNamespace
from unittest import mock

from kira.voice import SAPI_SCRIPT, Speaker


class SapiTtsTests(unittest.TestCase):
    def test_culture_is_captured_before_synthesizer_is_disposed(self):
        capture = "$culture = $s.Voice.Culture.Name"
        dispose = "$s.Dispose()"
        report = "Write-Output $culture"
        self.assertIn(capture, SAPI_SCRIPT)
        self.assertIn(dispose, SAPI_SCRIPT)
        self.assertIn(report, SAPI_SCRIPT)
        self.assertLess(SAPI_SCRIPT.index(capture), SAPI_SCRIPT.index(dispose))
        self.assertLess(SAPI_SCRIPT.index(dispose), SAPI_SCRIPT.index(report))


    def test_qsound_playing_callback_uses_signal_boolean(self):
        started = mock.Mock()
        finished = mock.Mock()
        fake = SimpleNamespace(_fx=object(), _item_began=False,
                               _item_started=started, _item_finished=finished)
        Speaker._on_playing(fake, True)
        started.assert_called_once_with()
        finished.assert_not_called()

        fake._item_began = True
        Speaker._on_playing(fake, False)
        finished.assert_called_once_with()

    def test_player_cleanup_stops_and_deletes_without_manual_disconnect(self):
        class FakePlayer:
            def __init__(self):
                self.stopped = False
                self.deleted = False

            def stop(self):
                self.stopped = True

            def deleteLater(self):
                self.deleted = True

        player, output = FakePlayer(), FakePlayer()
        Speaker._drop_player(SimpleNamespace(), player, output)
        self.assertTrue(player.stopped)
        self.assertTrue(player.deleted)
        self.assertTrue(output.deleted)

if __name__ == "__main__":
    unittest.main()
