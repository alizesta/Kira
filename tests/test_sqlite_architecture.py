"""Architecture regression tests for independent SQLite persistence services."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from kira.chat.sqlite_connection import SqliteConnectionManager
from kira.chat.sqlite_pending_queue import SqlitePendingMessageQueue
from kira.chat.sqlite_recovery import SqliteRecoveryManager
from kira.chat.sqlite_snapshot import SqliteSnapshotManager
from kira.chat.sqlite_repository import PersistenceError, SqliteChatRepository


class SqlitePersistenceBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.database = self.root / "chat.sqlite3"
        self.connections = SqliteConnectionManager(lambda: self.database)

    def tearDown(self):
        self.temp.cleanup()

    def test_snapshot_manager_owns_online_backup_and_retention(self):
        self.connections.configure_database()
        with self.connections.unit_of_work() as connection:
            connection.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, content TEXT)")
            connection.execute("INSERT INTO messages(content) VALUES ('durable')")
        snapshots = SqliteSnapshotManager(
            lambda: self.database, self.connections, db_name="chat.sqlite3", keep=1,
        )

        first = snapshots.create("cleared")
        second = snapshots.create("cleared")

        self.assertTrue((second / "chat.sqlite3").is_file())
        self.assertEqual(len(snapshots.list("cleared")), 1)
        connection = self.connections.connect_readonly(second / "chat.sqlite3")
        try:
            self.assertEqual(
                connection.execute("SELECT content FROM messages").fetchone()[0],
                "durable",
            )
        finally:
            connection.close()
        self.assertFalse(first.exists())

    def test_recovery_health_check_uses_ports_not_repository_internals(self):
        self.connections.configure_database()
        with self.connections.unit_of_work() as connection:
            connection.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, content TEXT)")
        recovery = SqliteRecoveryManager(
            db_path_provider=lambda: self.database,
            connection_manager=self.connections,
            read_rows=lambda _path: [],
            read_conversations=lambda _path: [],
            merge_rows=lambda *rows: [],
            write_recovery_state=lambda _rows, _conversations: None,
            db_name="chat.sqlite3",
            persistence_error=RuntimeError,
        )

        self.assertTrue(recovery.healthy(self.database))
        damaged = self.root / "damaged.sqlite3"
        damaged.write_bytes(b"not sqlite")
        self.assertFalse(recovery.healthy(damaged))
        self.assertEqual(recovery.backup_dirs(), [])

    def test_recovery_rewrite_rolls_back_messages_when_metadata_conflicts(self):
        repository = SqliteChatRepository(db_path=self.database)
        self.assertEqual(repository.init_db(), [])
        repository.create_conversation("kira", conversation_id="existing-conversation")
        self.assertTrue(repository.add_message(
            "user", "keep-this-message", character_id="kira",
            conversation_id="existing-conversation",
        ))

        recovered_rows = [(
            None, "user", "must-rollback", "", "kira",
            "new-conversation", "{}", "complete",
        )]
        conflicting_metadata = [{
            "id": "existing-conversation",
            "character_id": "another-character",
            "title": "conflict",
            "metadata": {},
            "status": "active",
            "created_at": "2026-01-01 00:00:00",
            "updated_at": "2026-01-01 00:00:00",
        }]

        with self.assertRaises(PersistenceError):
            repository._write_recovery_state(recovered_rows, conflicting_metadata)

        self.assertEqual(
            repository.recent_messages(10, character_id="kira"),
            [{"role": "user", "content": "keep-this-message"}],
        )
        self.assertIsNone(repository.get_conversation("new-conversation"))

    def test_pending_queue_replays_receipts_without_repository_dependency(self):
        self.connections.configure_database()
        with self.connections.unit_of_work() as connection:
            connection.execute(
                "CREATE TABLE persistence_receipts (token TEXT PRIMARY KEY NOT NULL)"
            )
            connection.execute(
                "CREATE TABLE conversations (id TEXT PRIMARY KEY, character_id TEXT NOT NULL)"
            )
            connection.execute(
                "CREATE TABLE messages (id INTEGER PRIMARY KEY, role TEXT, content TEXT, "
                "character_id TEXT, conversation_id TEXT, metadata TEXT, status TEXT)"
            )
        pending = []
        errors = []

        def migrate(connection):
            connection.execute(
                "CREATE TABLE IF NOT EXISTS persistence_receipts (token TEXT PRIMARY KEY NOT NULL)"
            )

        def ensure_conversation(connection, conversation_id, character_id):
            connection.execute(
                "INSERT OR IGNORE INTO conversations(id, character_id) VALUES (?, ?)",
                (conversation_id, character_id),
            )

        queue = SqlitePendingMessageQueue(
            db_path_provider=lambda: self.database,
            pending_getter=lambda: pending,
            pending_clearer=pending.clear,
            unit_of_work=self.connections.unit_of_work,
            migrate_schema=migrate,
            ensure_conversation_row=ensure_conversation,
            set_error=errors.append,
            note_error=lambda exc: errors.append(str(exc)),
            max_pending=10,
            persistence_error=RuntimeError,
        )
        self.assertFalse(hasattr(queue, "_repository"))
        row = ("user", "queued", "kira", "conversation", "{}", "complete", "stable-token")

        self.assertTrue(queue.enqueue_locked(row))
        queue.flush_locked()
        queue.flush_locked()

        with self.connections.unit_of_work() as connection:
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM messages").fetchone()[0], 1
            )
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM persistence_receipts").fetchone()[0], 1
            )
        self.assertEqual(pending, [])
        self.assertFalse(queue.spool_path().exists())


if __name__ == "__main__":
    unittest.main()
