"""Concurrency regressions for Evidence Memory's database and background lifecycle."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest import mock

from kira import evidence_memory


class EvidenceMemoryConcurrencyTests(unittest.TestCase):
    def test_concurrent_first_use_initializes_one_valid_database(self):
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(evidence_memory, "DATA_DIR", Path(directory)), mock.patch.object(
                evidence_memory, "_ready_path", None
            ):
                with ThreadPoolExecutor(max_workers=8) as pool:
                    list(pool.map(lambda _index: evidence_memory._ensure(), range(24)))

                database = Path(directory) / evidence_memory.DB_NAME
                self.assertTrue(database.is_file())
                with sqlite3.connect(str(database)) as connection:
                    result = connection.execute("PRAGMA quick_check").fetchone()
                    tables = {
                        row[0]
                        for row in connection.execute(
                            "SELECT name FROM sqlite_master WHERE type='table'"
                        )
                    }
                self.assertEqual(result[0], "ok")
                self.assertTrue({"facts", "evidence", "vectors", "meta", "quarantine"}.issubset(tables))

    def test_failed_vector_thread_start_releases_single_flight_flag(self):
        with (
            mock.patch.object(evidence_memory, "_vector_job_running", False),
            mock.patch.object(evidence_memory, "_embed_fail_until", 0.0),
            mock.patch.object(evidence_memory, "_embedding_config", return_value={"tag": "test"}),
            mock.patch.object(
                evidence_memory,
                "_start_background",
                side_effect=RuntimeError("thread start rejected"),
            ),
        ):
            evidence_memory.schedule_vector_backfill()
            self.assertFalse(evidence_memory._vector_job_running)


if __name__ == "__main__":
    unittest.main()
