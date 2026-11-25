"""Crash recovery orchestration over explicit persistence ports."""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Callable



class SqliteRecoveryManager:
    """Own database health checks, backup discovery, quarantine and recovery.

    The manager depends on narrow persistence callbacks, never on the concrete
    repository or its private attributes. Snapshot file lifecycle is delegated
    to SqliteSnapshotManager.
    """

    def __init__(
        self,
        *,
        db_path_provider: Callable[[], Path],
        connection_manager,
        read_rows: Callable[[Path], list[tuple]],
        read_conversations: Callable[[Path], list[dict]],
        merge_rows: Callable[..., list[tuple]],
        write_recovery_state: Callable[[list[tuple], list[dict]], None],
        db_name: str,
        persistence_error: type[Exception],
    ):
        self._db_path = db_path_provider
        self._connections = connection_manager
        self._read_rows = read_rows
        self._read_conversations = read_conversations
        self._merge_rows = merge_rows
        self._write_recovery_state = write_recovery_state
        self._db_name = str(db_name)
        self._persistence_error = persistence_error

    def healthy(self, path: Path) -> bool:
        path = Path(path)
        if not path.exists():
            return True
        try:
            connection = self._connections.connect_readonly(path, timeout_seconds=5)
            try:
                result = connection.execute("PRAGMA quick_check").fetchone()
                if not result or result[0] != "ok":
                    return False
                has_messages = connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='messages'"
                ).fetchone()
                if has_messages:
                    connection.execute("SELECT COUNT(*) FROM messages").fetchone()
                return True
            finally:
                connection.close()
        except sqlite3.Error:
            return False

    def backup_dirs(self) -> list[Path]:
        root = Path(self._db_path()).parent / "backups"
        try:
            return sorted((item for item in root.iterdir() if item.is_dir()), reverse=True)
        except OSError:
            return []

    def latest_backup_rows(self):
        for folder in self.backup_dirs():
            candidate = folder / self._db_name
            if candidate.is_file() and self.healthy(candidate):
                return self._read_rows(candidate), candidate
        return [], None

    def recover(self, reason: str) -> str:
        database = Path(self._db_path())
        stamp = time.strftime("%Y%m%d-%H%M%S")
        salvaged = self._read_rows(database)
        salvaged_conversations = self._read_conversations(database)
        quarantine = database.with_name(f"kira_memory.corrupt-{stamp}.sqlite3")
        suffix = 1
        while quarantine.exists():
            suffix += 1
            quarantine = database.with_name(f"kira_memory.corrupt-{stamp}-{suffix}.sqlite3")
        try:
            database.replace(quarantine)
            for side_suffix in ("-journal", "-wal", "-shm"):
                side = Path(str(database) + side_suffix)
                if side.exists():
                    side.replace(Path(str(quarantine) + side_suffix))
        except OSError as exc:
            raise self._persistence_error(f"فایل دیتابیس خراب جابه‌جا نشد: {exc}") from exc

        backup_rows, backup = self.latest_backup_rows()
        backup_conversations = self._read_conversations(backup) if backup else []
        merged = self._merge_rows(backup_rows, salvaged)
        # Messages and conversation metadata share one Unit of Work. A failed
        # metadata validation therefore rolls back the entire recovery rewrite.
        self._write_recovery_state(merged, [*backup_conversations, *salvaged_conversations])
        source = f" و از پشتیبان «{backup.parent.name}» کامل شد" if backup and backup_rows else ""
        return (
            f"دیتابیس گفتگو خراب بود ({reason}). فایل خراب پاک نشد و با نام «{quarantine.name}» "
            f"کنار گذاشته شد؛ {len(salvaged)} پیام از آن نجات یافت{source}. "
            f"در مجموع {len(merged)} پیام بازیابی شد."
        )
