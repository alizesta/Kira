import unittest
from pathlib import Path

from kira import characters


class CharacterProfilesTests(unittest.TestCase):
    def test_kira_is_default_and_has_coding_specialty(self):
        self.assertEqual(characters.active_id({}), "kira")
        prompt = characters.prompt_for({})
        self.assertIn("coding and software-development specialist", prompt)
        self.assertIn("Ai1 Code", prompt)

    def test_ren_and_mika_are_distinct_profiles(self):
        ren = characters.CHARACTERS["ren"]
        mika = characters.CHARACTERS["mika"]
        self.assertEqual(ren["gender"], "male")
        self.assertEqual(mika["gender"], "female")
        self.assertNotEqual(ren["prompt"], mika["prompt"])
        self.assertIn("same intelligence", ren["prompt"])
        self.assertIn("same intelligence", mika["prompt"])
        self.assertIn("medical-information guide", mika["specialty_prompt"])
        self.assertIn("news and intelligence analysis", ren["specialty_prompt"])

    def test_only_kira_has_a_builtin_portrait_until_new_art_is_ready(self):
        root = Path(__file__).resolve().parents[1]
        self.assertEqual(characters.CHARACTERS["kira"]["image"], "assets/characters/kira.svg")
        self.assertTrue((root / characters.CHARACTERS["kira"]["image"]).is_file())
        self.assertEqual(characters.CHARACTERS["ren"]["image"], "")
        self.assertEqual(characters.CHARACTERS["mika"]["image"], "")

    def test_unknown_profile_falls_back_to_kira(self):
        self.assertEqual(characters.active_id({"active_character_id": "missing"}), "kira")
        self.assertEqual(characters.display_name({"active_character_id": "missing"}), "Kira")

    def test_prompt_uses_selected_character(self):
        self.assertIn("You are Ren", characters.prompt_for({"active_character_id": "ren"}))
        self.assertIn("You are Mika", characters.prompt_for({"active_character_id": "mika"}))
        self.assertIn("medical-information guide", characters.prompt_for({"active_character_id": "mika"}))
        self.assertIn("news and intelligence analysis", characters.prompt_for({"active_character_id": "ren"}))

    def test_custom_profiles_and_hidden_builtins(self):
        settings = {
            "active_character_id": "custom_1",
            "characters": [{"id": "custom_1", "name": "Nova", "name_fa": "نوا",
                            "description": "custom", "prompt": "You are Nova"}],
            "deleted_character_ids": ["ren"],
        }
        self.assertNotIn("ren", characters.all_profiles(settings))
        self.assertEqual(characters.display_name(settings), "Nova")
        self.assertIn("You are Nova", characters.prompt_for(settings))


if __name__ == "__main__":
    unittest.main()
