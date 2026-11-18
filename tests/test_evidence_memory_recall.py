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


if __name__ == "__main__":
    unittest.main()
