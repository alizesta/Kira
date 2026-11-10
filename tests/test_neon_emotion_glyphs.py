"""Regression checks for Kira's neon emotion indicator.

These checks intentionally use only the standard library so CI can run them
without booting Qt or the desktop application.
"""
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class NeonEmotionGlyphTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.icons = (ROOT / "kira" / "ui_icons.py").read_text(encoding="utf-8")
        cls.main = (ROOT / "kira" / "main.py").read_text(encoding="utf-8")
        cls.update_method = cls.main.split(
            "    def update_mood_indicator(self):", 1
        )[1].split("    def chat_actions_html(self, kind, text):", 1)[0]

    def test_vector_emotion_glyph_renderer_exists(self):
        self.assertIn("def _emotion_shapes(name):", self.icons)
        self.assertIn('startswith("emotion_")', self.icons)
        self.assertIn("QPainterPath", self.icons)

    def test_live_emotion_uses_neon_vector_icon(self):
        self.assertIn('make_icon(\n                f"emotion_{icon_name}"', self.update_method)
        self.assertIn("face_label.setPixmap", self.update_method)
        self.assertIn("emotion_colors", self.update_method)

    def test_chat_emojis_are_not_rewritten_by_mood_indicator(self):
        self.assertIn("self.chat.append(message_html(kind, name, text, ui_dir, extra, footer))", self.main)
        self.assertIn("self.mood_emotion_icon", self.main)
        self.assertNotIn("behaviour_icons", self.update_method)
        self.assertNotIn("😜", self.update_method)
        self.assertIn('"energy_bolt"', self.update_method)
        self.assertIn('if name == "energy_bolt":', self.icons)


if __name__ == "__main__":
    unittest.main()
