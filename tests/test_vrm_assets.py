from __future__ import annotations

import unittest

from kira.characters.registry import _normalise_profile
from kira.vrm.metadata import inspect_vrm
from kira.vrm.paths import DEFAULT_KIRA_VRM, resolve_avatar_path


class BundledKiraAvatarTests(unittest.TestCase):
    def test_creator_provided_model_is_valid_vrm_1_humanoid_with_expressions(self):
        self.assertTrue(DEFAULT_KIRA_VRM.is_file(), f"Missing Kira model: {DEFAULT_KIRA_VRM}")
        info = inspect_vrm(DEFAULT_KIRA_VRM)
        self.assertEqual(info.vrm_version, "1.0")
        self.assertIn("hips", info.humanoid_bones)
        self.assertIn("head", info.humanoid_bones)
        self.assertTrue(info.expressions)

    def test_legacy_kira_profile_automatically_uses_the_default_model(self):
        profile = _normalise_profile({"id": "kira", "name": "Kira"})
        self.assertTrue(profile["avatar_default_enabled"])
        self.assertEqual(resolve_avatar_path(profile), str(DEFAULT_KIRA_VRM))

    def test_other_characters_do_not_inherit_kira_default(self):
        profile = _normalise_profile({"id": "ren", "name": "Ren"})
        self.assertFalse(profile["avatar_default_enabled"])
        self.assertEqual(resolve_avatar_path(profile), "")

    def test_custom_path_takes_precedence_and_default_can_be_disabled(self):
        custom = r"C:\Users\Example\Kira\custom.vrm"
        profile = _normalise_profile({
            "id": "kira", "name": "Kira", "avatar_model_path": custom,
        })
        self.assertEqual(resolve_avatar_path(profile), custom)
        cleared = _normalise_profile({
            "id": "kira", "name": "Kira", "avatar_default_enabled": False,
        })
        self.assertEqual(resolve_avatar_path(cleared), "")


if __name__ == "__main__":
    unittest.main()
