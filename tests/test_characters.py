import unittest

from kira import characters


class CharacterProfilesTests(unittest.TestCase):
    def test_kira_is_default_and_has_no_extra_prompt(self):
        self.assertEqual(characters.active_id({}), "kira")
        self.assertEqual(characters.prompt_for({}), "")

    def test_ren_and_mika_are_distinct_profiles(self):
        ren = characters.CHARACTERS["ren"]
        mika = characters.CHARACTERS["mika"]
        self.assertEqual(ren["gender"], "male")
        self.assertEqual(mika["gender"], "female")
        self.assertNotEqual(ren["prompt"], mika["prompt"])
        self.assertIn("same intelligence", ren["prompt"])
        self.assertIn("same intelligence", mika["prompt"])

    def test_unknown_profile_falls_back_to_kira(self):
        self.assertEqual(characters.active_id({"active_character_id": "missing"}), "kira")
        self.assertEqual(characters.display_name({"active_character_id": "missing"}), "Kira")

    def test_prompt_uses_selected_character(self):
        self.assertIn("You are Ren", characters.prompt_for({"active_character_id": "ren"}))
        self.assertIn("You are Mika", characters.prompt_for({"active_character_id": "mika"}))


if __name__ == "__main__":
    unittest.main()
