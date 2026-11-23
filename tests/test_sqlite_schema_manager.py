"""Regression coverage for the repository's extracted schema manager."""
from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from kira.chat.sqlite_repository import SCHEMA_VERSION, SqliteChatRepository
from kira.chat.sqlite_schema import SqliteSchemaManager


class SqliteSchemaManagerTests(unittest.TestCase):
    def test_repository_delegates_schema_migration_without_changing_database_contract(self):
        with tempfile.TemporaryDirectory(prefix="kira-schema-manager-") as directory:
            database = Path(directory) / "chat.sqlite3"
            repository = SqliteChatRepository(database)

            self.assertIsInstance(repository._schema_manager, SqliteSchemaManager)
            self.assertEqual(repository.init_db(), [])

            with sqlite3.connect(database) as connection:
                self.assertEqual(
                    connection.execute("PRAGMA user_version").fetchone()[0],
                    SCHEMA_VERSION,
                )
                tables = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                }
            self.assertIn("messages", tables)
            self.assertIn("conversations", tables)
            self.assertIn("persistence_schema", tables)

    def test_legacy_message_migration_remains_additive_and_preserves_rows(self):
        with tempfile.TemporaryDirectory(prefix="kira-schema-legacy-") as directory:
            database = Path(directory) / "chat.sqlite3"
            with sqlite3.connect(database) as connection:
                connection.execute(
                    "CREATE TABLE messages (id INTEGER PRIMARY KEY, role TEXT, content TEXT, created_at TEXT)"
                )
                connection.execute(
                    "INSERT INTO messages(id, role, content, created_at) VALUES (7, 'user', 'legacy', '2020-01-01')"
                )

            repository = SqliteChatRepository(database)
            self.assertEqual(repository.init_db(), [])
            rows = repository.get_messages(limit=10, character_id="kira")
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["id"], 7)
            self.assertEqual(rows[0]["content"], "legacy")


if __name__ == "__main__":
    unittest.main()
