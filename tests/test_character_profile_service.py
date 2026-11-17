"""Qt-free tests for CharacterProfileService mutations."""
import unittest

from kira.services.character_service import CharacterProfileService


class CharacterProfileServiceTests(unittest.TestCase):
    def setUp(self):
        self.service = CharacterProfileService()
        self.settings = {}

    def test_create_profile_initializes_character_scoped_settings(self):
        profile = self.service.create_profile(self.settings, "  Ren Custom  ", "analyst", "prompt")
        cid = profile["id"]
        self.assertTrue(cid.startswith("custom_"))
        self.assertEqual(profile["name"], "Ren Custom")
        self.assertEqual(self.settings["active_character_id"], cid)
        self.assertIn(cid, self.service.all_profiles(self.settings))
        self.assertEqual(self.settings["character_voice"][cid], {})
        self.assertEqual(self.settings["character_notes"][cid], "")
        self.assertEqual(self.settings["character_resources"][cid], {})

    def test_create_rejects_blank_name(self):
        with self.assertRaises(ValueError):
            self.service.create_profile(self.settings, " ")

    def test_update_profile_preserves_unknown_fields_and_validates_name(self):
        profile = self.service.create_profile(self.settings, "Custom")
        cid = profile["id"]
        self.settings["characters"][0]["custom_extension"] = {"x": 1}
        updated = self.service.update_profile(
            self.settings, cid, name="Updated", description="desc", prompt="new prompt"
        )
        self.assertEqual(updated["name"], "Updated")
        self.assertEqual(updated["custom_extension"], {"x": 1})
        with self.assertRaises(ValueError):
            self.service.update_profile(self.settings, cid, name=" ", description="", prompt="")

    def test_builtin_profiles_cannot_be_edited(self):
        with self.assertRaises(ValueError):
            self.service.update_profile(
                self.settings, "kira", name="Changed", description="", prompt=""
            )

    def test_delete_custom_profile_cleans_scoped_settings_and_resets_active(self):
        profile = self.service.create_profile(self.settings, "Custom")
        cid = profile["id"]
        self.settings["character_traits"] = {cid: {"focus": 0.8}}
        self.assertTrue(self.service.delete_profile(self.settings, cid))
        self.assertNotIn(cid, self.service.all_profiles(self.settings))
        self.assertEqual(self.settings["active_character_id"], "kira")
        for key in ("character_voice", "character_notes", "character_resources", "character_traits"):
            self.assertNotIn(cid, self.settings.get(key, {}))

    def test_delete_builtin_hides_it_but_default_kira_is_protected(self):
        self.assertTrue(self.service.delete_profile(self.settings, "ren"))
        self.assertNotIn("ren", self.service.all_profiles(self.settings))
        with self.assertRaises(ValueError):
            self.service.delete_profile(self.settings, "kira")

    def test_save_preferences_normalizes_voice_and_resource_values(self):
        profile = self.service.create_profile(self.settings, "Custom")
        cid = profile["id"]
        self.service.save_preferences(
            self.settings, cid,
            voice={"voice_rate": 140, "voice_volume": 1.5},
            resources={"skills": "one, two;one", "mcp": [" server "], "connectors": None},
            notes="  profile notes  ",
        )
        self.assertEqual(self.settings["character_voice"][cid], {"voice_rate": 140, "voice_volume": 1.0})
        self.assertEqual(self.settings["character_resources"][cid]["skills"], ["one", "two"])
        self.assertEqual(self.settings["character_resources"][cid]["mcp"], ["server"])
        self.assertEqual(self.settings["character_notes"][cid], "profile notes")

    def test_save_preferences_rejects_non_finite_voice_volume(self):
        profile = self.service.create_profile(self.settings, "Custom")
        with self.assertRaises(ValueError):
            self.service.save_preferences(
                self.settings, profile["id"], voice={"voice_volume": float("nan")},
                resources={}, notes="",
            )

    def test_save_personality_clamps_traits_and_saves_notes(self):
        profile = self.service.create_profile(self.settings, "Custom")
        result = self.service.save_personality(
            self.settings, profile["id"], traits={"focus": 1.5, "energy": -1, "bad": "x"},
            notes="notes",
        )
        self.assertEqual(result, {"focus": 1.0, "energy": 0.0})
        self.assertEqual(self.settings["character_traits"][profile["id"]], result)
        self.assertEqual(self.settings["character_notes"][profile["id"]], "notes")


if __name__ == "__main__":
    unittest.main()
