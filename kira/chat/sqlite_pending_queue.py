"""Durable pending-message spool and idempotent SQLite replay."""
from __future__ import annotations

import json
import os
import uuid


class SqlitePendingMessageQueue:
    def __init__(self, repository, *, max_pending: int, persistence_error):
        self._repository = repository
        self._max_pending = max(1, int(max_pending))
        self._persistence_error = persistence_error

    def spool_path(self):
        path = self._repository.db_path
        return path.with_name(path.name + ".pending.jsonl")

    def rows_locked(self):
        repo, rows = self._repository, {}
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
                            row = (str(role), str(body), str(cid or "").strip().lower() or "kira",
                                   str(conv_id), str(metadata), str(status), str(token))
                        except (TypeError, ValueError, json.JSONDecodeError) as exc:
                            raise self._persistence_error(
                                f"صف اضطراری پیام‌ها خراب است (خط {line_number}): {exc}"
                            ) from exc
                        rows.setdefault(row[6], row)
            except OSError as exc:
                raise self._persistence_error(f"صف اضطراری پیام‌ها خوانده نشد: {exc}") from exc
        for index, raw in enumerate(repo._pending):
            row = tuple(raw)
            if len(row) == 6:
                row = (*row, uuid.uuid4().hex)
                repo._pending[index] = row
            if len(row) == 7 and str(row[6] or ""):
                rows.setdefault(str(row[6]), row)
        return list(rows.values())

    def enqueue_locked(self, row):
        repo, spool = self._repository, self.spool_path()
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
            repo._note_error(exc)
            try:
                if spool.exists():
                    with spool.open("r+b") as handle:
                        handle.truncate(original_size)
                        handle.flush()
                        os.fsync(handle.fileno())
            except OSError as rollback_exc:
                repo._note_error(rollback_exc)
        cached = len(repo._pending) < self._max_pending
        if cached:
            repo._pending.append(row)
        if persisted:
            repo.last_error = "SQLite در دسترس نیست؛ پیام در صف اضطراری دیسک ذخیره شد و پس از بازیابی دیتابیس منتقل می‌شود."
            return True
        if cached:
            repo.last_error = "SQLite و صف اضطراری دیسک در دسترس نیستند؛ پیام فعلاً فقط در حافظه نگه داشته شد. برنامه را نبند تا ذخیره‌سازی بازیابی شود."
            return True
        repo.last_error = (
            "ذخیره‌سازی ناموفق است و صف اضطراری هم قابل نوشتن نیست؛ پیام جدید ذخیره یا صف‌بندی نشد. "
            f"صف حافظه به سقف {self._max_pending} پیام رسیده است."
        )
        return False

    def flush_locked(self):
        repo = self._repository
        pending = self.rows_locked()
        if not pending:
            return
        with repo._db() as connection:
            repo._migrate_schema(connection)
            for role, body, cid, conv_id, metadata, status, token in pending:
                receipt = connection.execute(
                    "INSERT OR IGNORE INTO persistence_receipts(token) VALUES (?)", (token,)
                )
                if receipt.rowcount:
                    repo._ensure_conversation_row(connection, conv_id, cid)
                    connection.execute(
                        "INSERT INTO messages(role, content, character_id, conversation_id, metadata, status) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (role, body, cid, conv_id, metadata, status),
                    )
        repo._pending.clear()
        try:
            self.spool_path().unlink(missing_ok=True)
        except OSError as exc:
            repo._note_error(exc)
