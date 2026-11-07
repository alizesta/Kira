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
