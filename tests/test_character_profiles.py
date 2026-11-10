from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from kira.characters import CharacterRegistry
from kira.characters.kira import PROFILE as KIRA_PROFILE
from kira.emotion.runtime import EmotionalRuntime
from kira.personality import build_system_prompt
from kira import mood, persona_memory


class CharacterRegistryTests(unittest.TestCase):
    def test_legacy_settings_seed_the_builtin_kira_profile(self):
        with tempfile.TemporaryDirectory() as folder:
            registry = CharacterRegistry(folder, legacy_name="Kira", legacy_notes="Use informal Persian.")
            profile = registry.get("kira")
            self.assertEqual(profile["name"], "Kira")
            self.assertEqual(profile["notes"], "Use informal Persian.")
            self.assertTrue(profile["built_in"])
            self.assertTrue((Path(folder) / "characters" / "profiles.json").is_file())

    def test_create_update_reload_activate_and_delete_custom_profile(self):
        with tempfile.TemporaryDirectory() as folder:
            registry = CharacterRegistry(folder)
            created = registry.create("Nova", "Calm and analytical.")
            custom_id = created["id"]
            registry.update(custom_id, description="A calm technical companion.", notes="Be concise.")
            registry.update(custom_id, traits={"playfulness": 0.2, "warmth": 0.9})
            reloaded = CharacterRegistry(folder)
            self.assertEqual(reloaded.active_id, custom_id)
            self.assertEqual(reloaded.active_profile["name"], "Nova")
            self.assertEqual(reloaded.active_profile["description"], "A calm technical companion.")
            self.assertEqual(reloaded.active_profile["traits"]["playfulness"], 0.2)
            self.assertTrue(reloaded.delete(custom_id))
            self.assertEqual(reloaded.active_id, "kira")
            with self.assertRaises(ValueError):
                reloaded.delete("kira")

    def test_kira_is_a_profile_and_custom_prompt_is_generic(self):
        self.assertEqual(KIRA_PROFILE["id"], "kira")
        self.assertTrue(KIRA_PROFILE["built_in"])
        custom = {
            "id": "nova", "name": "Nova", "description": "Quiet, careful and curious.",
            "notes": "Use short, measured sentences.", "system_prompt": "", "traits": {},
        }
        prompt = build_system_prompt({}, character_profile=custom)
        self.assertIn("Name: Nova", prompt)
        self.assertIn("Quiet, careful and curious.", prompt)
        self.assertIn("Use short, measured sentences.", prompt)
        self.assertNotIn("Kira's", prompt)
        kira_prompt = build_system_prompt({}, character_profile=KIRA_PROFILE)
        self.assertIn(KIRA_PROFILE["system_prompt"][:80], kira_prompt)
        self.assertIn("Kira", kira_prompt)


class PerCharacterStateTests(unittest.TestCase):
    def test_runtime_learning_uses_the_profile_baseline(self):
        custom_traits = dict(KIRA_PROFILE["traits"])
        custom_traits["teasing"] = 0.20
        with tempfile.TemporaryDirectory() as folder:
            runtime = EmotionalRuntime(path=Path(folder) / "state.json", base_traits=custom_traits)
            initial = runtime.snapshot(now=1000)
            self.assertAlmostEqual(initial["personality_traits"]["teasing"], 0.20)
            runtime.observe_feedback("liked_teasing", now=1000)
            runtime.observe_feedback("liked_teasing", now=1000 + 8 * 3600 + 1)
            learned = runtime.snapshot(now=1000 + 8 * 3600 + 1)
            self.assertGreater(learned["personality_traits"]["teasing"], 0.20)
            self.assertLess(learned["personality_traits"]["teasing"], 0.30)

    def test_emotion_and_state_files_are_isolated_by_character(self):
        custom_traits = dict(KIRA_PROFILE["traits"])
        custom_traits["playfulness"] = 0.25
        with tempfile.TemporaryDirectory() as folder:
            with mock.patch.object(mood, "DATA_DIR", Path(folder)):
                mood.set_active_character("kira", KIRA_PROFILE["traits"])
                mood.on_reply(["angry"], 90, now=1000)
                self.assertEqual(mood.current(now=1000)["emotion"], "angry")
                kira_runtime = Path(folder) / "kira_emotional_state.json"
                kira_legacy = Path(folder) / "kira_mood.json"
                self.assertTrue(kira_runtime.is_file())
                self.assertTrue(kira_legacy.is_file())

                mood.set_active_character("nova-test", custom_traits)
                self.assertNotEqual(mood.current(now=1000)["emotion"], "angry")
                mood.on_reply(["sad"], 90, now=2000)
                nova_runtime = Path(folder) / "characters" / "nova-test" / "emotional_state.json"
                nova_legacy = Path(folder) / "characters" / "nova-test" / "legacy_mood.json"
                self.assertTrue(nova_runtime.is_file())
                self.assertTrue(nova_legacy.is_file())
                self.assertEqual(mood.current(now=2000)["emotion"], "sad")

                mood.set_active_character("kira", KIRA_PROFILE["traits"])
                self.assertEqual(mood.current(now=1000)["emotion"], "angry")
                self.assertEqual(mood._emotional_runtime.base_traits["playfulness"], KIRA_PROFILE["traits"]["playfulness"])
            # Restore the runtime path after the patched data directory goes away.
            mood.set_active_character("kira", KIRA_PROFILE["traits"])


class PerCharacterVoiceMemoryTests(unittest.TestCase):
    def test_voice_samples_do_not_leak_between_character_profiles(self):
        with tempfile.TemporaryDirectory() as folder:
            with mock.patch.object(persona_memory, "DATA_DIR", Path(folder)):
                with mock.patch.object(persona_memory, "is_voice_sample", return_value=True):
                    persona_memory.set_active_character("kira")
                    persona_memory.observe("assistant", "Kira keeps her own distinct speaking style.")
                    shared_path = Path(folder) / "kira_persona_memory.json"
                    self.assertEqual(json.loads(shared_path.read_text(encoding="utf-8"))["voice"],
                                     ["Kira keeps her own distinct speaking style."])

                    persona_memory.set_active_character("nova-test")
                    persona_memory.observe("assistant", "Nova uses a calmer and more measured speaking style.")
                    self.assertEqual(persona_memory._load()["voice"],
                                     ["Nova uses a calmer and more measured speaking style."])
                    self.assertEqual(json.loads(shared_path.read_text(encoding="utf-8"))["voice"],
                                     ["Kira keeps her own distinct speaking style."])
                    self.assertTrue((Path(folder) / "characters" / "nova-test" / "voice_memory.json").is_file())

                    persona_memory.set_active_character("kira")
                    self.assertEqual(persona_memory._load()["voice"],
                                     ["Kira keeps her own distinct speaking style."])
            persona_memory.set_active_character("kira")


class CharacterTabWiringTests(unittest.TestCase):
    def test_navigation_contains_character_first_sections(self):
        source = (Path(__file__).resolve().parents[1] / "kira" / "main.py").read_text(encoding="utf-8")
        for required in (
            "self.build_characters_tab()", "self.build_personality_tab()", "self.build_help_tab()",
            '"tab_characters"', '"tab_personality"', '"tab_preferences"', '"tab_ai"', '"tab_help"',
            "character_profile=self.active_character()",
        ):
            self.assertIn(required, source)
        self.assertNotIn("self.build_assistant_tab()", source)
        self.assertIn("self.build_local_model_group()", source)


if __name__ == "__main__":
    unittest.main()
