"""Tests for scoped dependencies across MainWindow feature mixins."""
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / "kira" / "ui"


class MainWindowFeatureDependencyTests(unittest.TestCase):
    FEATURES = {
        "main_window.py": "root",
        "main_window_attachments_vision.py": "attachments_vision",
        "main_window_character_settings.py": "character_settings",
        "main_window_chat.py": "chat",
        "main_window_lifecycle.py": "lifecycle",
        "main_window_provider_settings.py": "provider_settings",
        "main_window_runtime.py": "runtime",
        "main_window_session.py": "session",
        "main_window_voice_settings.py": "voice_settings",
    }

    def test_each_feature_uses_its_scoped_dependency_module(self):
        for filename, feature in self.FEATURES.items():
            source = (UI / filename).read_text(encoding="utf-8")
            self.assertIn(
                f"from .main_window_{feature}_support import *",
                source,
                filename,
            )
            self.assertNotIn("from .main_window_support import *", source, filename)

    def test_shared_support_contains_only_cross_feature_helpers_and_relays(self):
        source = (UI / "main_window_support.py").read_text(encoding="utf-8")
        forbidden = (
            "from ..hybrid_ai import",
            "from ..voice import",
            "from ..listener import",
            "from ..vision_pipeline import",
            "from .. import routes",
            "from .. import websearch",
            "from ..tools import",
            "from ..chat.application_service import",
        )
        for dependency in forbidden:
            self.assertNotIn(dependency, source)
        self.assertIn("class SessionRelay", source)
        self.assertIn("def front_only", source)
        self.assertIn("def load_reactions", source)

    def test_feature_support_modules_do_not_import_other_feature_mixins(self):
        for path in UI.glob("main_window_*_support.py"):
            source = path.read_text(encoding="utf-8")
            for line in source.splitlines():
                if line.startswith("from .main_window_"):
                    self.assertEqual(
                        line,
                        "from .main_window_support import " + line.split(" import ", 1)[1],
                        str(path),
                    )

    def test_every_feature_support_module_exists(self):
        for feature in self.FEATURES.values():
            self.assertTrue(
                (UI / f"main_window_{feature}_support.py").is_file(),
                feature,
            )


if __name__ == "__main__":
    unittest.main()
