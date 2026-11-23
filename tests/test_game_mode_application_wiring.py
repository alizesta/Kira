"""Static wiring checks for the Game Mode application boundary."""
import ast
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class GameModeApplicationWiringTests(unittest.TestCase):
    def test_game_mode_service_is_qt_free(self):
        tree = ast.parse((ROOT / "kira/app/game_mode_application.py").read_text(encoding="utf-8"))
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.append(node.module or "")
        self.assertFalse(any(name.startswith(("PySide", "PyQt")) for name in imports))

    def test_bootstrap_injects_service_and_composition_binds_it(self):
        bootstrap = (ROOT / "kira/ui/bootstrap.py").read_text(encoding="utf-8")
        composition = (ROOT / "kira/ui/main_window_composition.py").read_text(encoding="utf-8")
        self.assertIn('game_mode_application_service=container.resolve("game_mode_application_service")', bootstrap)
        self.assertIn("game_mode_application_service=None", composition)

    def test_ui_delegates_game_mode_permissions_and_audio_alert_policy(self):
        vision = (ROOT / "kira/ui/main_window_attachments_vision.py").read_text(encoding="utf-8")
        runtime = (ROOT / "kira/ui/main_window_runtime.py").read_text(encoding="utf-8")
        chat = (ROOT / "kira/ui/main_window_chat.py").read_text(encoding="utf-8")
        settings = (ROOT / "kira/ui/main_window_voice_settings.py").read_text(encoding="utf-8")
        self.assertNotIn("game_mode_permissions(", vision)
        self.assertNotIn("normalize_game_mode_profile(", vision)
        self.assertNotIn("is_important_game_audio(", vision)
        self.assertNotIn("_game_audio_alerts", vision)
        self.assertIn("classify_game_audio(", vision)
        self.assertIn("command_denial_reason(", runtime)
        self.assertIn('game_mode_handler=lambda action: self.feature_controller("attachments_vision").handle_game_mode_command(action)', chat)
        self.assertIn("build_chat_vision_context(", chat)
        self.assertIn("LIVE GAME VISION STATUS:", vision)
        self.assertLess(chat.index("dispatch_commands("), chat.index("_game_vision_attachment()"))
        self.assertIn("self.context.services.game_mode_application_service.STORY_MODE", settings)


if __name__ == "__main__":
    unittest.main()
