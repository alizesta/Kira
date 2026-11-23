"""Regression coverage for neon effects on Qt action and widget objects."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest
from types import SimpleNamespace

try:
    from PySide6.QtGui import QAction
    from PySide6.QtWidgets import QApplication, QPushButton
    from kira.ui.appearance_runtime import AppearanceRuntime

    HAVE_QT = True
except Exception:  # pragma: no cover - optional GUI dependency in minimal environments
    HAVE_QT = False


@unittest.skipUnless(HAVE_QT, "PySide6 not installed")
class AppearanceRuntimeGlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_neon_glow_skips_qaction_and_still_styles_qwidgets(self):
        button = QPushButton()
        wake_action = QAction("Wake", button)
        session = SimpleNamespace(
            theme_for_character=lambda _character_id, _profile: {
                "second": "#55DDF5",
                "main": "#A78BFA",
            }
        )
        context = SimpleNamespace(
            services=SimpleNamespace(
                settings={},
                character_service=SimpleNamespace(
                    active_id=lambda _settings: "kira",
                    all_profiles=lambda _settings: {"kira": {}},
                ),
            ),
            controllers=SimpleNamespace(require=lambda name: session if name == "session" else None),
            views=SimpleNamespace(menu_btn=button, wake_btn=wake_action),
        )

        runtime = AppearanceRuntime(context)
        runtime._apply_neon_glow_effects({"glow": 58})

        self.assertIsNotNone(button.graphicsEffect())
        self.assertIn(button, runtime._neon_widget_effects)
        self.assertNotIn(wake_action, runtime._neon_widget_effects)


if __name__ == "__main__":
    unittest.main()
