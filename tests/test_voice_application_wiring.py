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
