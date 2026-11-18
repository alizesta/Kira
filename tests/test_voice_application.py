"""Qt-free tests for Voice application lifecycle orchestration."""
import unittest

from kira.app.voice_application import VoiceApplicationService


class _Signal:
    def __init__(self):
        self.callbacks = []

    def connect(self, callback):
        self.callbacks.append(callback)

    def emit(self, *args):
        for callback in tuple(self.callbacks):
            callback(*args)


class _Listener:
    def __init__(self):
        self.heard = _Signal()
        self.interrupted = _Signal()
        self.state = _Signal()
        self.error = _Signal()
        self.note = _Signal()
        self.finished = _Signal()
        self.running = False
        self.stop_called = False
        self.speaking_started = False
        self.speaking_ended = False
        self.muted = True
        self.kira_level = 0.0

    def start(self):
        self.running = True

    def stop(self):
        self.stop_called = True

    def isRunning(self):
        return self.running

    def begin_kira_speech(self):
        self.speaking_started = True

    def end_kira_speech(self):
        self.speaking_ended = True

    def finish(self):
        self.running = False
        self.finished.emit()


class _Speaker:
    def __init__(self):
        self._began = False
        self.spoken = []
        self.stopped = 0
        self.streamed = []
        self.played = []
        self.reset_count = 0
        self.end_count = 0
        self.settings = {"voice_volume": 70}

    def speak(self, text, rate=None, pitch=None, cache=False):
        self.spoken.append((text, rate, pitch, cache))

    def stop(self):
        self.stopped += 1

    def stream_reset(self):
        self.reset_count += 1

    def stream_text(self, text, final=False):
        self.streamed.append((text, final))

    def stream_end(self):
        self.end_count += 1

    def play_file(self, path):
        self.played.append(path)


