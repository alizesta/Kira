"""Independent online SQLite snapshot creation and retention."""
from __future__ import annotations

import shutil
import time
from pathlib import Path


class SqliteSnapshotManager:
    """Own snapshot files, SQLite online backup, and per-kind retention."""

    def __init__(self, db_path_provider, connection_manager, *, db_name: str, keep: int = 5):
        self._db_path = db_path_provider
        self._connections = connection_manager
        self._db_name = str(db_name)
        self._keep = max(1, int(keep))

    def create(self, kind: str) -> Path:
        kind = str(kind or "").strip()
        if not kind or any(char in kind for char in "/\\"):
            raise ValueError("snapshot kind must be a non-empty path-safe name")
        database = Path(self._db_path())
        root = database.parent / "snapshots"
        root.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        target = root / f"{kind}-{stamp}"
        suffix = 1
        while target.exists():
            suffix += 1
            target = root / f"{kind}-{stamp}-{suffix}"
        target.mkdir()
        try:
            source = self._connections.connect(database)
            try:
                destination = self._connections.connect(
                    target / self._db_name, apply_connection_policy=False
                )
                try:
                    source.backup(destination)
                finally:
                    destination.close()
            finally:
                source.close()
        except BaseException:
            shutil.rmtree(target, ignore_errors=True)
            raise
        old = sorted(
            (item for item in root.iterdir()
             if item.is_dir() and item.name.startswith(kind + "-")),
            key=lambda item: item.name,
        )
        for folder in old[:-self._keep]:
            shutil.rmtree(folder, ignore_errors=True)
        return target

    def list(self, kind: str = "cleared") -> list[Path]:
        root = Path(self._db_path()).parent / "snapshots"
        try:
            return sorted(
                (item for item in root.iterdir()
                 if item.is_dir() and item.name.startswith(str(kind) + "-")),
                reverse=True,
            )
        except OSError:
            return []
