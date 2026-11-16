import unittest

from kira.theme import character_theme


class CharacterThemeTests(unittest.TestCase):
    def test_user_selected_colour_overrides_builtin_character_palette(self):
        palette = character_theme("kira", {"theme_color": "#12ABEF"})
        self.assertEqual(palette["main"], "#12ABEF")
        self.assertEqual(palette["name"], "#12ABEF")

    def test_builtin_palette_is_preserved_without_override(self):
        self.assertEqual(character_theme("kira")["main"], "#9C7BFF")


if __name__ == "__main__":
    unittest.main()
