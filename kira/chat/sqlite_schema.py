"""Versioned additive schema creation and migration for Chat SQLite storage."""
from __future__ import annotations

from typing import Any, Callable


class SqliteSchemaManager:
    """Own schema version checks, additive DDL and legacy conversation backfill.

    Connections and transactions are supplied by the persistence composition.
    Pre-migration snapshots are delegated through the snapshot-service callback;
    callbacks avoid importing the concrete repository.
    """

    def __init__(
        self,
        *,
        has_table: Callable[..., bool],
        columns: Callable[..., set[str]],
        ensure_conversation_row: Callable[..., Any],
        snapshot: Callable[..., Any],
        schema_version: int,
        persistence_error: type[Exception],
        character_id: Callable[[str | None], str],
        legacy_conversation_id: Callable[[str], str],
        now: Callable[[], str],
    ) -> None:
        self._has_table = has_table
        self._columns = columns
        self._ensure_conversation_row = ensure_conversation_row
        self._snapshot = snapshot
        self._schema_version = int(schema_version)
        self._persistence_error = persistence_error
        self._character_id = character_id
        self._legacy_conversation_id = legacy_conversation_id
        self._now = now

    def create_schema(self, con):
        """Run an additive, transactional, versioned migration. Never rebuilds or drops legacy tables."""
        current_version = int(con.execute("PRAGMA user_version").fetchone()[0])
        if current_version > self._schema_version:
            raise self._persistence_error(
                f"نسخه دیتابیس ({current_version}) از این نسخه برنامه جدیدتر است؛ برای جلوگیری از Downgrade، تغییر داده نشد."
            )
        if self._has_table(con, "persistence_schema"):
            recorded_versions = [
                int(row[0]) for row in con.execute("SELECT version FROM persistence_schema")
            ]
            if recorded_versions and max(recorded_versions) > self._schema_version:
                raise self._persistence_error(
                    "نسخه ثبت‌شده Schema از این نسخه برنامه جدیدتر است؛ دیتابیس بدون تغییر باقی ماند."
                )
        con.execute(
            "CREATE TABLE IF NOT EXISTS conversations ("
            "id TEXT PRIMARY KEY, character_id TEXT NOT NULL, title TEXT NOT NULL DEFAULT '', "
            "metadata TEXT NOT NULL DEFAULT '{}', status TEXT NOT NULL DEFAULT 'active', "
            "created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
        )
        if not self._has_table(con, "messages"):
            con.execute(
                "CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT, role TEXT NOT NULL, content TEXT NOT NULL, "
                "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, character_id TEXT NOT NULL DEFAULT 'kira', "
                "conversation_id TEXT, metadata TEXT NOT NULL DEFAULT '{}', status TEXT NOT NULL DEFAULT 'complete')"
            )
        cols = self._columns(con, "messages")
        additions = (
            ("character_id", "TEXT NOT NULL DEFAULT 'kira'"),
            ("conversation_id", "TEXT"),
            ("metadata", "TEXT NOT NULL DEFAULT '{}'"),
            ("status", "TEXT NOT NULL DEFAULT 'complete'"),
        )
        for name, definition in additions:
            if name not in cols:
                con.execute(f"ALTER TABLE messages ADD COLUMN {name} {definition}")
        cols = self._columns(con, "messages")
        if "created_at" not in cols:
            con.execute("ALTER TABLE messages ADD COLUMN created_at TIMESTAMP")
        con.execute("CREATE INDEX IF NOT EXISTS messages_character_order ON messages(character_id, id)")
        con.execute("CREATE INDEX IF NOT EXISTS messages_conversation_order ON messages(conversation_id, id)")
        con.execute("CREATE INDEX IF NOT EXISTS messages_timestamp_order ON messages(created_at, id)")
        con.execute("CREATE INDEX IF NOT EXISTS conversations_character_updated ON conversations(character_id, updated_at)")
        chars = [row[0] for row in con.execute(
            "SELECT DISTINCT COALESCE(NULLIF(LOWER(character_id), ''), 'kira') FROM messages"
        )]
        for cid in chars:
            conv_id = self._legacy_conversation_id(cid)
            self._ensure_conversation_row(con, conv_id, cid)
            con.execute(
                "UPDATE messages SET character_id=? WHERE COALESCE(NULLIF(LOWER(character_id), ''), 'kira')=? "
                "AND (character_id IS NULL OR TRIM(character_id)='' OR LOWER(character_id)<>?)",
                (cid, cid, cid),
            )
            con.execute(
                "UPDATE messages SET conversation_id=? WHERE conversation_id IS NULL "
                "AND COALESCE(NULLIF(LOWER(character_id), ''), 'kira')=?",
                (conv_id, cid),
            )
        con.execute(
            "CREATE TABLE IF NOT EXISTS persistence_schema (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL, description TEXT NOT NULL)"
        )
        con.execute(
            "INSERT OR IGNORE INTO persistence_schema(version, applied_at, description) VALUES (?, ?, ?)",
            (1, self._now(), "conversation ids, message metadata and stream status"),
        )
        if self._schema_version >= 2:
            con.execute(
                "CREATE TABLE IF NOT EXISTS persistence_receipts (token TEXT PRIMARY KEY NOT NULL)"
            )
            con.execute(
                "INSERT OR IGNORE INTO persistence_schema(version, applied_at, description) VALUES (?, ?, ?)",
                (2, self._now(), "idempotent durable pending-message replay receipts"),
            )
        con.execute(f"PRAGMA user_version = {self._schema_version}")

    def migrate(self, con):
        has_messages = self._has_table(con, "messages")
        has_conversations = self._has_table(con, "conversations")
        has_versions = self._has_table(con, "persistence_schema")
        current_version = int(con.execute("PRAGMA user_version").fetchone()[0])
        if current_version > self._schema_version:
            raise self._persistence_error(
                f"نسخه دیتابیس ({current_version}) از این نسخه برنامه جدیدتر است؛ برای جلوگیری از Downgrade، تغییر داده نشد."
            )
        if has_versions:
            recorded = [
                int(row[0]) for row in con.execute("SELECT version FROM persistence_schema")
            ]
            if recorded and max(recorded) > self._schema_version:
                raise self._persistence_error(
                    "نسخه ثبت‌شده Schema از این نسخه برنامه جدیدتر است؛ دیتابیس بدون تغییر باقی ماند."
                )

        needs_migration = (
            current_version < self._schema_version
            or not has_messages
            or not has_conversations
            or not has_versions
        )
        if has_messages:
            cols = self._columns(con, "messages")
            needs_migration = needs_migration or any(
                name not in cols
                for name in ("character_id", "conversation_id", "metadata", "status", "created_at")
            )
        # A completely fresh database has nothing to back up. Existing user
        # data gets an online backup before additive DDL/backfill. Once version
        # 1 is in place, ordinary message writes do not acquire a schema lock.
        has_existing_data = has_messages or has_conversations or has_versions
        if not needs_migration:
            return
        if has_existing_data:
            self._snapshot("pre-migration")
        if not con.in_transaction:
            con.execute("BEGIN IMMEDIATE")
        self.create_schema(con)

