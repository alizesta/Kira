import unittest

from kira.ui import dash_theme


class MikaPinkChatPaletteTests(unittest.TestCase):
    def tearDown(self):
        dash_theme.set_character("kira")

    def test_mika_recolours_violet_accents_to_pink(self):
        dash_theme.set_character("mika")
        recoloured = dash_theme.tone("#a855f7")
        self.assertNotEqual(recoloured.lower(), "#a855f7")
        self.assertEqual(dash_theme.ticks_colour("#8b5cf6"), "#ff8acb")

    def test_mika_recolours_cyan_accents_into_a_second_pink(self):
        dash_theme.set_character("mika")
        recoloured = dash_theme.tone("#38bdf8")
        self.assertNotEqual(recoloured.lower(), "#38bdf8")
        self.assertNotEqual(recoloured.lower(), dash_theme.tone("#a855f7").lower())


if __name__ == "__main__":
    unittest.main()
