"""Architecture regressions for evidence storage, embedding isolation and vector-index lifecycle."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from kira import evidence_memory as em


class EvidenceMemoryArchitectureTests(unittest.TestCase):
    def test_fact_mutations_are_owned_by_dedicated_repository(self):
        self.assertEqual(
            type(em._FACT_REPOSITORY).__module__,
            "kira.evidence_memory_repository",
        )
        self.assertTrue(em.add_manual("repository-owned evidence fact"))
        self.assertTrue(any(
            "repository-owned evidence fact" in item["text"]
            for item in em.list_extra_items()
        ))

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


    def test_legacy_sqlite_schema_migrates_without_losing_facts_or_evidence(self):
        import sqlite3
        from pathlib import Path

        database = Path(self.temp.name) / em.DB_NAME
        with sqlite3.connect(str(database)) as connection:
            connection.executescript("""
                CREATE TABLE facts (
                    id TEXT PRIMARY KEY, subject TEXT NOT NULL, predicate TEXT NOT NULL, value TEXT NOT NULL, text TEXT NOT NULL,
                    category TEXT NOT NULL, status TEXT NOT NULL, source_kind TEXT NOT NULL, valid_from REAL, valid_to REAL,
                    supersedes TEXT NOT NULL DEFAULT '[]', legacy INTEGER NOT NULL DEFAULT 0, persona_id TEXT,
                    created_at REAL NOT NULL, updated_at REAL NOT NULL
                );
                CREATE INDEX facts_sp ON facts(subject, predicate, status);
                CREATE INDEX facts_persona ON facts(persona_id);
                CREATE TABLE evidence (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, fact_id TEXT NOT NULL, message_id INTEGER, speaker TEXT NOT NULL,
                    quote TEXT NOT NULL, created_at REAL NOT NULL, UNIQUE(fact_id, quote)
                );
                CREATE TABLE vectors (
                    fact_id TEXT NOT NULL, model TEXT NOT NULL, dim INTEGER NOT NULL, blob BLOB NOT NULL,
                    PRIMARY KEY(fact_id, model)
                );
                CREATE TABLE quarantine (id INTEGER PRIMARY KEY AUTOINCREMENT, created_at REAL NOT NULL, reason TEXT NOT NULL, payload TEXT NOT NULL);
                CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                INSERT INTO facts VALUES (
                    'legacy-fact', 'user', 'note', 'progressive rock', 'Likes progressive rock music',
                    'permanent', 'active', 'manual', NULL, NULL, '[]', 0, NULL, 1000, 1000
                );
                INSERT INTO evidence(fact_id, message_id, speaker, quote, created_at)
                VALUES ('legacy-fact', NULL, 'user', 'progressive rock music', 1000);
                INSERT INTO vectors(fact_id, model, dim, blob) VALUES ('legacy-fact', 'ollama::old-model', 2, X'0000803F00000040');
                INSERT INTO meta(key, value) VALUES ('backfilled', '1');
            """)

        self.assertTrue(any("progressive rock" in item["text"] for item in em.retrieve("progressive rock music", now=1001)))
        with sqlite3.connect(str(database)) as connection:
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            fact_count = connection.execute("SELECT COUNT(*) FROM facts WHERE id='legacy-fact'").fetchone()[0]
            evidence_count = connection.execute("SELECT COUNT(*) FROM evidence WHERE fact_id='legacy-fact'").fetchone()[0]
            old_vector_count = connection.execute("SELECT COUNT(*) FROM vectors WHERE model='ollama::old-model'").fetchone()[0]
        self.assertIn("embedding_indexes", tables)
        self.assertEqual(fact_count, 1)
        self.assertEqual(evidence_count, 1)
        self.assertEqual(old_vector_count, 1)

    def test_query_dimension_change_invalidates_only_derived_index_and_rebuilds(self):
        self.assertTrue(em.add_manual("stable evidence fact"))
        item = em.list_extra_items()[0]
        cfg = em.build_embedding_config({"embedding_backend": "ollama", "embedding_model": "fixed-name"})
        index = em.EmbeddingIndex.from_config(cfg)
        em._STORAGE.save_vectors(em._db, index, [item["id"][3:]], [[0.1, 0.2]], now=1000)
        self.assertEqual(em.stats()["vectors"], 1)

        with mock.patch.object(em, "_settings", {
            "embedding_backend": "ollama", "embedding_model": "fixed-name"
        }), mock.patch.object(em, "_embed", return_value=[[0.1, 0.2, 0.3]]), mock.patch.object(
            em, "schedule_vector_backfill"
        ) as schedule:
            self.assertEqual(em._semantic("stable evidence fact", [item["id"][3:]], em._embedding_config()), {})
            schedule.assert_called_once()

        self.assertEqual(em.stats()["vectors"], 0)
        self.assertTrue(any("stable evidence fact" in value["text"] for value in em.list_extra_items()))


if __name__ == "__main__":
    unittest.main()