class VoiceApplicationServiceTests(unittest.TestCase):
    def setUp(self):
        self.speaker = _Speaker()
        self.created = []
        self.events = []
        self.waiting = []
        self.service = VoiceApplicationService(
            speaker=self.speaker,
            listener_factory=lambda: self.created.append(_Listener()) or self.created[-1],
            on_heard=lambda text: self.events.append(("heard", text)),
            on_interrupted=lambda: self.events.append(("interrupted",)),
            on_state=lambda state: self.events.append(("state", state)),
            on_error=lambda message: self.events.append(("error", message)),
            on_note=lambda message: self.events.append(("note", message)),
            on_finished=lambda listener, was_current, restart: self.events.append(
                ("finished", listener, was_current, restart)
            ),
            on_waiting=lambda: self.waiting.append("waiting"),
        )

    def test_character_voice_overrides_are_isolated_and_allowlisted(self):
        shared = {"voice_rate": 100, "voice_volume": 0.5, "api_key": "never-copy"}
        effective = self.service.apply_character_settings(
            shared,
            {"voice_rate": 140, "voice_volume": 0.8, "api_key": "ignored"},
        )
        self.assertEqual(effective, {"voice_rate": 140, "voice_volume": 0.8, "api_key": "never-copy"})
        self.assertEqual(self.speaker.settings, effective)
        self.assertEqual(shared["voice_rate"], 100)
        self.assertEqual(effective["api_key"], "never-copy")
        self.assertNotEqual(effective["api_key"], "ignored")

    def test_transcript_policy_ignores_speech_without_wake_word_when_asleep(self):
        decision = self.service.interpret_transcript(
            "هوا چطوره؟", wake_enabled=True, awake=False
        )
        self.assertEqual(decision.action, "ignore")

    def test_transcript_policy_wakes_without_forwarding_short_wake_phrase(self):
        decision = self.service.interpret_transcript(
            "سلام کیرا", wake_enabled=True, awake=False
        )
        self.assertEqual(decision.action, "wake_only")

    def test_transcript_policy_extracts_command_after_wake_word(self):
        decision = self.service.interpret_transcript(
            "کیرا هوا چطوره؟", wake_enabled=True, awake=False
        )
        self.assertEqual(decision.action, "wake_submit")
        self.assertEqual(decision.text, "هوا چطوره؟")

    def test_transcript_policy_handles_sleep_stop_and_normal_submission(self):
        self.assertEqual(
            self.service.interpret_transcript(
                "بخواب", wake_enabled=True, awake=True
            ).action,
            "sleep",
        )
        self.assertEqual(
            self.service.interpret_transcript(
                "بس کن", wake_enabled=False, awake=True
            ).action,
            "stop",
        )
        normal = self.service.interpret_transcript(
            "سلام", wake_enabled=False, awake=False
        )
        self.assertEqual((normal.action, normal.text), ("submit", "سلام"))

    def test_voice_service_implements_speech_and_recording_ports(self):
        self.service.start_recording()
        listener = self.service.listener
        self.assertIsNotNone(listener)
        self.assertEqual(len(self.created), 1)
        self.assertTrue(self.created[0].running)

        self.service.speak("hello")
        self.service.stop_speaking()

        self.assertEqual(self.speaker.spoken, [("hello", None, None, False)])
        self.assertEqual(self.speaker.stopped, 1)

    def test_streaming_settings_and_file_playback_are_delegated(self):
        self.service.speak("local", -5, -3, cache=True)
        self.service.stream_reset()
        self.service.stream_text("partial")
        self.service.stream_text("final", final=True)
        self.service.stream_end()
        self.service.play_file("test.wav")

        self.assertEqual(self.speaker.spoken[-1], ("local", -5, -3, True))
        self.assertEqual(self.speaker.reset_count, 1)
        self.assertEqual(self.speaker.streamed, [("partial", False), ("final", True)])
        self.assertEqual(self.speaker.end_count, 1)
        self.assertEqual(self.speaker.played, ["test.wav"])
        self.assertIs(self.service.settings, self.speaker.settings)

    def test_is_speaking_exposes_only_the_playback_state(self):
        self.assertFalse(self.service.is_speaking())
        self.speaker._began = True
        self.assertTrue(self.service.is_speaking())

    def test_listener_signals_are_forwarded_to_application_callbacks(self):
        self.service.start_recording()
        listener = self.created[0]

        listener.heard.emit("سلام")
        listener.interrupted.emit()
        listener.state.emit("listening")
        listener.error.emit("device error")
        listener.note.emit("fallback")

        self.assertEqual(
            self.events,
            [
                ("heard", "سلام"),
                ("interrupted",),
                ("state", "listening"),
                ("error", "device error"),
                ("note", "fallback"),
            ],
        )

    def test_start_waits_for_stopping_listener_before_creating_replacement(self):
        self.service.start_recording()
        old = self.created[0]

        self.service.stop_recording()
        self.assertIsNone(self.service.listener)
        self.assertIs(self.service.stopping_listener, old)
        self.assertTrue(old.stop_called)

        self.service.start_recording()
        self.assertIsNone(self.service.listener)
        self.assertEqual(len(self.created), 1)
        self.assertEqual(self.waiting, ["waiting"])

        old.finish()
        self.assertIsNone(self.service.stopping_listener)
        self.assertEqual(self.events[-1], ("finished", old, False, True))

    def test_finish_reports_current_listener_and_does_not_request_restart_when_not_pending(self):
        self.service.start_recording()
        listener = self.created[0]

        listener.finish()

        self.assertIsNone(self.service.listener)
        self.assertEqual(self.events[-1], ("finished", listener, True, False))

    def test_speech_state_is_forwarded_to_active_listener(self):
        self.service.start_recording()
        listener = self.created[0]

        self.service.begin_speaking()
        self.service.end_speaking()
        self.service.unmute_if_idle()

        self.assertTrue(listener.speaking_started)
        self.assertTrue(listener.speaking_ended)
        self.assertFalse(listener.muted)

    def test_unmute_does_not_override_active_speaker_playback(self):
        self.service.start_recording()
        listener = self.created[0]
        self.speaker._began = True

        self.service.unmute_if_idle()

        self.assertTrue(listener.muted)

    def test_start_replaces_stale_deleted_listener_without_crashing(self):
        class DeletedListener:
            def isRunning(self):
                raise RuntimeError("deleted")

        self.service.stopping_listener = DeletedListener()
        self.service.start_recording()
        self.assertIsNotNone(self.service.listener)
        self.assertIsNone(self.service.stopping_listener)
        self.assertEqual(len(self.created), 1)

    def test_listener_start_failure_does_not_leave_a_false_active_listener(self):
        class BrokenListener(_Listener):
            def start(self):
                raise RuntimeError("device unavailable")

        self.service.listener_factory = BrokenListener
        with self.assertRaisesRegex(RuntimeError, "device unavailable"):
            self.service.start_recording()
        self.assertIsNone(self.service.listener)

    def test_dispose_waits_for_listener_exit_and_is_idempotent(self):
        self.service.start_recording()
        listener = self.created[0]

        self.assertFalse(self.service.dispose())
        self.assertTrue(listener.stop_called)
        self.assertIs(self.service.stopping_listener, listener)

        listener.finish()

        self.assertTrue(self.service.dispose())
        self.assertTrue(self.service.dispose())
        self.assertIsNone(self.service.listener)
        self.assertIsNone(self.service.stopping_listener)
        self.assertEqual(self.speaker.stopped, 2)
        with self.assertRaisesRegex(RuntimeError, "disposed"):
            self.service.start_recording()

    def test_stop_all_stops_both_microphone_and_speaker(self):
        self.service.start_recording()
        listener = self.created[0]

        self.service.stop_all()

        self.assertTrue(listener.stop_called)
        self.assertEqual(self.speaker.stopped, 1)


if __name__ == "__main__":
    unittest.main()
