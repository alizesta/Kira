"""Regression tests for SQLite connection policy and Unit of Work semantics."""
from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from kira.chat.sqlite_connection import (
    SQLITE_BUSY_TIMEOUT_SECONDS, SQLITE_WAL_AUTOCHECKPOINT_PAGES,
    SqliteConnectionManager,
)


class SqliteConnectionManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "chat.sqlite3"
        self.manager = SqliteConnectionManager(lambda: self.path)

    def tearDown(self):
        self.temp.cleanup()

    def test_wal_and_connection_policy_are_applied(self):
        self.assertEqual(self.manager.configure_database(), "wal")
        with self.manager.unit_of_work() as connection:
            self.assertEqual(connection.execute("PRAGMA journal_mode").fetchone()[0], "wal")
            self.assertEqual(connection.execute("PRAGMA synchronous").fetchone()[0], 2)
            self.assertEqual(connection.execute("PRAGMA foreign_keys").fetchone()[0], 1)
            self.assertEqual(connection.execute("PRAGMA busy_timeout").fetchone()[0],
                             int(SQLITE_BUSY_TIMEOUT_SECONDS * 1000))
            self.assertEqual(connection.execute("PRAGMA wal_autocheckpoint").fetchone()[0],
                             SQLITE_WAL_AUTOCHECKPOINT_PAGES)

    def test_unit_of_work_commits_and_closes_connection(self):
        with self.manager.unit_of_work() as connection:
            connection.execute("CREATE TABLE sample(value TEXT)")
            connection.execute("INSERT INTO sample VALUES ('committed')")
        with self.assertRaises(sqlite3.ProgrammingError):
            connection.execute("SELECT 1")
        with self.manager.unit_of_work() as connection:
            self.assertEqual(connection.execute("SELECT value FROM sample").fetchone()[0], "committed")

    def test_unit_of_work_rolls_back_all_writes_on_exception(self):
        with self.manager.unit_of_work() as connection:
            connection.execute("CREATE TABLE sample(value TEXT)")
        with self.assertRaisesRegex(RuntimeError, "interrupted"):
            with self.manager.unit_of_work() as connection:
                connection.execute("INSERT INTO sample VALUES ('not committed')")
                raise RuntimeError("interrupted")
        with self.manager.unit_of_work() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM sample").fetchone()[0], 0)
            self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")

    def test_unit_of_work_cannot_be_reentered(self):
        unit = self.manager.unit_of_work()
        with unit:
            pass
        with self.assertRaises(RuntimeError):
            with unit:
                pass


if __name__ == "__main__":
    unittest.main()
