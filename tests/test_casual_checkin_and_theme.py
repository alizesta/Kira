import unittest

from kira import theme
from kira.character.initiative import CASUAL_CHECKINS, build_casual_message


class CasualCheckinTests(unittest.TestCase):
    def test_messages_rotate_and_follow_language(self):
        fa = {build_casual_message("fa", i) for i in range(8)}
        self.assertEqual(fa, set(CASUAL_CHECKINS["fa"]))
        self.assertIn(build_casual_message("en", 1), CASUAL_CHECKINS["en"])
        self.assertTrue(build_casual_message("fa", "bad"))


class AppearanceTintTests(unittest.TestCase):
    def test_default_appearance_leaves_character_colours_alone(self):
        self.assertEqual(theme.appearance_tint((10, 10, 28), {}), (10, 10, 28))

    def test_brightness_and_background_colour_change_the_tint(self):
        bright = theme.appearance_tint((10, 10, 28), {"brightness": 150})
        dark = theme.appearance_tint((10, 10, 28), {"brightness": 50})
        self.assertGreater(sum(bright), sum(theme.appearance_tint((10, 10, 28), {})))
        self.assertLess(sum(dark), sum(bright))
        self.assertNotEqual(theme.appearance_tint((10, 10, 28), {"background_color": "#204060"}), (10, 10, 28))

    def test_card_style_follows_brightness(self):
        t = theme.CHARACTER_THEMES["kira"]
        self.assertNotEqual(theme.character_style(t, "off", {"brightness": 140}), theme.character_style(t, "off", {"brightness": 60}))


if __name__ == "__main__":
    unittest.main()


class UnslopThemeTests(unittest.TestCase):
    def test_palette_is_preserved_without_decorative_gradients(self):
        css = theme.build_style()
        self.assertIn("#0A0A1C", css)
        self.assertIn("#8C63FF", css)
        self.assertIn("#35D9F2", css)
        self.assertNotIn("qlineargradient", css.lower())
        self.assertNotIn("font-weight: 800", css)
        self.assertNotIn("font-weight: 900", css)

    def test_appearance_controls_still_affect_generated_style(self):
        default = theme.build_style("off", {})
        brighter = theme.build_style("off", {"background_color": "#203040", "brightness": 120})
        acrylic = theme.build_style("acrylic", {})
        self.assertNotEqual(default, brighter)
        self.assertNotEqual(default, acrylic)

    def test_character_styles_keep_accent_colours_without_gradients(self):
        kira = theme.character_style(theme.CHARACTER_THEMES["kira"])
        self.assertIn("#9C7BFF", kira)
        self.assertIn("#35D9F2", kira)
        self.assertNotIn("qlineargradient", kira.lower())
