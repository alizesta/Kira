"""Task 01: voice stop/cleanup is re-entrancy safe, idempotent, and a voice problem can never block the chat.

Real audio playback segfaults in a headless sandbox, so playback objects are faked; the fakes reproduce the real Qt
behaviour that caused the bug (QMediaPlayer.stop() emits playbackStateChanged, which calls Speaker.stop() again)."""
import os
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from tests import helpers
from tests.helpers import StreamResp, sse

try:
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QCoreApplication
    from PySide6.QtMultimedia import QMediaPlayer
    HAVE_QT = True
except Exception:                                    # pragma: no cover
    HAVE_QT = False

import time
from kira import config, memory

if HAVE_QT:
    APP = QApplication.instance() or QApplication([])
    from kira.voice import Speaker


class FakeSignal:
    def __init__(self):
        self.slots = []

    def connect(self, slot):
        self.slots.append(slot)

    def disconnect(self, slot):
        self.slots.remove(slot)


class FakeFx:
    """Mimics QMediaPlayer: stop() emits the state change, which makes Speaker.stop() run again (once)."""
    def __init__(self, speaker, reenter=True, explode=False):
        self.speaker, self.reenter, self.explode = speaker, reenter, explode
        self.stops = self.deleted = 0
        self.playbackStateChanged = FakeSignal()

    def stop(self):
        self.stops += 1
        if self.explode:
            raise RuntimeError("Internal C++ object (QMediaPlayer) already deleted.")
        if self.reenter:
            self.reenter = False
            self.speaker._on_pstate(QMediaPlayer.StoppedState)       # the real slot, called from inside stop()

    def deleteLater(self):
        self.deleted += 1
        if self.explode:
            raise RuntimeError("Internal C++ object (QMediaPlayer) already deleted.")


class Out:
    def __init__(self):
        self.deleted = 0

    def deleteLater(self):
        self.deleted += 1


@unittest.skipUnless(HAVE_QT, "PySide6 not installed")
class SpeakerStopTests(unittest.TestCase):
    def setUp(self):
        self.sp = Speaker({"voice_volume": 0.5})
        self.finished = []
        self.errors = []
        self.sp.finished.connect(lambda: self.finished.append(1))
        self.sp.error.connect(self.errors.append)

    def tearDown(self):
        self.sp._timer.stop()

    def test_stop_called_again_from_inside_the_players_stop_signal(self):
        """The original crash: AttributeError 'NoneType' object has no attribute 'deleteLater'."""
        fx, out = FakeFx(self.sp), Out()
        self.sp._fx, self.sp._out, self.sp._began = fx, out, True
        self.sp.stop()                                                   # must not raise
        self.assertIsNone(self.sp._fx)
        self.assertIsNone(self.sp._out)
        self.assertEqual((fx.stops, fx.deleted, out.deleted), (1, 1, 1))  # released exactly once
        self.assertEqual(len(self.finished), 1)                          # 'finished' announced exactly once
        self.assertFalse(self.sp._began)

    def test_stop_many_times_with_nothing_playing(self):
        for _ in range(10):
            self.sp.stop()
        self.assertEqual(self.finished, [])
        self.assertIsNone(self.sp._fx)

    def test_stop_repeated_during_playback_is_idempotent(self):
        fx = FakeFx(self.sp, reenter=False)
        self.sp._fx, self.sp._began = fx, True
        for _ in range(5):
            self.sp.stop()
        self.assertEqual((fx.stops, fx.deleted, len(self.finished)), (1, 1, 1))

    def test_player_whose_cpp_object_is_already_deleted(self):
        fx = FakeFx(self.sp, explode=True)
        self.sp._fx, self.sp._began = fx, True
        self.sp.stop()
        self.sp.stop()
        self.assertIsNone(self.sp._fx)
        self.assertEqual(len(self.finished), 1)

    def test_stop_without_the_new_attributes_state_is_consistent(self):
        self.sp._fx = None
        self.sp._out = None
        self.sp.stop()
        self.sp.stop()
        self.assertEqual(self.finished, [])

    def test_late_signal_from_a_released_player_is_ignored(self):
        fx = FakeFx(self.sp, reenter=False)
        self.sp._fx, self.sp._began = fx, True
        self.sp.stop()
        self.sp._on_pstate(QMediaPlayer.PlayingState)                    # stale event after stop
        self.sp._on_playing()
        self.sp._on_sound_status()
        self.assertFalse(self.sp._began)
        self.assertFalse(self.sp._timer.isActive())

    def test_speak_never_raises_and_reports_instead(self):
        with mock.patch("kira.voice.threading.Thread", side_effect=RuntimeError("cannot start thread")):
            self.sp.speak("سلام")                                          # must not raise
        self.assertEqual(len(self.errors), 1)
        self.assertIn("cannot start thread", self.errors[0])
        self.sp.speak("")                                                  # empty text: silently nothing
        self.sp.speak("   ")
        self.assertEqual(len(self.errors), 1)

    def test_stop_failure_inside_speak_is_reported_not_raised(self):
        with mock.patch.object(Speaker, "stop", side_effect=RuntimeError("boom")):
            self.sp.speak("سلام")
            self.sp.play_file("x.wav")
        self.assertEqual(len(self.errors), 2)

    def test_player_creation_failure_is_reported_and_cleaned_up(self):
        with mock.patch.object(Speaker, "_watch_devices"), mock.patch("kira.voice.QAudioOutput", side_effect=RuntimeError("no audio device")):
            self.sp._new_session(None, None, False)
            self.sp._on_ready(self.sp._gen, 0, "somefile.mp3", [])          # mp3 path builds a QAudioOutput first
        self.assertEqual(len(self.errors), 1)
        self.assertIn("no audio device", self.errors[0])
        self.assertIsNone(self.sp._fx)
        self.sp.stop()

    def test_stale_generation_result_is_dropped_without_touching_a_player(self):
        tmp = os.path.join(self.sp._tmp, "old.wav")
        open(tmp, "wb").write(b"x")
        self.sp._on_ready(self.sp._gen - 1, 0, tmp, [])
        self.assertFalse(os.path.exists(tmp))
        self.assertIsNone(self.sp._fx)


