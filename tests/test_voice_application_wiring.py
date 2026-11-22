"""Static contracts for voice/chat UI ports and the thin Qt host."""
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class VoiceApplicationWiringTests(unittest.TestCase):
    def read(self, path):
        return (ROOT / path).read_text(encoding="utf-8")

    def test_main_window_does_not_compose_or_own_voice_services(self):
        source = self.read("kira/ui/main_window.py")
        self.assertIn("class MainWindow(QMainWindow)", source)
        self.assertIn("voice_listener_finished = Signal", source)
        self.assertNotIn("voice_application_service", source)
        self.assertNotIn("create_voice_application_ports", source)
        self.assertNotIn("Speaker(", source)

    def test_voice_ports_resolve_callbacks_from_feature_owners(self):
        adapters = self.read("kira/ui/application_adapters.py")
        composition = self.read("kira/ui/main_window_composition.py")
        for owner in ("runtime", "session", "voice_settings"):
            self.assertIn(f'context.controllers.require("{owner}")', adapters)
        self.assertIn("context.host.voice_listener_finished.emit", adapters)
        self.assertNotIn("window.", adapters)
        self.assertIn(
            "create_voice_application_ports(self, self.adapters.speaker)",
            composition,
        )

    def test_microphone_toggle_preserves_handoff_and_reports_listening(self):
        composer = self.read("kira/ui/components/chat_composer.py")
        runtime_voice = self.read("kira/ui/main_window_runtime_voice.py")
        runtime = self.read("kira/ui/main_window_runtime.py")

        self.assertIn("self.mic_btn.toggled.connect(owner.toggle_mic)", composer)
        self.assertIn("pending_gemini = bool(", runtime_voice)
        self.assertIn("self._set_mic_checked(keep_listening)", runtime_voice)
        self.assertIn("در حال گوش‌دادن · Gemini Live", runtime_voice)
        self.assertIn("در حال گوش‌دادن · STT محلی", runtime_voice)

        completion = runtime.split("    def on_stream_done(self, res):", 1)[1].split(
            "\n    def on_error(", 1
        )[0]
        self.assertLess(
            completion.index("speech_live = bool(self.context.session._speech_live)"),
            completion.index("self.finish_request(res)"),
        )
        self.assertIn("if speech_live:", completion)

    def test_live_transcript_is_replaceable_and_assistant_reply_is_already_streamed(self):
        adapters = self.read("kira/ui/application_adapters.py")
        listener = self.read("kira/listener.py")
        runtime_voice = self.read("kira/ui/main_window_runtime_voice.py")
        runtime = self.read("kira/ui/main_window_runtime.py")
        service = self.read("kira/app/voice_application.py")
        self.assertIn('"partial": ("partial_heard", "text")', adapters)
        self.assertIn('listener.subscribe("partial", self.on_partial)', service)
        self.assertIn("def _maybe_emit_partial", listener)
        self.assertIn("segmenter.snapshot()", listener)
        self.assertIn("self._clear_voice_preview()", runtime_voice)
        self.assertIn("def on_voice_partial", runtime_voice)
        self.assertIn("cursor.removeSelectedText()", runtime_voice)
        self.assertIn("self._speak_stream(text)", runtime)
        self.assertIn("session.timer.setInterval(60)", self.read("kira/ui/main_window_session.py"))

    def test_gemini_live_transcripts_are_persisted_to_the_active_chat(self):
        worker = self.read("kira/gemini_live.py")
        runtime_voice = self.read("kira/ui/main_window_runtime_voice.py")
        runtime = self.read("kira/ui/main_window_runtime.py")

        self.assertIn('"input_audio_transcription": types.AudioTranscriptionConfig()', worker)
        self.assertIn('"output_audio_transcription": types.AudioTranscriptionConfig()', worker)
        self.assertIn('self.feature_controller("runtime").save_message(', runtime_voice)
        self.assertIn('"source": "gemini_live"', runtime_voice)
        self.assertIn('"modality": "audio"', runtime_voice)
        self.assertIn("use_current_request=False", runtime_voice)
        self.assertIn("persist_message(", runtime)
        self.assertIn("if use_current_request else None", runtime)

    def test_tray_exit_delegates_to_close_event_shutdown(self):
        lifecycle = self.read("kira/ui/main_window_lifecycle.py")
        start = lifecycle.index("    def quit_app(self):")
        end = lifecycle.find("\n    def ", start + 5)
        method = lifecycle[start:end if end >= 0 else len(lifecycle)]
        self.assertIn("self.window.close()", method)
        self.assertNotIn("app.quit()", method)
        self.assertIn("closeEvent", self.read("kira/ui/main_window_runtime.py"))

    def test_chat_ports_use_context_and_preserve_shared_skill_enrichment(self):
        adapters = self.read("kira/ui/application_adapters.py")
        composition = self.read("kira/ui/main_window_composition.py")
        self.assertIn("def create_chat_application_ports", adapters)
        self.assertIn('context.controllers.require("chat")', adapters)
        self.assertIn("def _enrich_chat_prompt", adapters)
        self.assertIn("shared_skills_application_service", adapters)
        self.assertIn("create_chat_application_ports(self)", composition)
        self.assertNotIn("window.", adapters)


if __name__ == "__main__":
    unittest.main()
