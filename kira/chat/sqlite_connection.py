"""Central SQLite connection policy and explicit Unit of Work."""
from __future__ import annotations

import sqlite3
from pathlib import Path

SQLITE_BUSY_TIMEOUT_SECONDS = 0.25
SQLITE_WAL_AUTOCHECKPOINT_PAGES = 1000


class SqliteUnitOfWork:
    def __init__(self, manager: "SqliteConnectionManager", path=None):
        self._manager, self._path = manager, path
        self._connection = None
        self._entered = False

    def __enter__(self):
        if self._entered:
            raise RuntimeError("A SQLite Unit of Work cannot be re-entered")
        self._entered = True
        self._connection = self._manager.connect(self._path)
        return self._connection

    def __exit__(self, exc_type, exc, traceback):
        connection, self._connection = self._connection, None
        if connection is None:
            return False
        try:
            connection.rollback() if exc_type is not None else connection.commit()
        finally:
            connection.close()
        return False


class SqliteConnectionManager:
    """Only owner of normal chat SQLite connections and connection policy."""

    def __init__(self, path_provider):
        self._path_provider = path_provider

    def connect(self, path=None, *, apply_connection_policy=True):
        target = Path(path or self._path_provider())
        target.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(
            str(target), timeout=SQLITE_BUSY_TIMEOUT_SECONDS, isolation_level="DEFERRED"
        )
        connection.row_factory = sqlite3.Row
        if apply_connection_policy:
            try:
                connection.execute("PRAGMA foreign_keys = ON")
                connection.execute(f"PRAGMA busy_timeout = {int(SQLITE_BUSY_TIMEOUT_SECONDS * 1000)}")
                connection.execute("PRAGMA synchronous = FULL")
                connection.execute(f"PRAGMA wal_autocheckpoint = {SQLITE_WAL_AUTOCHECKPOINT_PAGES}")
            except BaseException:
                connection.close()
                raise
        return connection

    def connect_readonly(self, path, *, timeout_seconds=5.0):
        target = Path(path).resolve()
        connection = sqlite3.connect(
            target.as_uri() + "?mode=ro", uri=True, timeout=float(timeout_seconds)
        )
        connection.row_factory = sqlite3.Row
        return connection

    def configure_database(self, path=None):
        connection = self.connect(path)
        try:
            mode = str(connection.execute("PRAGMA journal_mode = WAL").fetchone()[0]).lower()
            if mode != "wal":
                raise sqlite3.OperationalError(
                    f"SQLite WAL policy could not be applied (journal_mode={mode})"
                )
            connection.execute("PRAGMA synchronous = FULL")
            connection.execute(f"PRAGMA wal_autocheckpoint = {SQLITE_WAL_AUTOCHECKPOINT_PAGES}")
            connection.commit()
            return mode
        finally:
            connection.close()

    def unit_of_work(self, path=None):
        return SqliteUnitOfWork(self, path)
