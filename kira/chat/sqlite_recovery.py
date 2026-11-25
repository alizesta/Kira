"""Crash recovery and online snapshot lifecycle for chat SQLite storage."""
from __future__ import annotations

import shutil
import sqlite3
import time
from pathlib import Path


class SqliteRecoveryManager:
    def __init__(self, repository, *, db_name: str, snapshots_keep: int, persistence_error):
        self._repository = repository
        self._db_name = db_name
        self._snapshots_keep = max(1, int(snapshots_keep))
        self._persistence_error = persistence_error

    def healthy(self, path: Path) -> bool:
        path = Path(path)
        if not path.exists():
            return True
        try:
            con = self._repository._connections.connect_readonly(path, timeout_seconds=5)
            try:
                result = con.execute("PRAGMA quick_check").fetchone()
                if not result or result[0] != "ok":
                    return False
                if self._repository._has_table(con, "messages"):
                    con.execute("SELECT COUNT(*) FROM messages").fetchone()
                return True
            finally:
                con.close()
        except sqlite3.Error:
            return False

    def snapshot(self, kind: str) -> Path:
        repo = self._repository
        root = repo.db_path.parent / "snapshots"
        root.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        target, suffix = root / f"{kind}-{stamp}", 1
        while target.exists():
            suffix += 1
            target = root / f"{kind}-{stamp}-{suffix}"
        target.mkdir()
        source = repo._connections.connect(repo.db_path)
        try:
            destination = repo._connections.connect(target / self._db_name, apply_connection_policy=False)
            try:
                source.backup(destination)
            finally:
                destination.close()
        finally:
            source.close()
        old = sorted(p for p in root.iterdir() if p.is_dir() and p.name.startswith(kind + "-"))
        for folder in old[:-self._snapshots_keep]:
            shutil.rmtree(folder, ignore_errors=True)
        return target

    def backup_dirs(self):
        root = self._repository.db_path.parent / "backups"
        try:
            return sorted((p for p in root.iterdir() if p.is_dir()), reverse=True)
        except OSError:
            return []

    def latest_backup_rows(self):
        repo = self._repository
        for folder in self.backup_dirs():
            candidate = folder / self._db_name
            if candidate.is_file() and self.healthy(candidate):
                return repo._read_rows_full(candidate), candidate
        return [], None

    def recover(self, reason: str) -> str:
        repo = self._repository
        stamp = time.strftime("%Y%m%d-%H%M%S")
        salvaged = repo._read_rows_full(repo.db_path)
        salvaged_conversations = repo._read_conversations(repo.db_path)
        quarantine = repo.db_path.with_name(f"kira_memory.corrupt-{stamp}.sqlite3")
        suffix = 1
        while quarantine.exists():
            suffix += 1
            quarantine = repo.db_path.with_name(f"kira_memory.corrupt-{stamp}-{suffix}.sqlite3")
        try:
            repo.db_path.replace(quarantine)
            for side_suffix in ("-journal", "-wal", "-shm"):
                side = Path(str(repo.db_path) + side_suffix)
                if side.exists():
                    side.replace(Path(str(quarantine) + side_suffix))
        except OSError as exc:
            raise self._persistence_error(f"فایل دیتابیس خراب جابه‌جا نشد: {exc}") from exc
        backup_rows, backup = self.latest_backup_rows()
        backup_conversations = repo._read_conversations(backup) if backup else []
        merged = repo._merge(backup_rows, salvaged)
        repo._write_all(merged)
        repo._restore_conversation_metadata([*backup_conversations, *salvaged_conversations])
        source = f" و از پشتیبان «{backup.parent.name}» کامل شد" if backup and backup_rows else ""
        return (
            f"دیتابیس گفتگو خراب بود ({reason}). فایل خراب پاک نشد و با نام «{quarantine.name}» "
            f"کنار گذاشته شد؛ {len(salvaged)} پیام از آن نجات یافت{source}. "
            f"در مجموع {len(merged)} پیام بازیابی شد."
        )
