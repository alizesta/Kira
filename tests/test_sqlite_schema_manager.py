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
            self.assertIn("persistence_receipts", tables)
            with sqlite3.connect(database) as connection:
                self.assertEqual(
                    [row[0] for row in connection.execute(
                        "SELECT version FROM persistence_schema ORDER BY version"
                    )],
                    [1, 2],
                )

    def test_version_one_database_migrates_to_version_two_without_losing_messages(self):
        with tempfile.TemporaryDirectory(prefix="kira-schema-v1-") as directory:
            database = Path(directory) / "chat.sqlite3"
            with sqlite3.connect(database) as connection:
                connection.execute(
                    "CREATE TABLE conversations (id TEXT PRIMARY KEY, character_id TEXT NOT NULL, "
                    "title TEXT NOT NULL DEFAULT '', metadata TEXT NOT NULL DEFAULT '{}', "
                    "status TEXT NOT NULL DEFAULT 'active', created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
                )
                connection.execute(
                    "CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT, role TEXT NOT NULL, "
                    "content TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, "
                    "character_id TEXT NOT NULL DEFAULT 'kira', conversation_id TEXT, "
                    "metadata TEXT NOT NULL DEFAULT '{}', status TEXT NOT NULL DEFAULT 'complete')"
                )
                connection.execute(
                    "CREATE TABLE persistence_schema (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL, description TEXT NOT NULL)"
                )
                connection.execute(
                    "INSERT INTO persistence_schema VALUES (1, '2026-01-01', 'v1')"
                )
                connection.execute(
                    "INSERT INTO messages(role, content, character_id) VALUES ('user', 'v1 message', 'kira')"
                )
                connection.execute("PRAGMA user_version = 1")

            repository = SqliteChatRepository(database)
            self.assertEqual(repository.init_db(), [])
            self.assertEqual(repository.get_messages(limit=10, character_id="kira")[0]["content"], "v1 message")
            with sqlite3.connect(database) as connection:
                self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 2)
                self.assertEqual(
                    [row[0] for row in connection.execute(
                        "SELECT version FROM persistence_schema ORDER BY version"
                    )],
                    [1, 2],
                )
                self.assertIsNotNone(connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='persistence_receipts'"
                ).fetchone())

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
