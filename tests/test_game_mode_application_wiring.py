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

    def test_bootstrap_injects_service_and_window_has_fallback(self):
        bootstrap = (ROOT / "kira/app/bootstrap.py").read_text(encoding="utf-8")
        window = (ROOT / "kira/ui/main_window.py").read_text(encoding="utf-8")
        self.assertIn("GameModeApplicationService()", bootstrap)
        self.assertIn("game_mode_application_service=game_mode_application_service", bootstrap)
        self.assertIn("game_mode_application_service=None", window)
        self.assertIn("self.game_mode_application_service = game_mode_application_service", window)

    def test_ui_delegates_game_mode_permissions_and_audio_alert_policy(self):
        vision = (ROOT / "kira/ui/main_window_attachments_vision.py").read_text(encoding="utf-8")
        runtime = (ROOT / "kira/ui/main_window_runtime.py").read_text(encoding="utf-8")
        settings = (ROOT / "kira/ui/main_window_voice_settings.py").read_text(encoding="utf-8")
        self.assertNotIn("game_mode_permissions(", vision)
        self.assertNotIn("normalize_game_mode_profile(", vision)
        self.assertNotIn("is_important_game_audio(", vision)
        self.assertNotIn("_game_audio_alerts", vision)
        self.assertIn("classify_game_audio(", vision)
        self.assertIn("command_denial_reason(", runtime)
        self.assertIn("self.game_mode_application_service.STORY_MODE", settings)


if __name__ == "__main__":
    unittest.main()
