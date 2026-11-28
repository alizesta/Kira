from pathlib import Path
import tempfile
import unittest

from kira.personas import CHARACTERS, chat_background_file
from kira.theme import character_style


class MikaChatBackgroundTests(unittest.TestCase):
    def test_only_profiles_with_an_existing_configured_image_resolve_it(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            image = root / CHARACTERS["mika"]["chat_background"]
            image.parent.mkdir(parents=True)
            image.write_bytes(b"test image")
            self.assertEqual(chat_background_file(CHARACTERS["mika"], root), image.resolve())
            self.assertIsNone(chat_background_file(CHARACTERS["kira"], root))   # file not created yet
            kira_image = root / CHARACTERS["kira"]["chat_background"]
            kira_image.write_bytes(b"test image")
            self.assertEqual(chat_background_file(CHARACTERS["kira"], root), kira_image.resolve())
            self.assertIsNone(chat_background_file(CHARACTERS["ren"], root))

    def test_profile_portrait_resolver_uses_the_character_image_and_rejects_path_escape(self):
        from kira.personas import portrait_file

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            portrait = root / CHARACTERS["ren"]["image"]
            portrait.parent.mkdir(parents=True)
            portrait.write_bytes(b"portrait")
            self.assertEqual(portrait_file(CHARACTERS["ren"], root), portrait.resolve())
            unsafe = {**CHARACTERS["ren"], "image": "../../outside.jpg"}
            self.assertIsNone(portrait_file(unsafe, root))

    def test_background_paths_cannot_escape_the_asset_root(self):
        with tempfile.TemporaryDirectory() as temp:
            profile = {**CHARACTERS["mika"], "chat_background": "../../outside.jpg"}
            self.assertIsNone(chat_background_file(profile, temp))

    def test_theme_applies_background_only_when_a_path_is_supplied(self):
        palette = {"deep": "#171329", "main": "#D86CB8", "second": "#50D9F0"}
        path = Path("assets/characters/mika_chat_background.jpg")
        css = character_style(palette, background_image=path)
        self.assertIn('border-image: url("assets/characters/mika_chat_background.jpg") 0 0 0 0 stretch stretch;', css)
        self.assertNotIn("border-image:", character_style(palette))


if __name__ == "__main__":
    unittest.main()
