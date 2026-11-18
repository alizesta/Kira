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

    def test_non_kira_memory_never_digests_shared_legacy_chat_history(self):
        shared = [{"role": "user", "content": "A private topic from Kira's old conversation"}]
        with pm.character_scope("ren"):
            block = pm.build_block(shared)
            self.assertNotIn("private topic", block)
        with pm.character_scope("kira"):
            block = pm.build_block(shared)
            self.assertIn("private topic", block)

    def test_character_scope_restores_previous_context(self):
        self.assertEqual(pm.current_character_id(), "kira")
        with pm.character_scope("ren"):
            self.assertEqual(pm.current_character_id(), "ren")
            with pm.character_scope("mika"):
                self.assertEqual(pm.current_character_id(), "mika")
            self.assertEqual(pm.current_character_id(), "ren")
        self.assertEqual(pm.current_character_id(), "kira")

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

    def test_non_kira_memory_recall_uses_current_topic_and_keeps_identity(self):
        with pm.character_scope("ren"):
            pm.add_fact("name", "نام کاربر علی است", now=1000)
            pm.add_fact("job", "شغل کاربر مهندس نرم‌افزار است", now=1001)
            pm.add_fact("note", "کاربر به موسیقی راک علاقه دارد", now=1002)

            block = pm.build_block(query="آلبوم‌های موسیقی راک", now=1003)

            self.assertIn("نام کاربر علی است", block)
            self.assertIn("موسیقی راک", block)
            self.assertNotIn("مهندس نرم‌افزار", block)

        with pm.character_scope("mika"):
            self.assertEqual(pm.build_block(query="آلبوم‌های موسیقی راک", now=1003), "")

    def test_moments_and_summaries_are_recalled_by_topic(self):
        with pm.character_scope("mika"):
            pm.add_moment("event", "فردا امتحان زبان دارم", now=1000)
            pm.add_moment("event", "هفته بعد سفر شیراز دارم", now=1001)
            data = pm._load()
            data["summaries"] = [
                {"kind": "summary", "text": "درباره امتحان زبان و منابعش صحبت کردیم", "ts": 1000, "id": "exam"},
                {"kind": "summary", "text": "درباره سفر شیراز و هتل صحبت کردیم", "ts": 1001, "id": "trip"},
            ]
            pm._save(data)

            block = pm.build_block(query="برای سفر شیراز چه برنامه‌ای گفته بودم؟", now=1002)

        self.assertIn("سفر شیراز", block)
        self.assertIn("هتل", block)
        self.assertNotIn("امتحان زبان", block)

    def test_kira_uses_persona_relevance_fallback_when_evidence_index_is_unavailable(self):
        with pm.character_scope("kira"):
            pm.add_fact("job", "شغل کاربر مهندس نرم‌افزار است", now=1000)
            with mock.patch.object(pm._evidence, "build_block", return_value=None):
                block = pm.build_block(query="درباره کار مهندس نرم‌افزار بگو", now=1001)

        self.assertIn("مهندس نرم‌افزار", block)

    def test_memory_budget_keeps_complete_lines(self):
        header = "Header"
        first = "Section:\n- complete fact"
        second = "- this second line must not be cut"
        budget = len(header) + 2 + len(first)
        block = pm._fit_memory_block(header, [first + "\n" + second], budget)

        self.assertEqual(block, header + "\n\n" + first)
        self.assertLessEqual(len(block), budget)

    def test_current_topic_is_passed_to_memory_for_every_character(self):
        source = (Path(__file__).resolve().parents[1] / "kira" / "ui" / "main_window_chat.py").read_text(encoding="utf-8")
        self.assertIn("query=evidence_memory.query_from_context(history),", source)
        self.assertNotIn("query=evidence_memory.query_from_context(history) if character_id == ", source)

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
