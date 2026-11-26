"""Regression checks for the live neon emotion indicator wiring."""
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class NeonEmotionGlyphTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.icons = (ROOT / "kira" / "ui_icons.py").read_text(encoding="utf-8")
        cls.session = (ROOT / "kira" / "ui" / "main_window_session.py").read_text(encoding="utf-8")
        cls.header = (ROOT / "kira" / "ui" / "components" / "chat_header.py").read_text(encoding="utf-8")
        cls.update_method = cls.session.split(
            "    def update_mood_indicator(self):", 1
        )[1].split("    def _chat_action_icon_url", 1)[0]

    def test_svg_emotion_glyph_renderer_and_assets_exist(self):
        self.assertIn("QSvgRenderer", self.icons)
        self.assertIn("def _svg_pixmap(source, colour):", self.icons)
        self.assertIn('startswith("emotion_")', self.icons)
        self.assertTrue((ROOT / "assets" / "icons" / "emotion_happy.svg").is_file())
        self.assertTrue((ROOT / "assets" / "icons" / "emotion_neutral.svg").is_file())

    def test_hidden_header_face_is_explicitly_shown_by_live_mood_update(self):
        self.assertIn("self.mood_emotion_icon.hide()", self.header)
        self.assertIn('f"emotion_{icon_name}"', self.update_method)
        self.assertIn("face_label.setPixmap", self.update_method)
        self.assertIn("face_label.setVisible(True)", self.update_method)
        self.assertIn("emotion_colors", self.update_method)

    def test_energy_bolt_is_separate_from_the_emotion_face(self):
        self.assertIn('"energy_bolt"', self.update_method)
        self.assertIn("show_bolt =", self.update_method)
        self.assertIn("label.setVisible(False)", self.update_method)
        self.assertIn("face_label.setVisible(True)", self.update_method)


if __name__ == "__main__":
    unittest.main()
