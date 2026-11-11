import tempfile
import unittest
from pathlib import Path
from unittest import mock

from kira import persona_memory as pm
from kira.personality import build_system_prompt


class PersonaMemoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        p = mock.patch.object(pm, "DATA_DIR", Path(self.tmp.name))
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(self.tmp.cleanup)

    def test_voice_samples_learn_and_filter(self):
        pm.observe("assistant", "[smug] خب معلومه که خوشگلم، تو چی فکر می‌کردی؟")
        pm.observe("assistant", "As an AI language model I cannot do that today")
        pm.observe("assistant", "see https://example.com for the long thing here")
        block = pm.build_block()
        self.assertIn("خوشگلم", block)
        self.assertNotIn("[smug]", block)
        self.assertNotIn("language model", block)
        self.assertNotIn("example.com", block)

    def test_facts_extracted_and_deduped(self):
        pm.observe("user", "اسم من رضاست. دوست دارم موسیقی راک")
        pm.observe("user", "my name is Ali")
        pm.observe("user", "یادت باشه فردا امتحان دارم")
        facts = pm.facts()
        self.assertEqual(sum(f.startswith("His name") for f in facts), 1)      # newest name replaces the old
        self.assertTrue(any("Ali" in f for f in facts))
        self.assertTrue(any("امتحان" in f for f in facts))
        self.assertIn("What she knows about him", pm.build_block())

    def test_long_term_memory_is_separate_for_each_character_and_keeps_kira_legacy_file(self):
        with pm.character_scope("kira"):
            pm.observe("user", "my name is KiraUser")
            pm.observe("assistant", "این هم یک جواب خودمانی مخصوص کیراست، همین‌قدر ساده و مستقیم.")
            self.assertTrue((Path(self.tmp.name) / pm.FILE_NAME).exists())
        with pm.character_scope("ren"):
            pm.observe("user", "my name is RenUser")
            block = pm.build_block()
            self.assertIn("RenUser", block)
            self.assertIn("Ren's own memory", block)
            self.assertNotIn("KiraUser", block)
            self.assertTrue((Path(self.tmp.name) / "kira_persona_memory_ren.json").exists())
        with pm.character_scope("mika"):
            pm.observe("user", "my name is MikaUser")
            block = pm.build_block()
            self.assertIn("MikaUser", block)
            self.assertNotIn("RenUser", block)
            self.assertNotIn("KiraUser", block)
            self.assertTrue((Path(self.tmp.name) / "kira_persona_memory_mika.json").exists())
        with pm.character_scope("kira"):
            block = pm.build_block()
            self.assertIn("KiraUser", block)
            self.assertNotIn("RenUser", block)
            self.assertNotIn("MikaUser", block)

    def test_evidence_memory_is_written_only_for_kira(self):
        with mock.patch.object(pm._evidence, "record_user_message") as record:
            with pm.character_scope("ren"):
                pm.observe("user", "my name is Ren")
            record.assert_not_called()
            with pm.character_scope("kira"):
                pm.observe("user", "my name is Kira")
            record.assert_called_once()

    def test_last_reply_voice_and_joke_memory_do_not_cross_characters(self):
        with pm.character_scope("kira"):
            pm.observe("assistant", "این یک جمله‌ی مخصوص کیراست که برای نمونه‌ی لحن ذخیره می‌شود.")
        with pm.character_scope("ren"):
            pm.observe("user", "😂")
            self.assertFalse(any(m["kind"] == "joke" for m in pm._load()["moments"]))

    def test_questions_are_not_facts(self):
        pm.observe("user", "من چی دوست دارم؟")
        self.assertEqual(pm.facts(), [])

    def test_digest_and_prompt_integration(self):
        older = [{"role": "user", "content": "درباره‌ی سفر به شیراز حرف زدیم"}, {"role": "assistant", "content": "اوهوم"}]
        block = pm.build_block(older)
        self.assertIn("شیراز", block)
        prompt = build_system_prompt({"assistant_name": "Kira"}, "FORMAT", block)
        self.assertLess(prompt.index("Kira's own memory"), prompt.index("FORMAT"))
        self.assertIn("You are Kira", prompt)

    def test_empty_memory_adds_nothing_and_forget(self):
        self.assertEqual(pm.build_block(), "")
        pm.observe("user", "my name is Sara")
        pm.observe("assistant", "باشه عزیزم، یادم می‌مونه که کی هستی")
        pm.forget_conversation()
        self.assertNotIn("عزیزم", pm.build_block())
        self.assertTrue(pm.facts())
        pm.forget_facts()
        self.assertEqual(pm.facts(), [])


if __name__ == "__main__":
    unittest.main()
