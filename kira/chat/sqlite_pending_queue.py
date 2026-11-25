"""Durable pending-message spool and idempotent SQLite replay."""
from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Callable


class SqlitePendingMessageQueue:
    """Persistent queue with explicit ports; no knowledge of repository internals."""

    def __init__(
        self,
        *,
        db_path_provider: Callable[[], Path],
        pending_getter: Callable[[], list],
        pending_clearer: Callable[[], None],
        unit_of_work: Callable,
        migrate_schema: Callable,
        ensure_conversation_row: Callable,
        set_error: Callable[[str | None], None],
        note_error: Callable[[BaseException], None],
        max_pending: int,
        persistence_error: type[Exception],
    ):
        self._db_path = db_path_provider
        self._pending = pending_getter
        self._clear_pending = pending_clearer
        self._unit_of_work = unit_of_work
        self._migrate_schema = migrate_schema
        self._ensure_conversation_row = ensure_conversation_row
        self._set_error = set_error
        self._note_error = note_error
        self._max_pending = max(1, int(max_pending))
        self._persistence_error = persistence_error

    def spool_path(self) -> Path:
        path = Path(self._db_path())
        return path.with_name(path.name + ".pending.jsonl")

    def rows_locked(self) -> list[tuple]:
        rows = {}
        spool = self.spool_path()
        if spool.is_file():
            try:
                with spool.open("r", encoding="utf-8") as handle:
                    for line_number, line in enumerate(handle, 1):
                        if not line.strip():
                            continue
                        try:
                            raw = json.loads(line)
                            if not isinstance(raw, list) or len(raw) != 7:
                                raise ValueError("invalid row shape")
                            role, body, cid, conv_id, metadata, status, token = raw
                            if role not in ("user", "assistant", "system"):
                                raise ValueError("invalid role")
                            if status not in ("streaming", "complete", "interrupted", "failed", "cancelled"):
                                raise ValueError("invalid status")
                            if not str(token or ""):
                                raise ValueError("missing queue token")
                            row = (
                                str(role), str(body), str(cid or "").strip().lower() or "kira",
                                str(conv_id), str(metadata), str(status), str(token),
                            )
                        except (TypeError, ValueError, json.JSONDecodeError) as exc:
                            raise self._persistence_error(
                                f"صف اضطراری پیام‌ها خراب است (خط {line_number}): {exc}"
                            ) from exc
                        rows.setdefault(row[6], row)
            except OSError as exc:
                raise self._persistence_error(f"صف اضطراری پیام‌ها خوانده نشد: {exc}") from exc

        for raw in self._pending():
            row = tuple(raw)
            if len(row) == 6:
                # Legacy in-memory entries have no durable token. Normalize this
                # read without mutating the compatibility queue owned by the app.
                row = (*row, uuid.uuid4().hex)
            if len(row) == 7 and str(row[6] or ""):
                rows.setdefault(str(row[6]), row)
        return list(rows.values())

    def enqueue_locked(self, row) -> bool:
        spool = self.spool_path()
        pending = self._pending()
        if len(self.rows_locked()) >= self._max_pending:
            self._set_error(
                f"صف پیام‌های معوق پر است (queue is full): جدیدترین پیام در صف قرار نگرفت "
                f"(newest message was not queued). سقف {self._max_pending} پیام است."
            )
            return False

        original_size = 0
        try:
            spool.parent.mkdir(parents=True, exist_ok=True)
            original_size = spool.stat().st_size if spool.exists() else 0
            payload = json.dumps(list(row), ensure_ascii=False, separators=(",", ":")) + "\n"
            with spool.open("a", encoding="utf-8", newline="") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            persisted = True
        except (OSError, TypeError, ValueError) as exc:
            persisted = False
            self._note_error(exc)
            try:
                if spool.exists():
                    with spool.open("r+b") as handle:
                        handle.truncate(original_size)
                        handle.flush()
                        os.fsync(handle.fileno())
            except OSError as rollback_exc:
                self._note_error(rollback_exc)

        cached = len(pending) < self._max_pending
        if cached:
            pending.append(row)
        if persisted:
            self._set_error(
                "SQLite در دسترس نیست؛ پیام در صف اضطراری دیسک ذخیره شد و پس از بازیابی دیتابیس منتقل می‌شود."
            )
            return True
        if cached:
            self._set_error(
                "SQLite و صف اضطراری دیسک در دسترس نیستند؛ پیام فعلاً فقط در حافظه نگه داشته شد. "
                "برنامه را نبند تا ذخیره‌سازی بازیابی شود."
            )
            return True
        self._set_error(
            "ذخیره‌سازی ناموفق است و صف اضطراری هم قابل نوشتن نیست؛ پیام جدید ذخیره یا صف‌بندی نشد. "
            f"صف حافظه به سقف {self._max_pending} پیام رسیده است."
        )
        return False

    def flush_locked(self) -> None:
        pending = self.rows_locked()
        if not pending:
            return
        # Receipt insert and message insert share the same transaction. A crash
        # before spool cleanup can replay safely without duplicating a message.
        with self._unit_of_work() as connection:
            self._migrate_schema(connection)
            for role, body, cid, conv_id, metadata, status, token in pending:
                receipt = connection.execute(
                    "INSERT OR IGNORE INTO persistence_receipts(token) VALUES (?)", (token,)
                )
                if receipt.rowcount:
                    self._ensure_conversation_row(connection, conv_id, cid)
                    connection.execute(
                        "INSERT INTO messages(role, content, character_id, conversation_id, metadata, status) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (role, body, cid, conv_id, metadata, status),
                    )
        self._clear_pending()
        try:
            self.spool_path().unlink(missing_ok=True)
        except OSError as exc:
            self._note_error(exc)
