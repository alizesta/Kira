"""Static wiring checks for the Voice application boundary."""
import ast
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class VoiceApplicationWiringTests(unittest.TestCase):
    def test_voice_application_service_is_qt_free(self):
        tree = ast.parse((ROOT / "kira/app/voice_application.py").read_text(encoding="utf-8"))
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.append(node.module or "")
        self.assertFalse(any(name.startswith(("PySide", "PyQt")) for name in imports))

    def test_outer_composition_injects_voice_factory_and_typed_ports(self):
        bootstrap = (ROOT / "kira/ui/bootstrap.py").read_text(encoding="utf-8")
        modules = (ROOT / "kira/app/feature_modules.py").read_text(encoding="utf-8")
        composition = (ROOT / "kira/ui/main_window_composition.py").read_text(encoding="utf-8")
        adapters = (ROOT / "kira/ui/application_adapters.py").read_text(encoding="utf-8")
        window = (ROOT / "kira/ui/main_window.py").read_text(encoding="utf-8")
        self.assertIn('voice_application_service_factory=container.resolve("voice_application_service_factory")', bootstrap)
        self.assertIn("create_voice_application_service_factory", modules)
        self.assertIn("voice_application_service_factory(create_voice_application_ports(self, self.speaker))", composition)
        self.assertIn("QtVoiceListenerAdapter", adapters)
        self.assertIn("QtSpeakerAdapter", adapters)
        self.assertIn("voice_application_service_factory=None", window)

    def test_ui_delegates_voice_policy_and_worker_lifecycle(self):
        runtime = (ROOT / "kira/ui/main_window_runtime.py").read_text(encoding="utf-8")
        chat = (ROOT / "kira/ui/main_window_chat.py").read_text(encoding="utf-8")
        self.assertNotIn("self.speaker._began", runtime + chat)
        self.assertNotIn("self.speaker.stream_", runtime)
        self.assertNotIn("self.speaker.speak(", runtime)
        self.assertNotIn("self.speaker.stop()", runtime)
        self.assertNotIn("self.listener = ", runtime)
        self.assertIn("interpret_transcript(", runtime)
        self.assertIn("start_recording()", runtime)
        self.assertIn("stop_recording()", runtime)

    def test_all_voice_consumers_use_the_application_service(self):
        paths = (
            "kira/ui/main_window_chat.py",
            "kira/ui/main_window_runtime.py",
            "kira/ui/main_window_session.py",
            "kira/ui/main_window_voice_settings.py",
            "kira/ui/main_window_character_settings.py",
            "kira/ui/main_window_attachments_vision.py",
        )
        for relative in paths:
            source = (ROOT / relative).read_text(encoding="utf-8")
            self.assertNotIn("self.speaker.", source, relative)


if __name__ == "__main__":
    unittest.main()
