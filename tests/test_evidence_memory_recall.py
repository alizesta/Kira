"""Topic-recall regressions for the evidence-backed memory index."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from kira import evidence_memory as em


class EvidenceMemoryRecallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.patches = [
            mock.patch.object(em, "DATA_DIR", Path(self.temp.name)),
            mock.patch.object(em, "_ready_path", None),
            mock.patch.object(em, "_enabled", True),
            mock.patch.object(em, "_settings", {}),
        ]
        for patcher in self.patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(self.temp.cleanup)

    def test_interest_recall_includes_only_topic_matching_likes_and_dislikes(self):
        self.assertTrue(em.add_manual("موسیقی راک", predicate="like"))
        self.assertTrue(em.add_manual("فوتبال", predicate="like"))
        self.assertTrue(em.add_manual("فیلم ترسناک", predicate="dislike"))

        line = em.interest_line(query="آلبوم موسیقی راک")

        self.assertIn("موسیقی راک", line)
        self.assertNotIn("فوتبال", line)
        self.assertNotIn("فیلم ترسناک", line)

    def test_smalltalk_or_tokenless_query_never_returns_all_interests(self):
        em.add_manual("موسیقی راک", predicate="like")
        em.add_manual("فوتبال", predicate="like")

        self.assertEqual(em.interest_line(query="مرسی"), "")
        self.assertEqual(em.interest_line(query="از و به"), "")

    def test_retrieval_failures_are_logged_and_do_not_escape(self):
        with mock.patch.object(em, "_db", side_effect=RuntimeError("synthetic failure")):
            with self.assertLogs("kira.evidence_memory", level="WARNING") as captured:
                self.assertEqual(em.retrieve("موضوع مشخص"), [])
                self.assertEqual(em.interest_line(query="موضوع مشخص"), "")

        self.assertTrue(any("Evidence-memory retrieval failed" in line for line in captured.output))
        self.assertTrue(any("Evidence-memory interest recall failed" in line for line in captured.output))

        with mock.patch.object(em, "rank_texts", side_effect=RuntimeError("ranking failed")):
            with self.assertLogs("kira.evidence_memory", level="WARNING") as ranking_logs:
                self.assertEqual(em.interest_line(query="موضوع مشخص"), "")
        self.assertTrue(any("Evidence-memory interest ranking failed" in line for line in ranking_logs.output))


    def test_manual_memory_write_propagates_storage_failure(self):
        with mock.patch.object(em, "_db", side_effect=RuntimeError("synthetic write failure")):
            with self.assertLogs("kira.evidence_memory", level="ERROR") as captured:
                with self.assertRaisesRegex(RuntimeError, "synthetic write failure"):
                    em.add_manual("manual fact")
        self.assertTrue(any("Could not store manually edited evidence memory" in line for line in captured.output))

    def test_persona_delete_propagates_storage_failure(self):
        with mock.patch.object(em, "_db", side_effect=RuntimeError("synthetic delete failure")):
            with self.assertLogs("kira.evidence_memory", level="ERROR") as captured:
                with self.assertRaisesRegex(RuntimeError, "synthetic delete failure"):
                    em.delete_by_persona_id("persona-1")
        self.assertTrue(any("Could not delete evidence" in line for line in captured.output))

    def test_persona_update_does_not_fallback_after_lookup_failure(self):
        with mock.patch.object(em, "_db", side_effect=RuntimeError("synthetic lookup failure")):
            with self.assertLogs("kira.evidence_memory", level="ERROR") as captured:
                with self.assertRaisesRegex(RuntimeError, "synthetic lookup failure"):
                    em.update_by_persona_id("old-id", "new-id", "updated memory")
        self.assertTrue(any("Could not inspect evidence" in line for line in captured.output))

    def test_forget_all_propagates_storage_failure(self):
        with mock.patch.object(em, "_db", side_effect=RuntimeError("synthetic clear failure")):
            with self.assertLogs("kira.evidence_memory", level="ERROR") as captured:
                with self.assertRaisesRegex(RuntimeError, "synthetic clear failure"):
                    em.forget_all()
        self.assertTrue(any("Could not clear evidence memory" in line for line in captured.output))

    def test_extra_item_delete_propagates_storage_failure(self):
        with mock.patch.object(em, "_db", side_effect=RuntimeError("synthetic delete failure")):
            with self.assertLogs("kira.evidence_memory", level="ERROR") as captured:
                with self.assertRaisesRegex(RuntimeError, "synthetic delete failure"):
                    em.delete_extra("ev:fact-1")
        self.assertTrue(any("Could not delete an extra" in line for line in captured.output))

    def test_extra_item_update_is_atomic_when_reinsert_fails(self):
        self.assertTrue(em.add_manual("original evidence fact"))
        item = em.list_extra_items()[0]
        with mock.patch.object(em, "_ingest", side_effect=RuntimeError("synthetic reinsert failure")):
            with self.assertLogs("kira.evidence_memory", level="ERROR"):
                with self.assertRaisesRegex(RuntimeError, "synthetic reinsert failure"):
                    em.update_extra(item["id"], "replacement evidence fact")
        remaining = em.list_extra_items()
        self.assertEqual([entry["id"] for entry in remaining], [item["id"]])


    def test_forget_all_does_not_clear_when_history_watermark_is_unavailable(self):
        with mock.patch.object(em, "_chat_max_id", side_effect=RuntimeError("history unavailable")), mock.patch.object(
            em, "_db"
        ) as database:
            with self.assertLogs("kira.evidence_memory", level="ERROR") as captured:
                with self.assertRaisesRegex(RuntimeError, "history unavailable"):
                    em.forget_all()

        database.assert_not_called()
        self.assertTrue(any("Could not clear evidence memory" in line for line in captured.output))


    def test_persona_evidence_update_rolls_back_if_replacement_fails(self):
        self.assertTrue(em.add_manual("original persona fact", persona_id="old-persona-id"))
        before = em.list_extra_items()
        self.assertEqual(len(before), 1)

        with mock.patch.object(em, "_ingest", side_effect=RuntimeError("synthetic replacement failure")):
            with self.assertLogs("kira.evidence_memory", level="ERROR"):
                with self.assertRaisesRegex(RuntimeError, "synthetic replacement failure"):
                    em.update_by_persona_id("old-persona-id", "new-persona-id", "replacement persona fact")

        after = em.list_extra_items()
        self.assertEqual([item["id"] for item in after], [item["id"] for item in before])
        self.assertEqual(after[0]["text"], before[0]["text"])


if __name__ == "__main__":
    unittest.main()
