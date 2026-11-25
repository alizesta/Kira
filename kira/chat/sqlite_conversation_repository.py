"""Conversation-table repository separated from chat-message persistence."""
from __future__ import annotations

import copy
import json
import sqlite3
import uuid
from typing import Any, Callable


class SqliteConversationRepository:
    """Own conversation SQL operations while receiving connection and lifecycle ports."""

    def __init__(
        self,
        *,
        db: Callable,
        lock,
        migrate_schema: Callable,
        ensure_conversation_row: Callable,
        note_error: Callable,
        flush_pending_locked: Callable,
        snapshot: Callable,
        pending: list,
        active_conversations: dict,
        character_id: Callable,
        now: Callable,
        json_object: Callable,
        persistence_error: type[BaseException],
    ) -> None:
        self._db = db
        self._lock = lock
        self._migrate_schema = migrate_schema
        self._ensure_conversation_row = ensure_conversation_row
        self._note_error = note_error
        self._flush_pending_locked = flush_pending_locked
        self._snapshot = snapshot
        self._pending = pending
        self._active_conversations = active_conversations
        self._character_id = character_id
        self._now = now
        self._json_object = json_object
        self._persistence_error = persistence_error

    def _conversation_record(self, row):
        record = dict(row)
        record["metadata"] = self._json_object(record.get("metadata"))
        return record

    def create_conversation(self, character_id=None, title="", metadata=None, conversation_id=None) -> dict[str, Any]:
        cid = self._character_id(character_id)
        conv_id = str(conversation_id or uuid.uuid4())
        stamp = self._now()
        try:
            with self._lock, self._db() as con:
                self._migrate_schema(con)
                self._ensure_conversation_row(con, conv_id, cid, stamp)
                con.execute(
                    "UPDATE conversations SET title=?, metadata=?, updated_at=? WHERE id=? AND character_id=?",
                    (str(title or ""), json.dumps(self._json_object(metadata), ensure_ascii=False), stamp, conv_id, cid),
                )
                row = con.execute("SELECT * FROM conversations WHERE id=?", (conv_id,)).fetchone()
                if row is None or row["character_id"] != cid:
                    raise self._persistence_error("شناسه گفتگو متعلق به شخصیت دیگری است.")
                record = self._conversation_record(row)
                self._active_conversations[cid] = conv_id
                return record
        except self._persistence_error:
            raise
        except (sqlite3.Error, OSError) as exc:
            self._note_error(exc)
            raise self._persistence_error(str(exc)) from exc

    def get_or_create_conversation(self, character_id=None) -> dict[str, Any]:
        cid = self._character_id(character_id)
        with self._lock:
            try:
                with self._db() as con:
                    self._migrate_schema(con)
                    row = con.execute(
                        "SELECT * FROM conversations WHERE character_id=? AND status='active' ORDER BY updated_at DESC, rowid DESC LIMIT 1",
                        (cid,),
                    ).fetchone()
                if row is not None:
                    record = self._conversation_record(row)
                    self._active_conversations[cid] = str(record["id"])
                    return record
                return self.create_conversation(cid)
            except (sqlite3.Error, OSError) as exc:
                self._note_error(exc)
                raise self._persistence_error(str(exc)) from exc

    def get_conversation(self, conversation_id: str) -> dict[str, Any] | None:
        with self._db() as con:
            row = con.execute("SELECT * FROM conversations WHERE id=?", (str(conversation_id),)).fetchone()
            return self._conversation_record(row) if row else None

    def list_conversations(self, character_id=None) -> list[dict[str, Any]]:
        with self._db() as con:
            if character_id is None:
                rows = con.execute("SELECT * FROM conversations ORDER BY updated_at DESC, rowid DESC").fetchall()
            else:
                rows = con.execute(
                    "SELECT * FROM conversations WHERE character_id=? ORDER BY updated_at DESC, rowid DESC",
                    (self._character_id(character_id),),
                ).fetchall()
        return [self._conversation_record(row) for row in rows]

    def update_conversation(self, conversation_id: str, *, title=None, metadata=None, status=None) -> bool:
        changes, values = [], []
        if title is not None:
            changes.append("title=?"); values.append(str(title))
        if metadata is not None:
            changes.append("metadata=?"); values.append(json.dumps(self._json_object(metadata), ensure_ascii=False))
        if status is not None:
            if status not in ("active", "closed", "archived"):
                raise ValueError("status must be active, closed or archived; trashed is lifecycle-owned")
            changes.append("status=?"); values.append(status)
        if not changes:
            return False
        changes.append("updated_at=?"); values.append(self._now()); values.append(str(conversation_id))
        with self._lock, self._db() as con:
            row = con.execute("SELECT character_id FROM conversations WHERE id=?", (str(conversation_id),)).fetchone()
            cur = con.execute(f"UPDATE conversations SET {', '.join(changes)} WHERE id=?", values)
            if cur.rowcount and row is not None and status is not None:
                cid = self._character_id(row["character_id"])
                if status == "active":
                    self._active_conversations[cid] = str(conversation_id)
                elif self._active_conversations.get(cid) == str(conversation_id):
                    self._active_conversations.pop(cid, None)
            return cur.rowcount > 0

    def update_conversation_lifecycle(self, changes: list[dict[str, Any]]) -> bool:
        """Apply a validated lifecycle batch atomically without touching message rows."""
        if not changes:
            return False
        normalized = []
        seen = set()
        for item in changes:
            conv_id = str(item.get("id") or "").strip()
            status = str(item.get("status") or "")
            metadata = self._json_object(item.get("metadata"))
            previous = str(item.get("previous_status") or "")
            if not conv_id or conv_id in seen:
                raise ValueError("lifecycle batch requires unique non-empty conversation IDs")
            if status not in ("active", "archived", "trashed"):
                raise ValueError("invalid lifecycle target status")
            seen.add(conv_id)
            normalized.append((conv_id, status, json.dumps(metadata, ensure_ascii=False), previous))
        with self._lock:
            rows = {}
            with self._db() as con:
                self._migrate_schema(con)
                if not con.in_transaction:
                    con.execute("BEGIN IMMEDIATE")
                for conv_id, _, _, previous in normalized:
                    row = con.execute(
                        "SELECT character_id, status FROM conversations WHERE id=?", (conv_id,)
                    ).fetchone()
                    if row is None:
                        raise self._persistence_error(f"conversation not found: {conv_id}")
                    if str(row["status"] or "active") != previous:
                        raise self._persistence_error(f"conversation state changed concurrently: {conv_id}")
                    rows[conv_id] = str(row["character_id"] or "")
                stamp = self._now()
                for conv_id, status, metadata_json, _ in normalized:
                    con.execute(
                        "UPDATE conversations SET status=?, metadata=?, updated_at=? WHERE id=?",
                        (status, metadata_json, stamp, conv_id),
                    )
            # Update the in-memory active pointer only after SQLite committed.
            for conv_id, status, _, _ in normalized:
                character = self._character_id(rows[conv_id])
                if status == "active":
                    self._active_conversations[character] = conv_id
                elif self._active_conversations.get(character) == conv_id:
                    self._active_conversations.pop(character, None)
        return True

    def mutate_conversations(
        self,
        mutations: list[tuple[str, Callable[[dict[str, Any]], dict[str, Any]]]],
    ) -> dict[str, dict[str, Any]]:
        """Apply metadata/title mutations against current rows in one SQLite transaction.

        Each callback receives the latest conversation record while a write
        transaction is held. This prevents stale read-modify-write updates and
        makes multi-conversation organization operations all-or-nothing.
        """
        if not mutations:
            return {}

        normalized = []
        seen = set()
        for item in mutations:
            try:
                conversation_id, mutator = item
            except (TypeError, ValueError) as exc:
                raise TypeError("each mutation must be a (conversation_id, callback) pair") from exc
            conv_id = str(conversation_id or "").strip()
            if not conv_id or conv_id in seen:
                raise ValueError("metadata batch requires unique non-empty conversation IDs")
            if not callable(mutator):
                raise TypeError("metadata mutation must be callable")
            seen.add(conv_id)
            normalized.append((conv_id, mutator))

        updated_records: dict[str, dict[str, Any]] = {}
        stamp = self._now()
        with self._lock:
            with self._db() as con:
                self._migrate_schema(con)
                if not con.in_transaction:
                    con.execute("BEGIN IMMEDIATE")

                pending_updates = []
                for conv_id, mutator in normalized:
                    row = con.execute(
                        "SELECT * FROM conversations WHERE id=?", (conv_id,)
                    ).fetchone()
                    if row is None:
                        raise self._persistence_error(f"conversation not found: {conv_id}")
                    current = self._conversation_record(row)
                    updated = mutator(copy.deepcopy(current))
                    if not isinstance(updated, dict):
                        raise TypeError("metadata mutation callback must return a conversation dictionary")
                    if str(updated.get("id") or "") != conv_id:
                        raise ValueError("metadata mutation cannot change conversation identity")

                    for protected_field in ("character_id", "status", "created_at", "updated_at"):
                        if (
                            protected_field in updated
                            and updated[protected_field] != current.get(protected_field)
                        ):
                            raise ValueError(
                                f"metadata mutation cannot change {protected_field}"
                            )

                    metadata = updated.get("metadata", current.get("metadata", {}))
                    if not isinstance(metadata, dict):
                        raise TypeError("conversation metadata mutation must return a dictionary")
                    try:
                        metadata_json = json.dumps(
                            metadata, ensure_ascii=False, allow_nan=False
                        )
                    except (TypeError, ValueError) as exc:
                        raise self._persistence_error(
                            f"conversation metadata is not JSON serializable: {conv_id}"
                        ) from exc
                    title = str(updated.get("title", current.get("title")) or "")
                    if title != str(current.get("title") or "") or metadata != current.get("metadata", {}):
                        pending_updates.append((conv_id, title, metadata_json))

                for conv_id, title, metadata_json in pending_updates:
                    con.execute(
                        "UPDATE conversations SET title=?, metadata=?, updated_at=? WHERE id=?",
                        (title, metadata_json, stamp, conv_id),
                    )

                for conv_id, _ in normalized:
                    row = con.execute(
                        "SELECT * FROM conversations WHERE id=?", (conv_id,)
                    ).fetchone()
                    updated_records[conv_id] = self._conversation_record(row)

        return updated_records


    def mutate_all_conversations(
        self,
        character_id: str | None,
        mutator: Callable[[dict[str, Any]], dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        """Mutate every selected conversation under one write transaction."""
        if not callable(mutator):
            raise TypeError("metadata mutation must be callable")

        updated_records: dict[str, dict[str, Any]] = {}
        stamp = self._now()
        with self._lock:
            with self._db() as con:
                self._migrate_schema(con)
                if not con.in_transaction:
                    con.execute("BEGIN IMMEDIATE")
                if character_id is None:
                    rows = con.execute(
                        "SELECT * FROM conversations ORDER BY rowid"
                    ).fetchall()
                else:
                    rows = con.execute(
                        "SELECT * FROM conversations WHERE character_id=? ORDER BY rowid",
                        (self._character_id(character_id),),
                    ).fetchall()

                pending_updates = []
                identifiers = []
                for row in rows:
                    current = self._conversation_record(row)
                    conv_id = str(current["id"])
                    updated = mutator(copy.deepcopy(current))
                    if not isinstance(updated, dict):
                        raise TypeError("metadata mutation callback must return a conversation dictionary")
                    if str(updated.get("id") or "") != conv_id:
                        raise ValueError("metadata mutation cannot change conversation identity")

                    for protected_field in ("character_id", "status", "created_at", "updated_at"):
                        if (
                            protected_field in updated
                            and updated[protected_field] != current.get(protected_field)
                        ):
                            raise ValueError(
                                f"metadata mutation cannot change {protected_field}"
                            )

                    metadata = updated.get("metadata", current.get("metadata", {}))
                    if not isinstance(metadata, dict):
                        raise TypeError("conversation metadata mutation must return a dictionary")
                    try:
                        metadata_json = json.dumps(
                            metadata, ensure_ascii=False, allow_nan=False
                        )
                    except (TypeError, ValueError) as exc:
                        raise self._persistence_error(
                            f"conversation metadata is not JSON serializable: {conv_id}"
                        ) from exc
                    title = str(updated.get("title", current.get("title")) or "")
                    if title != str(current.get("title") or "") or metadata != current.get("metadata", {}):
                        pending_updates.append((conv_id, title, metadata_json))
                    identifiers.append(conv_id)

                for conv_id, title, metadata_json in pending_updates:
                    con.execute(
                        "UPDATE conversations SET title=?, metadata=?, updated_at=? WHERE id=?",
                        (title, metadata_json, stamp, conv_id),
                    )

                for conv_id in identifiers:
                    row = con.execute(
                        "SELECT * FROM conversations WHERE id=?", (conv_id,)
                    ).fetchone()
                    updated_records[conv_id] = self._conversation_record(row)

        return updated_records

    def close_conversation(self, conversation_id: str) -> bool:
        return self.update_conversation(conversation_id, status="closed")

    def delete_conversation(self, conversation_id: str, *, expected_status: str | None = None) -> int:
        """Snapshot before deleting one conversation and its messages."""
        conv_id = str(conversation_id)
        with self._lock:
            try:
                self._flush_pending_locked()
                with self._db() as con:
                    self._migrate_schema(con)
                    if not con.in_transaction:
                        con.execute("BEGIN IMMEDIATE")
                    count = int(con.execute(
                        "SELECT COUNT(*) FROM messages WHERE conversation_id=?", (conv_id,)
                    ).fetchone()[0])
                    conversation = con.execute(
                        "SELECT status FROM conversations WHERE id=?", (conv_id,)
                    ).fetchone()
                    exists = conversation is not None
                    if expected_status is not None:
                        if conversation is None or str(conversation["status"] or "active") != expected_status:
                            raise self._persistence_error("conversation state changed before permanent deletion")

                    # Refuse deletion when another durable table declares a
                    # foreign-key dependency on this conversation or its messages.
                    dependencies = []
                    tables = con.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                    ).fetchall()
                    for table_row in tables:
                        table = str(table_row["name"])
                        if table in ("conversations", "messages"):
                            continue
                        quoted_table = '"' + table.replace('"', '""') + '"'
                        for fk in con.execute(f"PRAGMA foreign_key_list({quoted_table})").fetchall():
                            target_table = str(fk[2])
                            if target_table not in ("conversations", "messages"):
                                continue
                            child_column = '"' + str(fk[3]).replace('"', '""') + '"'
                            target_column = str(fk[4] or "id")
                            quoted_target_column = '"' + target_column.replace('"', '""') + '"'
                            if target_table == "conversations":
                                dependency_query = (
                                    f"SELECT 1 FROM {quoted_table} WHERE {child_column} IN "
                                    f"(SELECT {quoted_target_column} FROM conversations WHERE id=?) LIMIT 1"
                                )
                            else:
                                dependency_query = (
                                    f"SELECT 1 FROM {quoted_table} WHERE {child_column} IN "
                                    f"(SELECT {quoted_target_column} FROM messages WHERE conversation_id=?) LIMIT 1"
                                )
                            if con.execute(dependency_query, (conv_id,)).fetchone() is not None:
                                dependencies.append(table)
                                break
                    if dependencies:
                        names = ", ".join(sorted(set(dependencies)))
                        raise self._persistence_error(
                            f"conversation has dependent records in: {names}"
                        )
                    if count or exists:
                        # Keep the write transaction open across backup and delete,
                        # preventing another process from inserting rows between those steps.
                        self._snapshot("before-delete-conversation")
                    con.execute("DELETE FROM messages WHERE conversation_id=?", (conv_id,))
                    con.execute("DELETE FROM conversations WHERE id=?", (conv_id,))
                self._pending[:] = [row for row in self._pending if row[3] != conv_id]
                for cid, active_id in list(self._active_conversations.items()):
                    if active_id == conv_id:
                        self._active_conversations.pop(cid, None)
                return count
            except (sqlite3.Error, OSError, self._persistence_error) as exc:
                raise self._persistence_error(f"حذف گفتگو ناموفق بود؛ داده‌ها حفظ شدند. ({exc})") from exc

