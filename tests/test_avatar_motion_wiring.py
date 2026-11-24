"""Application event wiring for the avatar's live listening and speaking states."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class AvatarListeningWiringTests(unittest.TestCase):
    def test_local_listener_and_gemini_live_drive_listening_state(self):
        source = (ROOT / "kira" / "ui" / "main_window_runtime_voice.py").read_text(encoding="utf-8")
        self.assertIn('self.context.adapters.director.event("listening_started")', source)
        self.assertIn('self.context.adapters.director.event("listening_stopped")', source)
        self.assertIn('if state in ("listening", "hearing"):', source)
        self.assertIn('elif state == "gemini_live":', source)

    def test_gemini_live_audio_drives_speaking_and_mouth_animation(self):
        worker = (ROOT / "kira" / "gemini_live.py").read_text(encoding="utf-8")
        runtime = (ROOT / "kira" / "ui" / "main_window_runtime_voice.py").read_text(encoding="utf-8")
        self.assertIn("audio_playback_changed = Signal(bool)", worker)
        self.assertIn("audio_level = Signal(float)", worker)
        self.assertIn("audio_playback_changed.connect(self._on_gemini_audio_playback)", runtime)
        self.assertIn("audio_level.connect(self.context.adapters.animator.set_mouth_target)", runtime)

    def test_event_table_releases_listening_for_thinking_and_speaking(self):
        import json
        events = json.loads((ROOT / "emotion_library" / "events.json").read_text(encoding="utf-8"))["events"]
        self.assertTrue(events["listening_started"]["listening"])
        self.assertFalse(events["listening_stopped"]["listening"])
        self.assertFalse(events["response_started"]["listening"])
        self.assertFalse(events["tts_started"]["listening"])


if __name__ == "__main__":
    unittest.main()
