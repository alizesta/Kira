"""Qt-free chat persistence and history.

The persistence boundary owns conversation/message lifecycle, SQLite transactions,
schema migration, ordering, metadata, stream completion and recovery. UI and chat
application code consume ChatPersistence and never need to know the DB schema.
"""
from __future__ import annotations

import contextlib
import copy
import json
import shutil
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Protocol, runtime_checkable

from ..config import DB_PATH

DB_NAME = "kira_memory.sqlite3"
DEFAULT_CHARACTER = "kira"
SCHEMA_VERSION = 1
SNAPSHOTS_KEEP = 5
MAX_PENDING_MESSAGES = 500


class PersistenceError(RuntimeError):
    """A persistence operation failed without silently discarding saved data."""


ChatStoreError = PersistenceError


@runtime_checkable
class ChatRepository(Protocol):
    """Replaceable repository contract; no database-specific types escape it."""

    @property
    def last_error(self) -> str | None: ...
    @last_error.setter
    def last_error(self, value: str | None) -> None: ...
    def init_db(self) -> list[str]: ...
    def create_conversation(self, character_id=None, title="", metadata=None,
                            conversation_id=None) -> dict[str, Any]: ...
    def get_or_create_conversation(self, character_id=None) -> dict[str, Any]: ...
    def get_conversation(self, conversation_id: str) -> dict[str, Any] | None: ...
    def list_conversations(self, character_id=None) -> list[dict[str, Any]]: ...
    def update_conversation(self, conversation_id: str, *, title=None, metadata=None, status=None) -> bool: ...
    def close_conversation(self, conversation_id: str) -> bool: ...
    def delete_conversation(self, conversation_id: str, *, expected_status: str | None = None) -> int: ...
    def update_conversation_lifecycle(self, changes: list[dict[str, Any]]) -> bool: ...
    def mutate_conversations(
        self, mutations: list[tuple[str, Callable[[dict[str, Any]], dict[str, Any]]]]
    ) -> dict[str, dict[str, Any]]: ...
    def mutate_all_conversations(
        self, character_id: str | None, mutator: Callable[[dict[str, Any]], dict[str, Any]]
    ) -> dict[str, dict[str, Any]]: ...
    def add_message(self, role: str, content: str, character_id: str | None = None, **options) -> bool: ...
    def update_stream_message(self, message_id: int, content: str, **options) -> bool: ...
    def conversation_context(self, limit: int = 12, max_chars: int = 12000,
                             character_id: str | None = None, conversation_id: str | None = None) -> list[dict[str, str]]: ...
    def recent_messages(self, limit: int = 12, character_id: str | None = None,
                        conversation_id: str | None = None) -> list[dict[str, str]]: ...
    def recent_message_records(self, limit: int = 2000, character_id: str | None = None) -> list[dict[str, Any]]: ...
    def get_messages(self, limit: int = 1000, character_id: str | None = None,
                     conversation_id: str | None = None, after_id: int = 0) -> list[dict[str, Any]]: ...
    def get_transfer_messages(self, conversation_id: str, character_id: str, after_created_at: str = "", after_id: int = 0, limit: int = 1000) -> list[dict[str, Any]]: ...
    def message_id_for(self, role: str, content: str, character_id: str | None = None) -> int | None: ...
    def rows_with_ids(self, limit: int = 3000, after_id: int = 0,
                      character_id: str | None = None) -> list[tuple[int, str, str, str]]: ...
    def max_message_id(self) -> int: ...
    def message_count(self, character_id: str | None = None, conversation_id: str | None = None) -> int: ...
    def pending_count(self) -> int: ...
    def list_snapshots(self, kind: str = "cleared") -> list[Path]: ...
    def clear_memory(self, character_id: str | None = None) -> None: ...
    def restore_last_cleared(self) -> int: ...
    def import_messages(self, source: str | Path) -> int: ...
    def import_transfer_records(self, conversations: list[dict[str, Any]], messages: list[dict[str, Any]]) -> dict[str, Any]: ...


def _character_id(value: str | None) -> str:
    return str(value or "").strip().lower() or DEFAULT_CHARACTER


def _legacy_conversation_id(character_id: str) -> str:
    # Stable across restarts and data-folder moves; legacy versions had one history per character.
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"kira:legacy-conversation:{_character_id(character_id)}"))


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except (TypeError, ValueError):
            return {}
    return {}


