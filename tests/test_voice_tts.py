"""Regression tests for local Piper playback and Qt audio handling."""
import unittest
from types import SimpleNamespace
from unittest import mock

from PySide6.QtMultimedia import QSoundEffect

from kira.voice import Speaker
from kira.ui.main_window import MainWindow


class LocalTtsPlaybackTests(unittest.TestCase):
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

    def test_qsound_playing_callback_supports_no_argument_signal(self):
        started = mock.Mock()
        finished = mock.Mock()
        player = SimpleNamespace(isPlaying=mock.Mock(return_value=True))
        fake = SimpleNamespace(_fx=player, _item_began=False,
                               _item_started=started, _item_finished=finished)

        Speaker._on_playing(fake)
        player.isPlaying.assert_called_once_with()
        started.assert_called_once_with()
        finished.assert_not_called()

        fake._item_began = True
        player.isPlaying.return_value = False
        Speaker._on_playing(fake)
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


    def test_local_tts_playback_callbacks_report_real_playback_state(self):
        class Status:
            def __init__(self):
                self.value = ""
            def setText(self, value):
                self.value = value

        fake = SimpleNamespace(_local_tts_test_active=True, local_voice_status=Status())
        MainWindow._on_local_tts_playback_started(fake)
        self.assertIn("پخش TTS شروع شد", fake.local_voice_status.value)

        MainWindow._on_local_tts_playback_finished(fake)
        self.assertIn("صدا کامل پخش شد", fake.local_voice_status.value)
        self.assertFalse(fake._local_tts_test_active)

    def test_local_tts_playback_error_is_not_hidden(self):
        class Status:
            def __init__(self):
                self.value = ""
            def setText(self, value):
                self.value = value

        fake = SimpleNamespace(_local_tts_test_active=True, local_voice_status=Status())
        MainWindow._on_local_tts_playback_error(fake, "device unavailable")
        self.assertIn("device unavailable", fake.local_voice_status.value)
        self.assertFalse(fake._local_tts_test_active)


    def test_sound_error_is_reported_before_stop_can_emit_finished(self):
        events = []
        fake = SimpleNamespace(
            _fx=SimpleNamespace(status=lambda: QSoundEffect.Error),
            error=SimpleNamespace(emit=lambda _message: events.append("error")),
            stop=lambda: events.append("stop"),
        )
        Speaker._on_sound_status(fake)
        self.assertEqual(events, ["error", "stop"])

    def test_device_change_is_reported_before_playback_is_cancelled(self):
        events = []
        fake = SimpleNamespace(
            _fx=object(),
            error=SimpleNamespace(emit=lambda _message: events.append("error")),
            stop=lambda: events.append("stop"),
        )
        Speaker._on_devices_changed(fake)
        self.assertEqual(events, ["error", "stop"])

    def test_device_change_forces_system_default_instead_of_stale_selection(self):
        events = []
        fake = SimpleNamespace(
            _fx=object(),
            _prefer_default_output=False,
            error=SimpleNamespace(emit=lambda _message: events.append("error")),
            stop=lambda: events.append("stop"),
        )
        Speaker._on_devices_changed(fake)
        self.assertTrue(fake._prefer_default_output)
        self.assertEqual(events, ["error", "stop"])

    def test_sound_error_switches_future_playback_to_system_default(self):
        events = []
        fake = SimpleNamespace(
            _fx=SimpleNamespace(status=lambda: QSoundEffect.Error),
            _prefer_default_output=False,
            error=SimpleNamespace(emit=lambda _message: events.append("error")),
            stop=lambda: events.append("stop"),
        )
        Speaker._on_sound_status(fake)
        self.assertTrue(fake._prefer_default_output)
        self.assertEqual(events, ["error", "stop"])

    def test_stop_emits_cancelled_for_an_active_session(self):
        import threading

        events = []
        session = SimpleNamespace(
            streaming=False,
            input_done=True,
            cond=threading.Condition(),
            ready={},
        )
        fake = SimpleNamespace(
            _gen=0,
            _timer=SimpleNamespace(stop=lambda: None),
            _session=session,
            _fx=None,
            _out=None,
            _drop_player=lambda _fx, _out: None,
            _end=lambda: None,
            cancelled=SimpleNamespace(emit=lambda: events.append("cancelled")),
        )
        Speaker.stop(fake)
        self.assertEqual(events, ["cancelled"])

    def test_cancelled_local_tts_test_does_not_report_success(self):
        class Status:
            def __init__(self):
                self.value = ""
            def setText(self, value):
                self.value = value

        fake = SimpleNamespace(_local_tts_test_active=True, local_voice_status=Status())
        MainWindow._on_local_tts_playback_cancelled(fake)
        self.assertIn("متوقف شد", fake.local_voice_status.value)
        self.assertFalse(fake._local_tts_test_active)

    def test_cancel_callback_ignores_normal_speech(self):
        class Status:
            def setText(self, value):
                raise AssertionError("normal speech must not alter the local TTS test log")

        fake = SimpleNamespace(_local_tts_test_active=False, local_voice_status=Status())
        MainWindow._on_local_tts_playback_cancelled(fake)

    def test_local_tts_playback_callbacks_ignore_normal_speech(self):
        class Status:
            def setText(self, value):
                raise AssertionError("normal speech must not alter the local TTS test log")

        fake = SimpleNamespace(_local_tts_test_active=False, local_voice_status=Status())
        MainWindow._on_local_tts_playback_started(fake)
        MainWindow._on_local_tts_playback_finished(fake)
        MainWindow._on_local_tts_playback_error(fake, "unrelated")

if __name__ == "__main__":
    unittest.main()