@unittest.skipUnless(HAVE_QT, "PySide6 not installed")
class VoiceNeverBlocksChatTests(unittest.TestCase):
    def setUp(self):
        d = config.DATA_DIR / "voice_case"
        d.mkdir(exist_ok=True)
        self.path = d / "settings.json"
        if self.path.exists():
            self.path.unlink()
        prot, unprot = helpers.fake_dpapi()
        self.patches = [mock.patch.object(config, "CONFIG_PATH", self.path),
                        mock.patch.object(config, "protect", prot), mock.patch.object(config, "unprotect", unprot),
                        mock.patch("requests.get", side_effect=__import__("requests").ConnectionError("off"))]
        for p in self.patches:
            p.start()
        memory.init_db()
        memory.clear_memory()
        from kira.ui.main_window import MainWindow
from kira.theme import STYLE
        APP.setStyleSheet(STYLE)
        self.win = MainWindow()
        self.win.show()
        APP.processEvents()
        w = self.win
        helpers.enable(w.settings, "groq")
        w.settings["providers"]["ollama"]["enabled"] = False
        from kira import routes
        routes.ensure_routes(w.settings)
        from kira.hybrid_ai import HybridRouter
        w.client = HybridRouter(w.settings)

    def tearDown(self):
        w = self.win
        w.client.cancel()
        if getattr(w, "worker", None) is not None:
            w.worker.wait(3000)
        w.companion.close()
        w.close()
        APP.processEvents()
        for p in self.patches:
            p.stop()

    def send_and_wait(self, text):
        self.win.input.setText(text)
        self.win.send_message()
        end = time.time() + 8
        while time.time() < end and self.win.busy:
            QCoreApplication.processEvents()
            time.sleep(0.01)
        self.assertFalse(self.win.busy)

    def reply(self, text):
        return mock.patch("requests.post", side_effect=lambda *a, **k: StreamResp(sse(text)))

    def test_stop_raising_does_not_stop_the_message_from_being_sent(self):
        w = self.win
        w.set_voice_enabled(True)
        with mock.patch.object(w.speaker, "stop", side_effect=RuntimeError("deleteLater boom")), self.reply("پاسخ سالم"), \
                mock.patch.object(w.speaker, "speak"):
            self.send_and_wait("سلام")
        text = w.chat.toPlainText()
        self.assertIn("سلام", text)
        self.assertIn("پاسخ سالم", text)
        self.assertEqual(memory.recent_messages(5)[-1]["content"], "پاسخ سالم")
        self.assertTrue(w.send_btn.isEnabled())

    def test_speak_raising_keeps_the_reply_and_reports_once(self):
        w = self.win
        w.set_voice_enabled(True)
        with mock.patch.object(w.speaker, "speak", side_effect=RuntimeError("tts exploded")), \
                mock.patch.object(w.speaker, "stream_text", side_effect=RuntimeError("tts exploded")), self.reply("جواب"):
            self.send_and_wait("یک")
            self.send_and_wait("دو")
        text = w.chat.toPlainText()
        self.assertEqual(text.count("جواب"), 2)
        self.assertEqual(text.count("tts exploded"), 1)                    # voice errors are rate-limited (10 min)
        self.assertFalse(w.busy)

    def test_voice_error_signal_then_next_message_still_works(self):
        w = self.win
        w.speaker.error.emit("Piper local TTS: model unavailable")
        with self.reply("ادامه"):
            self.send_and_wait("پیام")
        self.assertIn("ادامه", w.chat.toPlainText())

    def test_tts_off_never_calls_the_speaker(self):
        w = self.win
        w.set_voice_enabled(False)
        with mock.patch.object(w.speaker, "speak") as speak, self.reply("خاموش"):
            self.send_and_wait("hi")
        speak.assert_not_called()
        self.assertIn("خاموش", w.chat.toPlainText())

    def test_tts_on_calls_the_speaker_with_the_reply_text(self):
        w = self.win
        w.set_voice_enabled(True)
        with mock.patch.object(w.speaker, "speak") as speak, self.reply("[happy]\nروشن"):
            self.send_and_wait("hi")
        speak.assert_called_once_with("روشن")

    def test_toggle_voice_and_stop_button_repeatedly_while_a_player_exists(self):
        w = self.win
        for i in range(6):
            fx = FakeFx(w.speaker)
            w.speaker._fx, w.speaker._began = fx, True
            w.set_voice_enabled(i % 2 == 0)
            w.stop_btn.click()
            w.stop_btn.click()
            w.speaker.stop()
            w.speaker.stop()
            self.assertEqual(fx.deleted, 1)
        self.assertIsNone(w.speaker._fx)

    def test_closing_the_window_while_a_player_exists(self):
        w = self.win
        fx = FakeFx(w.speaker)
        w.speaker._fx, w.speaker._began = fx, True
        w.close()
        self.assertEqual(fx.deleted, 1)
        self.assertIsNone(w.speaker._fx)


if __name__ == "__main__":
    unittest.main()