class SqliteChatRepository:
    """Thread-safe SQLite repository retaining compatibility with Kira's legacy DB.

    db_path may be a path or a zero-argument provider. The default path is
    resolved at operation time so existing deployments/tests can override it.
    """

    def __init__(self, db_path=None):
        self._db_path = db_path if callable(db_path) else (lambda: Path(db_path or DB_PATH))
        self._lock = threading.RLock()
        self._pending: list[tuple] = []
        self._active_conversations: dict[str, str] = {}
        self.last_error: str | None = None
        self.startup_notes: list[str] = []

    @property
    def db_path(self) -> Path:
        return Path(self._db_path())

    @contextlib.contextmanager
    def _db(self, path=None):
        con = sqlite3.connect(str(path or self.db_path), timeout=15)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys = ON")
        try:
            with con:
                yield con
        finally:
            con.close()

    @staticmethod
    def _has_table(con, name: str) -> bool:
        return con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None

    @staticmethod
    def _columns(con, table: str) -> set[str]:
        return {str(row[1]) for row in con.execute(f"PRAGMA table_info({table})")}

    def _healthy(self, path: Path) -> bool:
        path = Path(path)
        if not path.exists():
            return True
        try:
            con = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=5)
            try:
                row = con.execute("PRAGMA quick_check").fetchone()
                if not row or row[0] != "ok":
                    return False
                if self._has_table(con, "messages"):
                    con.execute("SELECT COUNT(*) FROM messages").fetchone()
                return True
            finally:
                con.close()
        except sqlite3.Error:
            return False

    def _snapshot(self, kind: str) -> Path:
        root = self.db_path.parent / "snapshots"
        root.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        target, n = root / f"{kind}-{stamp}", 1
        while target.exists():
            n += 1
            target = root / f"{kind}-{stamp}-{n}"
        target.mkdir()
        src = sqlite3.connect(str(self.db_path), timeout=15)
        try:
            dst = sqlite3.connect(str(target / DB_NAME))
            try:
                src.backup(dst)
            finally:
                dst.close()
        finally:
            src.close()
        old = sorted((p for p in root.iterdir() if p.is_dir() and p.name.startswith(kind + "-")))
        for folder in old[:-SNAPSHOTS_KEEP]:
            shutil.rmtree(folder, ignore_errors=True)
        return target

    def _read_rows_full(self, path) -> list[tuple]:
        """Read legacy/current DB rows, including metadata and stream state; salvage readable rows."""
        path = Path(path)
        if not path.is_file():
            return []
        try:
            con = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=5)
        except sqlite3.Error:
            return []
        rows = []
        try:
            if not self._has_table(con, "messages"):
                return []
            cols = self._columns(con, "messages")
            cid_expr = "COALESCE(character_id, 'kira')" if "character_id" in cols else "'kira'"
            conv_expr = "conversation_id" if "conversation_id" in cols else "NULL"
            meta_expr = "metadata" if "metadata" in cols else "'{}'"
            status_expr = "status" if "status" in cols else "'complete'"
            ts_expr = "COALESCE(created_at, '')" if "created_at" in cols else "''"
            cur = con.execute(
                f"SELECT id, role, content, {ts_expr}, {cid_expr}, {conv_expr}, {meta_expr}, {status_expr} "
                "FROM messages ORDER BY id"
            )
            while True:
                try:
                    batch = cur.fetchmany(200)
                except sqlite3.Error:
                    break
                if not batch:
                    break
                for row in batch:
                    role, body = row[1], row[2]
                    if role not in ("user", "assistant", "system") or not str(body or "").strip():
                        continue
                    cid = _character_id(row[4])
                    rows.append((int(row[0]), str(role), str(body), str(row[3] or ""), cid,
                                 str(row[5]) if row[5] else _legacy_conversation_id(cid),
                                 json.dumps(_json_object(row[6]), ensure_ascii=False), str(row[7] or "complete")))
        except sqlite3.Error:
            pass
        finally:
            con.close()
        return rows

    def _read_conversations(self, path) -> list[dict[str, Any]]:
        path = Path(path)
        if not path.is_file():
            return []
        try:
            con = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=5)
        except sqlite3.Error:
            return []
        try:
            if not self._has_table(con, "conversations"):
                return []
            cols = self._columns(con, "conversations")
            if not {"id", "character_id"} <= cols:
                return []
            title = "title" if "title" in cols else "''"
            metadata = "metadata" if "metadata" in cols else "'{}'"
            status = "status" if "status" in cols else "'active'"
            created = "created_at" if "created_at" in cols else "''"
            updated = "updated_at" if "updated_at" in cols else created
            rows = con.execute(
                f"SELECT id, character_id, {title}, {metadata}, {status}, {created}, {updated} FROM conversations"
            ).fetchall()
            return [{
                "id": str(row[0]), "character_id": _character_id(row[1]), "title": str(row[2] or ""),
                "metadata": _json_object(row[3]), "status": str(row[4] or "active"),
                "created_at": str(row[5] or _now()), "updated_at": str(row[6] or row[5] or _now()),
            } for row in rows]
        except sqlite3.Error:
            return []
        finally:
            con.close()

    def _restore_conversation_metadata(self, conversations):
        if not conversations:
            return
        with self._db() as con:
            self._migrate_schema(con)
            for row in conversations:
                existing = con.execute(
                    "SELECT character_id FROM conversations WHERE id=?", (row["id"],)
                ).fetchone()
                if existing is not None and _character_id(existing["character_id"]) != _character_id(row["character_id"]):
                    raise PersistenceError("شناسه گفتگو در فایل پشتیبان به شخصیت دیگری تعلق دارد.")
                con.execute(
                    "INSERT INTO conversations(id, character_id, title, metadata, status, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET "
                    "title=excluded.title, metadata=excluded.metadata, status=excluded.status, "
                    "created_at=excluded.created_at, updated_at=excluded.updated_at",
                    (row["id"], row["character_id"], row["title"],
                     json.dumps(_json_object(row.get("metadata")), ensure_ascii=False),
                     row["status"], row["created_at"], row["updated_at"]),
                )

    def read_rows(self, path) -> list[tuple[str, str, str]]:
        return [(row[1], row[2], row[3]) for row in self._read_rows_full(path)]

    def read_rows_full(self, path):
        return self._read_rows_full(path)

    @staticmethod
    def _message_fields(row):
        """Normalize durable, merged and legacy tuple shapes to one message record."""
        if len(row) >= 8:
            message_id, role, body, stamp, cid, conv_id, metadata, status = row[:8]
        else:
            message_id = None
            role, body = row[0], row[1]
            stamp = row[2] if len(row) > 2 else ""
            cid = row[3] if len(row) > 3 else None
            conv_id = row[4] if len(row) > 4 else None
            metadata = row[5] if len(row) > 5 else "{}"
            status = row[6] if len(row) > 6 else "complete"
        cid = _character_id(cid)
        conv_id = str(conv_id) if conv_id else _legacy_conversation_id(cid)
        return (
            int(message_id) if message_id is not None else None,
            str(role), str(body), str(stamp or ""), cid, conv_id,
            json.dumps(_json_object(metadata), ensure_ascii=False), str(status or "complete"),
        )

    @staticmethod
    def _message_key(row):
        normalized = SqliteChatRepository._message_fields(row)
        return normalized[1], normalized[2], normalized[3], normalized[4], normalized[5]

    @staticmethod
    def _merge(*sources):
        """Stable union preserving existing IDs when they do not collide."""
        seen_keys, used_ids, output = set(), set(), []
        for source_order, rows in enumerate(sources):
            for index, raw_row in enumerate(rows):
                message_id, role, body, stamp, cid, conv_id, metadata, status = (
                    SqliteChatRepository._message_fields(raw_row)
                )
                key = (role, body, stamp, cid, conv_id)
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                if message_id is not None and message_id in used_ids:
                    message_id = None
                if message_id is not None:
                    used_ids.add(message_id)
                output.append((
                    stamp, source_order, index, message_id, role, body, cid,
                    conv_id, metadata, status,
                ))
        output.sort(key=lambda item: (item[0], item[1], item[2]))
        next_id = max(used_ids, default=0) + 1
        merged = []
        for stamp, _, _, message_id, role, body, cid, conv_id, metadata, status in output:
            if message_id is None:
                message_id = next_id
                next_id += 1
            merged.append((message_id, role, body, stamp, cid, conv_id, metadata, status))
        return merged

    def _ensure_conversation_row(self, con, conversation_id: str, character_id: str, created_at=None):
        cid = _character_id(character_id)
        stamp = created_at or _now()
        con.execute(
            "INSERT OR IGNORE INTO conversations(id, character_id, title, metadata, status, created_at, updated_at) "
            "VALUES (?, ?, '', '{}', 'active', ?, ?)",
            (conversation_id, cid, stamp, stamp),
        )
        row = con.execute("SELECT character_id FROM conversations WHERE id=?", (str(conversation_id),)).fetchone()
        if row is None or _character_id(row["character_id"]) != cid:
            raise PersistenceError("شناسه گفتگو به شخصیت دیگری تعلق دارد.")

    def _create_schema(self, con):
        """Run an additive, transactional, versioned migration. Never rebuilds or drops legacy tables."""
        current_version = int(con.execute("PRAGMA user_version").fetchone()[0])
        if current_version > SCHEMA_VERSION:
            raise PersistenceError(
                f"نسخه دیتابیس ({current_version}) از این نسخه برنامه جدیدتر است؛ برای جلوگیری از Downgrade، تغییر داده نشد."
            )
        if self._has_table(con, "persistence_schema"):
            recorded_versions = [
                int(row[0]) for row in con.execute("SELECT version FROM persistence_schema")
            ]
            if recorded_versions and max(recorded_versions) > SCHEMA_VERSION:
                raise PersistenceError(
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
            conv_id = _legacy_conversation_id(cid)
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
            (SCHEMA_VERSION, _now(), "conversation ids, message metadata and stream status"),
        )
        con.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    def _migrate_schema(self, con):
        has_messages = self._has_table(con, "messages")
        has_conversations = self._has_table(con, "conversations")
        has_versions = self._has_table(con, "persistence_schema")
        current_version = int(con.execute("PRAGMA user_version").fetchone()[0])
        if current_version > SCHEMA_VERSION:
            raise PersistenceError(
                f"نسخه دیتابیس ({current_version}) از این نسخه برنامه جدیدتر است؛ برای جلوگیری از Downgrade، تغییر داده نشد."
            )
        if has_versions:
            recorded = [
                int(row[0]) for row in con.execute("SELECT version FROM persistence_schema")
            ]
            if recorded and max(recorded) > SCHEMA_VERSION:
                raise PersistenceError(
                    "نسخه ثبت‌شده Schema از این نسخه برنامه جدیدتر است؛ دیتابیس بدون تغییر باقی ماند."
                )

        needs_migration = (
            current_version < SCHEMA_VERSION
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
        self._create_schema(con)

    def _write_all(self, rows):
        """Transactional recovery rewrite that preserves non-conflicting message IDs."""
        with self._db() as con:
            self._migrate_schema(con)
            con.execute("DELETE FROM messages")
            for raw_row in rows:
                message_id, role, body, stamp, cid, conv_id, metadata, status = self._message_fields(raw_row)
                self._ensure_conversation_row(con, conv_id, cid, stamp or None)
                fields = (role, body, stamp or "", cid, conv_id, metadata or "{}", status or "complete")
                if message_id is None:
                    con.execute(
                        "INSERT INTO messages(role, content, created_at, character_id, conversation_id, metadata, status) "
                        "VALUES (?, ?, NULLIF(?, ''), ?, ?, ?, ?)",
                        fields,
                    )
                else:
                    con.execute(
                        "INSERT INTO messages(id, role, content, created_at, character_id, conversation_id, metadata, status) "
                        "VALUES (?, ?, ?, NULLIF(?, ''), ?, ?, ?, ?)",
                        (message_id, *fields),
                    )

    def _backup_dirs(self):
        root = self.db_path.parent / "backups"
        try:
            return sorted((p for p in root.iterdir() if p.is_dir()), reverse=True)
        except OSError:
            return []

    def _latest_backup_rows(self):
        for folder in self._backup_dirs():
            candidate = folder / DB_NAME
            if candidate.is_file() and self._healthy(candidate):
                return self._read_rows_full(candidate), candidate
        return [], None

    def _recover(self, reason: str) -> str:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        salvaged = self._read_rows_full(self.db_path)
        salvaged_conversations = self._read_conversations(self.db_path)
        quarantine = self.db_path.with_name(f"kira_memory.corrupt-{stamp}.sqlite3")
        suffix = 1
        while quarantine.exists():
            suffix += 1
            quarantine = quarantine.with_name(f"kira_memory.corrupt-{stamp}-{suffix}.sqlite3")
        try:
            self.db_path.replace(quarantine)
            for side_suffix in ("-journal", "-wal", "-shm"):
                side = Path(str(self.db_path) + side_suffix)
                if side.exists():
                    side.replace(Path(str(quarantine) + side_suffix))
        except OSError as exc:
            raise PersistenceError(f"فایل دیتابیس خراب جابه‌جا نشد: {exc}") from exc
        backup_rows, backup = self._latest_backup_rows()
        backup_conversations = self._read_conversations(backup) if backup else []
        merged = self._merge(backup_rows, salvaged)
        self._write_all(merged)
        self._restore_conversation_metadata([*backup_conversations, *salvaged_conversations])
        where = f" و از پشتیبان «{backup.parent.name}» کامل شد" if backup and backup_rows else ""
        return (f"دیتابیس گفتگو خراب بود ({reason}). فایل خراب پاک نشد و با نام «{quarantine.name}» کنار گذاشته شد؛ "
                f"{len(salvaged)} پیام از آن نجات یافت{where}. در مجموع {len(merged)} پیام بازیابی شد.")

    def _note_error(self, exc):
        self.last_error = f"{type(exc).__name__}: {exc}"

    def init_db(self) -> list[str]:
        notes: list[str] = []
        with self._lock:
            try:
                self.db_path.parent.mkdir(parents=True, exist_ok=True)
                if not self._healthy(self.db_path):
                    notes.append(self._recover("بررسی سلامت فایل ناموفق بود"))
                with self._db() as con:
                    self._migrate_schema(con)
                    active_rows = con.execute(
                        "SELECT id, character_id FROM conversations WHERE status='active' "
                        "ORDER BY updated_at DESC, rowid DESC"
                    ).fetchall()
                    self._active_conversations.clear()
                    for row in active_rows:
                        self._active_conversations.setdefault(_character_id(row["character_id"]), str(row["id"]))
                self.last_error = None
            except (sqlite3.Error, OSError, PersistenceError) as exc:
                self._note_error(exc)
                notes.append(f"دیتابیس گفتگو باز نشد ({exc}). گفتگو فعلاً فقط در حافظه نگه داشته می‌شود.")
        self.startup_notes[:] = notes
        return notes

    def _flush_pending_locked(self):
        if not self._pending:
            return
        with self._db() as con:
            self._migrate_schema(con)
            con.executemany(
                "INSERT INTO messages(role, content, character_id, conversation_id, metadata, status) VALUES (?, ?, ?, ?, ?, ?)",
                self._pending,
            )
            for row in self._pending:
                self._ensure_conversation_row(con, row[3], row[2])
        self._pending.clear()

    def flush_pending(self) -> int:
        """Persist every queued message before application shutdown."""
        with self._lock:
            pending_count = len(self._pending)
            if not pending_count:
                return 0
            try:
                self._flush_pending_locked()
            except (sqlite3.Error, OSError, PersistenceError) as exc:
                self._note_error(exc)
                raise PersistenceError(
                    f"Could not flush {pending_count} pending chat messages: {exc}"
                ) from exc
            self.last_error = None
            return pending_count

    @staticmethod
    def _conversation_record(row):
        record = dict(row)
        record["metadata"] = _json_object(record.get("metadata"))
        return record

    def create_conversation(self, character_id=None, title="", metadata=None, conversation_id=None) -> dict[str, Any]:
        cid = _character_id(character_id)
        conv_id = str(conversation_id or uuid.uuid4())
        stamp = _now()
        try:
            with self._lock, self._db() as con:
                self._migrate_schema(con)
                self._ensure_conversation_row(con, conv_id, cid, stamp)
                con.execute(
                    "UPDATE conversations SET title=?, metadata=?, updated_at=? WHERE id=? AND character_id=?",
                    (str(title or ""), json.dumps(_json_object(metadata), ensure_ascii=False), stamp, conv_id, cid),
                )
                row = con.execute("SELECT * FROM conversations WHERE id=?", (conv_id,)).fetchone()
                if row is None or row["character_id"] != cid:
                    raise PersistenceError("شناسه گفتگو متعلق به شخصیت دیگری است.")
                record = self._conversation_record(row)
                self._active_conversations[cid] = conv_id
                return record
        except PersistenceError:
            raise
        except (sqlite3.Error, OSError) as exc:
            self._note_error(exc)
            raise PersistenceError(str(exc)) from exc

    def get_or_create_conversation(self, character_id=None) -> dict[str, Any]:
        cid = _character_id(character_id)
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
                raise PersistenceError(str(exc)) from exc

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
                    (_character_id(character_id),),
                ).fetchall()
        return [self._conversation_record(row) for row in rows]

    def update_conversation(self, conversation_id: str, *, title=None, metadata=None, status=None) -> bool:
        changes, values = [], []
        if title is not None:
            changes.append("title=?"); values.append(str(title))
        if metadata is not None:
            changes.append("metadata=?"); values.append(json.dumps(_json_object(metadata), ensure_ascii=False))
        if status is not None:
            if status not in ("active", "closed", "archived"):
                raise ValueError("status must be active, closed or archived; trashed is lifecycle-owned")
            changes.append("status=?"); values.append(status)
        if not changes:
            return False
        changes.append("updated_at=?"); values.append(_now()); values.append(str(conversation_id))
        with self._lock, self._db() as con:
            row = con.execute("SELECT character_id FROM conversations WHERE id=?", (str(conversation_id),)).fetchone()
            cur = con.execute(f"UPDATE conversations SET {', '.join(changes)} WHERE id=?", values)
            if cur.rowcount and row is not None and status is not None:
                cid = _character_id(row["character_id"])
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
            metadata = _json_object(item.get("metadata"))
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
                        raise PersistenceError(f"conversation not found: {conv_id}")
                    if str(row["status"] or "active") != previous:
                        raise PersistenceError(f"conversation state changed concurrently: {conv_id}")
                    rows[conv_id] = str(row["character_id"] or "")
                stamp = _now()
                for conv_id, status, metadata_json, _ in normalized:
                    con.execute(
                        "UPDATE conversations SET status=?, metadata=?, updated_at=? WHERE id=?",
                        (status, metadata_json, stamp, conv_id),
                    )
            # Update the in-memory active pointer only after SQLite committed.
            for conv_id, status, _, _ in normalized:
                character = _character_id(rows[conv_id])
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
        stamp = _now()
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
                        raise PersistenceError(f"conversation not found: {conv_id}")
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
                        raise PersistenceError(
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
        stamp = _now()
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
                        (_character_id(character_id),),
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
                        raise PersistenceError(
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
                            raise PersistenceError("conversation state changed before permanent deletion")

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
                        raise PersistenceError(
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
            except (sqlite3.Error, OSError, PersistenceError) as exc:
                raise PersistenceError(f"حذف گفتگو ناموفق بود؛ داده‌ها حفظ شدند. ({exc})") from exc

    def add_message(self, role, content, character_id=None, *, conversation_id=None, metadata=None,
                    status="complete", message_id=None) -> bool:
        """Append idempotently; preserve queued writes and report overflow without evicting older messages."""
        cid = _character_id(character_id)
        role, body = str(role), str(content)
        if role not in ("user", "assistant", "system"):
            raise ValueError("role must be user, assistant or system")
        if status not in ("streaming", "complete", "interrupted", "failed", "cancelled"):
            raise ValueError("invalid message status")
        meta_json = json.dumps(_json_object(metadata), ensure_ascii=False, separators=(",", ":"))
        resolved_conv_id = str(conversation_id) if conversation_id else None
        fallback_conv_id = resolved_conv_id or self._active_conversations.get(cid)
        with self._lock:
            for attempt in (1, 2):
                try:
                    self._flush_pending_locked()
                    with self._db() as con:
                        self._migrate_schema(con)
                        if resolved_conv_id is None:
                            row = con.execute(
                                "SELECT id FROM conversations WHERE character_id=? AND status='active' ORDER BY updated_at DESC, rowid DESC LIMIT 1",
                                (cid,),
                            ).fetchone()
                            resolved_conv_id = str(row["id"]) if row else str(uuid.uuid4())
                            self._active_conversations[cid] = resolved_conv_id
                        row = con.execute("SELECT character_id FROM conversations WHERE id=?", (resolved_conv_id,)).fetchone()
                        if row is None:
                            self._ensure_conversation_row(con, resolved_conv_id, cid)
                        elif row["character_id"] != cid:
                            raise PersistenceError("شناسه گفتگو متعلق به شخصیت دیگری است.")
                        if message_id is not None:
                            existing_message = con.execute(
                                "SELECT character_id, conversation_id FROM messages WHERE id=?", (int(message_id),)
                            ).fetchone()
                            if existing_message and (
                                existing_message["character_id"] != cid or
                                existing_message["conversation_id"] != resolved_conv_id
                            ):
                                raise PersistenceError("شناسه پیام متعلق به گفتگوی دیگری است.")
                        if message_id is None:
                            con.execute(
                                "INSERT INTO messages(role, content, character_id, conversation_id, metadata, status) "
                                "VALUES (?, ?, ?, ?, ?, ?)",
                                (role, body, cid, resolved_conv_id, meta_json, status),
                            )
                        else:
                            con.execute(
                                "INSERT INTO messages(id, role, content, character_id, conversation_id, metadata, status) "
                                "VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET content=excluded.content, "
                                "metadata=excluded.metadata, status=excluded.status",
                                (int(message_id), role, body, cid, resolved_conv_id, meta_json, status),
                            )
                        con.execute("UPDATE conversations SET updated_at=? WHERE id=?", (_now(), resolved_conv_id))
                    self._active_conversations[cid] = resolved_conv_id
                    self.last_error = None
                    return True
                except PersistenceError:
                    raise
                except (sqlite3.Error, OSError) as exc:
                    self._note_error(exc)
                    if attempt == 1 and self._is_corruption(exc):
                        try:
                            self.startup_notes.append(self._recover(str(exc)))
                            continue
                        except (sqlite3.Error, OSError, PersistenceError) as recovery:
                            self._note_error(recovery)
                    break
            pending_conv = resolved_conv_id or fallback_conv_id or _legacy_conversation_id(cid)
            if len(self._pending) >= MAX_PENDING_MESSAGES:
                self.last_error = (
                    f"{self.last_error or 'Chat database is unavailable'}; "
                    f"in-memory write queue is full ({MAX_PENDING_MESSAGES} messages); "
                    "the newest message was not queued and existing pending messages were retained."
                )
                return False
            self._pending.append((role, body, cid, pending_conv, meta_json, status))
            return False

    @staticmethod
    def _is_corruption(exc) -> bool:
        if isinstance(exc, sqlite3.DatabaseError) and not isinstance(exc, (sqlite3.OperationalError, sqlite3.IntegrityError)):
            return True
        message = str(exc).lower()
        return any(token in message for token in ("malformed", "not a database", "disk image", "corrupt", "file is encrypted"))

    def update_stream_message(self, message_id: int, content: str, *, character_id=None,
                              conversation_id=None, metadata=None, status="streaming") -> bool:
        """Persist a stream snapshot under one stable message id (no duplicate rows per chunk)."""
        cid = _character_id(character_id)
        if status not in ("streaming", "complete", "interrupted", "failed", "cancelled"):
            raise ValueError("invalid message status")
        if conversation_id is None:
            conversation_id = self.get_or_create_conversation(cid)["id"]
        meta_json = json.dumps(_json_object(metadata), ensure_ascii=False, separators=(",", ":"))
        with self._lock, self._db() as con:
            self._migrate_schema(con)
            row = con.execute("SELECT character_id FROM conversations WHERE id=?", (str(conversation_id),)).fetchone()
            if row is not None and row["character_id"] != cid:
                raise PersistenceError("شناسه گفتگو متعلق به شخصیت دیگری است.")
            self._ensure_conversation_row(con, str(conversation_id), cid)
            existing_message = con.execute(
                "SELECT character_id, conversation_id FROM messages WHERE id=?", (int(message_id),)
            ).fetchone()
            if existing_message and (
                existing_message["character_id"] != cid or
                existing_message["conversation_id"] != str(conversation_id)
            ):
                raise PersistenceError("شناسه پیام متعلق به گفتگوی دیگری است.")
            con.execute(
                "INSERT INTO messages(id, role, content, character_id, conversation_id, metadata, status) "
                "VALUES (?, 'assistant', ?, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET content=excluded.content, "
                "metadata=excluded.metadata, status=excluded.status",
                (int(message_id), str(content), cid, str(conversation_id), meta_json, status),
            )
            con.execute("UPDATE conversations SET updated_at=? WHERE id=?", (_now(), str(conversation_id)))
        return True

    def recent_messages(self, limit=12, character_id=None, conversation_id=None):
        limit = max(0, int(limit))
        if limit == 0:
            return []
        with self._lock:
            try:
                self._flush_pending_locked()
                with self._db() as con:
                    where, args = [], []
                    if character_id is not None:
                        where.append("character_id=?"); args.append(_character_id(character_id))
                    if conversation_id is not None:
                        where.append("conversation_id=?"); args.append(str(conversation_id))
                    clause = " WHERE " + " AND ".join(where) if where else ""
                    rows = con.execute(
                        f"SELECT role, content FROM messages{clause} ORDER BY COALESCE(created_at, '') DESC, id DESC LIMIT ?", (*args, limit)
                    ).fetchall()
                return [{"role": row[0], "content": row[1]} for row in reversed(rows)]
            except (sqlite3.Error, OSError) as exc:
                self._note_error(exc)
                kept = [row for row in self._pending if
                        (character_id is None or row[2] == _character_id(character_id)) and
                        (conversation_id is None or row[3] == str(conversation_id))]
                return [{"role": row[0], "content": row[1]} for row in kept[-limit:]]

    def recent_message_records(self, limit=2000, character_id=None):
        """Return recent persisted records with metadata for crash-safe recovery policies."""
        try:
            page_size = max(0, min(int(limit), 5000))
        except (TypeError, ValueError, OverflowError):
            page_size = 0
        if page_size == 0:
            return []
        with self._lock:
            try:
                self._flush_pending_locked()
                with self._db() as con:
                    where, args = [], []
                    if character_id is not None:
                        where.append("character_id=?")
                        args.append(_character_id(character_id))
                    clause = " WHERE " + " AND ".join(where) if where else ""
                    rows = con.execute(
                        "SELECT id, role, content, created_at, character_id, conversation_id, metadata, status "
                        f"FROM messages{clause} ORDER BY COALESCE(created_at, '') DESC, id DESC LIMIT ?",
                        (*args, page_size),
                    ).fetchall()
                return [{
                    "id": int(row["id"]), "role": str(row["role"]), "content": str(row["content"]),
                    "created_at": str(row["created_at"] or ""), "character_id": str(row["character_id"] or ""),
                    "conversation_id": str(row["conversation_id"] or ""),
                    "metadata": _json_object(row["metadata"]), "status": str(row["status"] or ""),
                } for row in reversed(rows)]
            except (sqlite3.Error, OSError) as exc:
                self._note_error(exc)
                raise PersistenceError(f"Could not inspect persisted chat message records: {exc}") from exc

    def get_messages(self, limit=1000, character_id=None, conversation_id=None, after_id=0):
        with self._lock:
            self._flush_pending_locked()
            with self._db() as con:
                where, args = ["id > ?"], [int(after_id)]
                if character_id is not None:
                    where.append("character_id=?"); args.append(_character_id(character_id))
                if conversation_id is not None:
                    where.append("conversation_id=?"); args.append(str(conversation_id))
                args.append(max(0, int(limit)))
                rows = con.execute(
                    "SELECT id, role, content, created_at, character_id, conversation_id, metadata, status "
                    f"FROM messages WHERE {' AND '.join(where)} ORDER BY COALESCE(created_at, '') ASC, id ASC LIMIT ?", args
                ).fetchall()
            return [{
                "id": int(row["id"]), "role": row["role"], "content": row["content"],
                "created_at": str(row["created_at"] or ""), "character_id": row["character_id"],
                "conversation_id": row["conversation_id"], "metadata": _json_object(row["metadata"]),
                "status": row["status"],
            } for row in rows]

    def messages_after(self, after_id=0, limit=500):
        """Return a stable ID-ordered page for consumers that apply their own filters.

        This cursor is monotonic by message ID, so imported messages with older
        timestamps cannot be skipped while paging.
        """
        try:
            cursor = max(0, int(after_id))
            page_size = max(1, min(int(limit), 5000))
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("after_id and limit must be integers") from exc
        with self._lock:
            self._flush_pending_locked()
            with self._db() as con:
                rows = con.execute(
                    "SELECT id, role, content, created_at, character_id, conversation_id, metadata, status "
                    "FROM messages WHERE id > ? ORDER BY id ASC LIMIT ?",
                    (cursor, page_size),
                ).fetchall()
        return [{
            "id": int(row["id"]), "role": str(row["role"]), "content": str(row["content"] or ""),
            "created_at": str(row["created_at"] or ""), "character_id": str(row["character_id"] or ""),
            "conversation_id": str(row["conversation_id"] or ""),
            "metadata": _json_object(row["metadata"]), "status": str(row["status"] or "complete"),
        } for row in rows]

    def get_transfer_messages(self, conversation_id, character_id, after_created_at="", after_id=0, limit=1000):
        """Read an ordered bounded page for portable export using a stable keyset cursor."""
        with self._lock:
            self._flush_pending_locked()
            with self._db() as con:
                rows = con.execute(
                    "SELECT id, role, content, created_at, character_id, conversation_id, metadata, status "
                    "FROM messages WHERE conversation_id=? AND character_id=? AND "
                    "(COALESCE(created_at, '') > ? OR (COALESCE(created_at, '') = ? AND id > ?)) "
                    "ORDER BY COALESCE(created_at, '') ASC, id ASC LIMIT ?",
                    (str(conversation_id), _character_id(character_id), str(after_created_at),
                     str(after_created_at), int(after_id), max(1, min(int(limit), 5000))),
                ).fetchall()
            return [{
                "id": int(row["id"]), "role": row["role"], "content": row["content"],
                "created_at": str(row["created_at"] or ""), "character_id": row["character_id"],
                "conversation_id": row["conversation_id"], "metadata": _json_object(row["metadata"]),
                "status": row["status"],
            } for row in rows]

    def message_id_for(self, role, content, character_id=None):
        with self._db() as con:
            if character_id is None:
                row = con.execute("SELECT id FROM messages WHERE role=? AND content=? ORDER BY COALESCE(created_at, '') DESC, id DESC LIMIT 1",
                                  (str(role), str(content))).fetchone()
            else:
                row = con.execute("SELECT id FROM messages WHERE role=? AND content=? AND character_id=? ORDER BY COALESCE(created_at, '') DESC, id DESC LIMIT 1",
                                  (str(role), str(content), _character_id(character_id))).fetchone()
        return int(row[0]) if row else None

    def rows_with_ids(self, limit=3000, after_id=0, character_id=None):
        """Evidence-memory cursor API: rows must advance monotonically by message ID."""
        try:
            with self._lock:
                self._flush_pending_locked()
                with self._db() as con:
                    if character_id is None:
                        rows = con.execute(
                            "SELECT id, role, content, created_at FROM messages "
                            "WHERE id > ? ORDER BY id ASC LIMIT ?",
                            (int(after_id), max(0, int(limit))),
                        ).fetchall()
                    else:
                        rows = con.execute(
                            "SELECT id, role, content, created_at FROM messages "
                            "WHERE id > ? AND character_id=? ORDER BY id ASC LIMIT ?",
                            (int(after_id), _character_id(character_id), max(0, int(limit))),
                        ).fetchall()
            return [(int(row[0]), str(row[1]), str(row[2]), str(row[3] or "")) for row in rows]
        except (sqlite3.Error, OSError) as exc:
            self._note_error(exc)
            return []

    def max_message_id(self):
        try:
            with self._db() as con:
                return int(con.execute("SELECT COALESCE(MAX(id), 0) FROM messages").fetchone()[0])
        except (sqlite3.Error, OSError):
            return 0

    def message_count(self, character_id=None, conversation_id=None):
        try:
            with self._lock, self._db() as con:
                where, args = [], []
                if character_id is not None:
                    where.append("character_id=?"); args.append(_character_id(character_id))
                if conversation_id is not None:
                    where.append("conversation_id=?"); args.append(str(conversation_id))
                clause = " WHERE " + " AND ".join(where) if where else ""
                return int(con.execute(f"SELECT COUNT(*) FROM messages{clause}", args).fetchone()[0])
        except (sqlite3.Error, OSError) as exc:
            self._note_error(exc)
            return 0

    def pending_count(self):
        with self._lock:
            return len(self._pending)

    def list_snapshots(self, kind="cleared"):
        root = self.db_path.parent / "snapshots"
        try:
            return sorted((p for p in root.iterdir() if p.is_dir() and p.name.startswith(kind + "-")), reverse=True)
        except OSError:
            return []

    def clear_memory(self, character_id=None):
        """Snapshot first, then delete only the requested character's messages."""
        with self._lock:
            try:
                with self._db() as con:
                    self._migrate_schema(con)
                    if not con.in_transaction:
                        con.execute("BEGIN IMMEDIATE")
                    count = int(con.execute("SELECT COUNT(*) FROM messages").fetchone()[0])
                    if count:
                        # The same BEGIN IMMEDIATE transaction stays open through
                        # snapshot and deletion, preventing concurrent inserts.
                        self._snapshot("cleared")
                    if character_id is None:
                        con.execute("DELETE FROM messages")
                    else:
                        con.execute("DELETE FROM messages WHERE character_id=?", (_character_id(character_id),))
            except (sqlite3.Error, OSError, PersistenceError) as exc:
                raise PersistenceError(f"پاک‌سازی ناموفق بود؛ داده‌ها حذف نشدند یا Snapshot قبلی حفظ شد. ({exc})") from exc
            if character_id is None:
                self._pending.clear()
            else:
                self._pending[:] = [row for row in self._pending if row[2] != _character_id(character_id)]

    def import_messages(self, source) -> int:
        """Append missing messages while preserving all non-conflicting message IDs."""
        source = Path(source)
        if not source.is_file():
            raise PersistenceError("فایل انتخاب‌شده پیدا نشد.")
        incoming = self._read_rows_full(source)
        incoming_conversations = self._read_conversations(source)
        if not incoming and not incoming_conversations:
            return 0
        with self._lock:
            try:
                self._flush_pending_locked()
                current = self._read_rows_full(self.db_path)
                seen_keys = {self._message_key(row) for row in current}
                current_ids = {int(row[0]) for row in current}
                source_ids = {
                    fields[0] for fields in (self._message_fields(row) for row in incoming)
                    if fields[0] is not None
                }
                used_ids = set(current_ids)
                next_id = max({0, *current_ids, *source_ids}) + 1
                new_rows = []
                for index, raw_row in enumerate(incoming):
                    source_id, role, body, stamp, cid, conv_id, metadata, status = self._message_fields(raw_row)
                    key = (role, body, stamp, cid, conv_id)
                    if key in seen_keys:
                        continue
                    seen_keys.add(key)
                    # Keep the source ID if unused; collisions receive a fresh ID
                    # above every existing and source ID to avoid changing references.
                    if source_id is None or source_id in used_ids:
                        while next_id in used_ids:
                            next_id += 1
                        message_id = next_id
                        next_id += 1
                    else:
                        message_id = source_id
                    used_ids.add(message_id)
                    new_rows.append((stamp, index, message_id, role, body, cid, conv_id, metadata, status))
                new_rows.sort(key=lambda row: (row[0], row[1]))
                current_conversation_ids = {
                    row["id"] for row in self._read_conversations(self.db_path)
                }
                has_new_conversations = any(
                    row["id"] not in current_conversation_ids for row in incoming_conversations
                )
                if not new_rows and not has_new_conversations:
                    return 0
                if current or current_conversation_ids:
                    self._snapshot("before-import")
                with self._db() as con:
                    self._migrate_schema(con)
                    for conversation in incoming_conversations:
                        existing = con.execute(
                            "SELECT character_id FROM conversations WHERE id=?", (conversation["id"],)
                        ).fetchone()
                        if existing is not None and _character_id(existing["character_id"]) != _character_id(conversation["character_id"]):
                            raise PersistenceError("شناسه گفتگوی واردشده به شخصیت دیگری تعلق دارد.")
                        con.execute(
                            "INSERT OR IGNORE INTO conversations(id, character_id, title, metadata, status, created_at, updated_at) "
                            "VALUES (?, ?, ?, ?, ?, ?, ?)",
                            (conversation["id"], conversation["character_id"], conversation["title"],
                             json.dumps(conversation["metadata"], ensure_ascii=False), conversation["status"],
                             conversation["created_at"], conversation["updated_at"]),
                        )
                    for stamp, _, message_id, role, body, cid, conv_id, metadata, status in new_rows:
                        self._ensure_conversation_row(con, conv_id, cid, stamp or None)
                        con.execute(
                            "INSERT INTO messages(id, role, content, created_at, character_id, conversation_id, metadata, status) "
                            "VALUES (?, ?, ?, NULLIF(?, ''), ?, ?, ?, ?)",
                            (message_id, role, body, stamp or "", cid, conv_id, metadata, status),
                        )
                return len(new_rows)
            except (sqlite3.Error, OSError, PersistenceError) as exc:
                raise PersistenceError(f"ورود چت ناموفق بود (چیزی تغییر نکرد): {exc}") from exc

    def import_transfer_records(self, conversations, messages):
        """Atomically append validated transfer records without overwriting existing data."""
        with self._lock:
            self._flush_pending_locked()
            try:
                with self._db() as con:
                    self._migrate_schema(con)
                    conversation_map = {}
                    imported_conversations = remapped_conversations = 0
                    for item in conversations:
                        source_id = str(item["id"])
                        character_id = _character_id(item["character_id"])
                        existing = con.execute("SELECT character_id FROM conversations WHERE id=?", (source_id,)).fetchone()
                        target_id = source_id
                        if existing is not None and _character_id(existing["character_id"]) != character_id:
                            target_id = str(uuid.uuid4())
                            remapped_conversations += 1
                        conversation_map[source_id] = target_id
                        if existing is None or target_id != source_id:
                            con.execute(
                                "INSERT INTO conversations(id, character_id, title, metadata, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                                (target_id, character_id, str(item.get("title", "")),
                                 json.dumps(_json_object(item.get("metadata")), ensure_ascii=False),
                                 str(item.get("status", "active")), str(item.get("created_at", "")),
                                 str(item.get("updated_at", item.get("created_at", "")))),
                            )
                            imported_conversations += 1
                    signatures = set()
                    for row in con.execute("SELECT role, content, created_at, character_id, conversation_id, metadata, status FROM messages"):
                        signatures.add((str(row[0]), str(row[1]), str(row[2] or ""), _character_id(row[3]),
                                        str(row[4] or ""), json.dumps(_json_object(row[5]), ensure_ascii=False, sort_keys=True),
                                        str(row[6] or "complete")))
                    used_ids = {int(row[0]) for row in con.execute("SELECT id FROM messages")}
                    # If any non-duplicate ID collision occurs in a conversation, allocate
                    # fresh IDs for that conversation's imported messages as a group. This
                    # keeps equal-timestamp message order stable under the repository's
                    # (created_at, id) ordering contract.
                    order_remap_conversations = set()
                    seen_source_ids = set()
                    for item in messages:
                        source_id = item.get("id")
                        conv_id = conversation_map[str(item["conversation_id"])]
                        cid = _character_id(item["character_id"])
                        metadata = _json_object(item.get("metadata"))
                        signature = (
                            str(item["role"]), str(item["content"]), str(item.get("created_at", "")),
                            cid, conv_id, json.dumps(metadata, ensure_ascii=False, sort_keys=True),
                            str(item.get("status", "complete")),
                        )
                        if signature not in signatures and source_id is not None and (
                            int(source_id) in used_ids or int(source_id) in seen_source_ids
                        ):
                            order_remap_conversations.add(conv_id)
                        if source_id is not None:
                            seen_source_ids.add(int(source_id))
                    imported_messages = skipped_duplicates = remapped_messages = 0
                    for item in messages:
                        cid = _character_id(item["character_id"])
                        conv_id = conversation_map[str(item["conversation_id"])]
                        role, body = str(item["role"]), str(item["content"])
                        stamp = str(item.get("created_at", ""))
                        metadata = _json_object(item.get("metadata"))
                        status = str(item.get("status", "complete"))
                        meta_json = json.dumps(metadata, ensure_ascii=False, separators=(",", ":"))
                        signature = (role, body, stamp, cid, conv_id,
                                     json.dumps(metadata, ensure_ascii=False, sort_keys=True), status)
                        if signature in signatures:
                            skipped_duplicates += 1
                            continue
                        source_id = item.get("id")
                        if source_id is not None and int(source_id) not in used_ids and conv_id not in order_remap_conversations:
                            con.execute(
                                "INSERT INTO messages(id, role, content, created_at, character_id, conversation_id, metadata, status) VALUES (?, ?, ?, NULLIF(?, ''), ?, ?, ?, ?)",
                                (int(source_id), role, body, stamp, cid, conv_id, meta_json, status),
                            )
                            used_ids.add(int(source_id))
                        else:
                            if source_id is not None:
                                remapped_messages += 1
                            con.execute(
                                "INSERT INTO messages(role, content, created_at, character_id, conversation_id, metadata, status) VALUES (?, ?, NULLIF(?, ''), ?, ?, ?, ?)",
                                (role, body, stamp, cid, conv_id, meta_json, status),
                            )
                            used_ids.add(int(con.execute("SELECT last_insert_rowid()").fetchone()[0]))
                        signatures.add(signature)
                        imported_messages += 1
                    return {
                        "imported_conversations": imported_conversations,
                        "imported_messages": imported_messages,
                        "skipped_duplicates": skipped_duplicates,
                        "remapped_conversations": remapped_conversations,
                        "remapped_messages": remapped_messages,
                        "conversation_id_map": conversation_map,
                    }
            except (sqlite3.Error, OSError, PersistenceError, ValueError, TypeError) as exc:
                raise PersistenceError(f"ورود مکالمات ناموفق بود؛ تراکنش بازگردانی شد: {exc}") from exc

    def _ensure_conversation_rows(self, con, rows):
        for raw_row in rows:
            _, role, body, stamp, cid, conv_id, metadata, status = self._message_fields(raw_row)
            self._ensure_conversation_row(con, conv_id, cid, stamp or None)

    def restore_last_cleared(self):
        for snapshot in self.list_snapshots("cleared"):
            candidate = snapshot / DB_NAME
            if candidate.is_file():
                return self.import_messages(candidate)
        raise PersistenceError("هیچ پاک‌سازی قبلی برای بازگردانی پیدا نشد.")

    def conversation_context(self, limit=12, max_chars=12000, character_id=None, conversation_id=None):
        messages = self.recent_messages(max(1, int(limit)), character_id, conversation_id)
        kept, used = [], 0
        for item in reversed(messages):
            role = item.get("role")
            content = str(item.get("content") or "").strip()
            if role not in ("user", "assistant") or not content:
                continue
            content = content[-4000:]
            cost = len(content)
            if kept and used + cost > max_chars:
                break
            kept.append({"role": role, "content": content})
            used += cost
        return list(reversed(kept))
