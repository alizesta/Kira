"""Architecture regressions for evidence storage, embedding isolation and vector-index lifecycle."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from kira import evidence_memory as em


class EvidenceMemoryArchitectureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.patches = [
            mock.patch.object(em, "DATA_DIR", Path(self.temp.name)),
            mock.patch.object(em, "_ready_path", None),
            mock.patch.object(em, "_enabled", True),
            mock.patch.object(em, "_settings", {}),
            mock.patch.object(em, "_vector_job_running", False),
            mock.patch.object(em, "_embed_fail_until", 0.0),
            mock.patch.object(em, "_query_fail_until", 0.0),
        ]
        for patcher in self.patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(self.temp.cleanup)

    def test_model_and_provider_are_part_of_versioned_index_identity(self):
        first = em.build_embedding_config({"embedding_backend": "ollama", "embedding_model": "bge-m3"})
        changed_model = em.build_embedding_config({"embedding_backend": "ollama", "embedding_model": "nomic-embed-text"})
        changed_provider = em.build_embedding_config({
            "embedding_backend": "provider", "embedding_provider": "openai", "embedding_model": "text-embedding-3-small"
        })
        self.assertIn("index-v1", first["tag"])
        self.assertNotEqual(first["tag"], changed_model["tag"])
        self.assertNotEqual(first["tag"], changed_provider["tag"])

    def test_embedding_failure_preserves_fact_and_lexical_retrieval(self):
        self.assertTrue(em.add_manual("likes progressive rock music"))
        with mock.patch.object(em, "_settings", {
            "embedding_backend": "ollama", "embedding_model": "bge-m3"
        }), mock.patch.object(em, "_embed", return_value=None), mock.patch.object(
            em, "_start_background", side_effect=lambda function, *args: function(*args)
        ):
            em.schedule_vector_backfill()

        self.assertTrue(any("progressive rock music" in item["text"] for item in em.list_extra_items()))
        recalled = em.retrieve("progressive rock music")
        self.assertTrue(any("progressive rock music" in item["text"] for item in recalled))
        self.assertEqual(em.stats()["vectors"], 0)

    def test_backfill_drains_more_than_one_batch(self):
        for index in range(em.EMBED_BATCH + 3):
            self.assertTrue(em.add_manual(f"distinct durable fact number {index}"))
        with mock.patch.object(em, "_settings", {
            "embedding_backend": "ollama", "embedding_model": "test-embedding"
        }), mock.patch.object(
            em, "_embed", side_effect=lambda texts, query=False: [[1.0, 0.5] for _ in texts]
        ), mock.patch.object(
            em, "_start_background", side_effect=lambda function, *args: function(*args)
        ):
            em.schedule_vector_backfill()

        self.assertEqual(em.stats()["vectors"], em.EMBED_BATCH + 3)

    def test_edit_and_delete_remove_vectors_without_losing_other_facts(self):
        with mock.patch.object(em, "_settings", {
            "embedding_backend": "ollama", "embedding_model": "test-embedding"
        }), mock.patch.object(
            em, "_embed", side_effect=lambda texts, query=False: [[0.2, 0.8] for _ in texts]
        ), mock.patch.object(
            em, "_start_background", side_effect=lambda function, *args: function(*args)
        ):
            em.add_manual("first evidence fact")
            em.add_manual("second evidence fact")
            items = em.list_extra_items()
            first_id = items[0]["id"]
            self.assertGreaterEqual(em.stats()["vectors"], 2)
            self.assertTrue(em.update_extra(first_id, "edited evidence fact"))
            self.assertTrue(any(item["text"] == "edited evidence fact" for item in em.list_extra_items()))
            second = next(item for item in em.list_extra_items() if item["text"] == "second evidence fact")
            self.assertTrue(em.delete_extra(second["id"]))
            remaining = em.list_extra_items()
            self.assertEqual([item["text"] for item in remaining], ["edited evidence fact"])
            self.assertEqual(em.stats()["vectors"], 1)


if __name__ == "__main__":
    unittest.main()
