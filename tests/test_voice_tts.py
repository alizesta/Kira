"""Regression tests for local Piper playback and Qt audio handling."""
import threading
import unittest
from types import SimpleNamespace
from unittest import mock


from kira.voice import Speaker
from kira.ui.main_window import MainWindow


class LocalTtsPlaybackTests(unittest.TestCase):
    def test_new_speaker_starts_with_neutral_prosody(self):
        from PySide6.QtWidgets import QApplication
        from kira.voice_prosody import resolve_prosody

        app = QApplication.instance() or QApplication([])
        speaker = Speaker({"local_voice_tts": False})
        try:
            self.assertEqual(speaker._prosody, resolve_prosody())
        finally:
            speaker._timer.stop()
            speaker.deleteLater()
            app.processEvents()

    def test_live_provider_selector_refreshes_after_connections_addition(self):
        from PySide6.QtWidgets import QApplication
        from kira.ui.pages.voice_page import VoicePage

        app = QApplication.instance() or QApplication([])
        page = VoicePage({"providers": {}}, lambda key: key)
        try:
            page.refresh_gemini_providers({
                "providers": {
                    "google-main": {
                        "service": "google",
                        "label": "Google AI Studio",
                        "api_key": "AIza-test-key",
                    }
                }
            })
            self.assertEqual(page.gemini_provider.currentData(), "google-main")
        finally:
            page.deleteLater()
            app.processEvents()

    def test_live_provider_selector_preserves_missing_saved_provider(self):
        from PySide6.QtWidgets import QApplication
        from kira.ui.pages.voice_page import VoicePage

        app = QApplication.instance() or QApplication([])
        page = VoicePage({
            "gemini_live_provider": "google-removed",
            "providers": {
                "google-current": {
                    "service": "google",
                    "label": "Current Google",
                    "api_key": "AIza-test-key",
                }
            },
        }, lambda key: key)
        try:
            self.assertEqual(page.gemini_provider.currentData(), "google-removed")
            self.assertIn("پیدا نشد", page.gemini_provider.currentText())
        finally:
            page.deleteLater()
            app.processEvents()

    def test_emotion_profile_updates_active_stream_synthesis(self):
        from kira.voice_prosody import resolve_prosody

        session = SimpleNamespace(streaming=True, prosody={}, cond=threading.Condition())
        speaker = SimpleNamespace(_session=session, _prosody={})
        Speaker.set_emotion(speaker, ["sad"], 100)

        self.assertEqual(session.prosody, resolve_prosody(["sad"], 100))
        self.assertGreater(session.prosody["length_scale"], 1.0)
        self.assertLess(session.prosody["gain_db"], 0.0)

    def test_second_sentence_synthesis_prepends_real_silence(self):
        import io
        import wave

        from kira import local_voice
        from kira.voice_prosody import resolve_prosody

        payload = io.BytesIO()
        with wave.open(payload, "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(1000)
            audio.writeframes(b"\x01\x00" * 10)

        session = SimpleNamespace(
            rate=0,
            pitch=0,
            cache=False,
            gen=1,
            prosody=resolve_prosody(),
            cond=threading.Condition(),
        )
        speaker = SimpleNamespace(
            settings={"local_voice_tts": True, "voice_rate": 0},
            _tmp="/tmp",
            _save_local_wav=mock.Mock(return_value=("cached.wav", [])),
            _report=mock.Mock(),
        )
        with mock.patch.object(local_voice, "tts_ready", return_value=True), \
             mock.patch.object(local_voice, "normalize_persian_tts_text", return_value="سلام"), \
             mock.patch.object(local_voice, "synthesize_persian", return_value=payload.getvalue()):
            result = Speaker._synth(speaker, session, 1, "سلام")

        self.assertEqual(result, ("cached.wav", []))
        assembled = speaker._save_local_wav.call_args.args[1]
        with wave.open(io.BytesIO(assembled), "rb") as audio:
            samples = audio.readframes(audio.getnframes())
            self.assertEqual(audio.getnframes(), 275)
        self.assertEqual(samples[:265 * 2], b"\0" * 265 * 2)
        self.assertEqual(samples[265 * 2:], b"\\x01\\x00" * 10)


    def test_invalid_selected_piper_voice_falls_back_to_local_mana(self):
        import io
        import wave

        from kira import local_voice
        from kira.voice_prosody import resolve_prosody
        from kira import voice as voice_module

        wav = io.BytesIO()
        with wave.open(wav, "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(24000)
            audio.writeframes(bytes(64))

        speaker = Speaker.__new__(Speaker)
        speaker.settings = {"local_voice_tts": True, "voice_rate": 0, "tts_engine": "piper"}
        speaker._tmp = "/tmp/kira-piper-fallback"
        speaker._save_local_wav = mock.Mock(return_value=("fallback.wav", []))
        speaker._report = mock.Mock()
        session = SimpleNamespace(
            rate=0, pitch=0, cache=False, gen=1,
            prosody=resolve_prosody(), cond=threading.Condition(),
        )
        with (
            mock.patch.object(speaker, "_use_kitten", return_value=False),
            mock.patch.object(
                local_voice, "ensure_tts_ready",
                side_effect=[RuntimeError("missing ONNX or JSON"), None],
            ) as prepare,
            mock.patch.object(local_voice, "normalize_persian_tts_text", return_value="سلام"),
            mock.patch.object(local_voice, "synthesize_persian", return_value=wav.getvalue()) as synthesize,
            mock.patch.object(voice_module, "split_comma_clauses", return_value=["سلام"]),
            mock.patch.object(voice_module, "join_wavs_with_pauses", return_value=wav.getvalue()),
            mock.patch.object(voice_module, "apply_audio_effects", side_effect=lambda payload, _profile: payload),
        ):
            result = Speaker._synth(speaker, session, 0, "سلام")

        self.assertEqual(result, ("fallback.wav", []))
        self.assertEqual([call.args[0] for call in prepare.call_args_list], ["custom-voice.onnx", ""])
        self.assertEqual(synthesize.call_args.args[1], "")
        speaker._report.assert_called_once()
        self.assertIn("Mana", speaker._report.call_args.args[0])

    def test_speaker_idle_state_waits_for_real_thread_exit(self):
        class FakeThread:
            def __init__(self):
                self.alive = True

            def is_alive(self):
                return self.alive

        worker = FakeThread()
        speaker = SimpleNamespace(
            _worker_lock=threading.Lock(),
            _worker_threads={worker},
        )

        self.assertFalse(Speaker.is_idle(speaker))
        worker.alive = False
        self.assertTrue(Speaker.is_idle(speaker))
        self.assertEqual(speaker._worker_threads, set())

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


    def test_default_output_falls_back_to_an_enumerated_device(self):
        import kira.voice as voice_module

        class Device:
            def __init__(self, name, null=False):
                self.name = name
                self.null = null

            def isNull(self):
                return self.null

            def description(self):
                return self.name

        fallback = Device("USB Headset")
        speaker = SimpleNamespace(
            settings={"output_device": ""},
            _prefer_default_output=False,
        )
        devices = SimpleNamespace(
            defaultAudioOutput=lambda: Device("", null=True),
            audioOutputs=lambda: [fallback],
        )
        with mock.patch.object(voice_module, "QMediaDevices", devices):
            self.assertIs(Speaker._default_output(speaker), fallback)

    def test_player_is_registered_and_signals_connected_before_start(self):
        speaker = Speaker.__new__(Speaker)
        import kira.voice as voice_module
        order = []

        class Sig:
            def __init__(self, name):
                self.name, self.slots = name, []

            def connect(self, slot):
                self.slots.append(slot)

        class Player:
            def __init__(self, path, device, volume, parent):
                self.playingChanged, self.failed = Sig("p"), Sig("f")
                self.duration_ms = 100

            def start(self):
                order.append((speaker._fx is self, bool(self.playingChanged.slots), bool(self.failed.slots)))

        speaker._tmp = "/tmp/kira_tts"
        speaker.settings = {}
        speaker._watch_devices = lambda: None
        speaker._default_output = lambda: object()
        speaker._on_playing = lambda *_: None
        speaker._on_player_failed = lambda *_: None
        speaker._on_playing_end = lambda *_: None
        with mock.patch.object(voice_module, "_PcmPlayer", Player), \
             mock.patch.object(voice_module, "QTimer", SimpleNamespace(singleShot=mock.Mock())):
            Speaker._start_playback(speaker, SimpleNamespace(keep=True), "/tmp/test.wav", [])
        self.assertEqual(order, [(True, True, True)])


if __name__ == "__main__":
    unittest.main()
