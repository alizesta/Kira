"""Backward-compatible imports for the extracted chat persistence repository.

New application code must depend on kira.chat.persistence. This module only
preserves the historical public functions used by existing Kira integrations.
"""
from __future__ import annotations

import contextlib
import sqlite3
from pathlib import Path

from .config import DB_PATH
from .chat.persistence import (
    ChatPersistence,
    PersistenceError,
    _DEFAULT_REPOSITORY,
    _character_id,
)

DB_NAME = "kira_memory.sqlite3"
SNAPSHOTS_KEEP = 5
DEFAULT_CHARACTER = "kira"
ChatStoreError = PersistenceError

repository = _DEFAULT_REPOSITORY
repository._db_path = lambda: Path(DB_PATH)
chat_persistence = ChatPersistence(repository)
_pending = repository._pending
_lock = repository._lock
last_error: str | None = repository.last_error
startup_notes = repository.startup_notes


def _sync_in():
    repository._db_path = lambda: Path(DB_PATH)
    repository.last_error = last_error


def _sync_out():
    global last_error
    last_error = repository.last_error


@contextlib.contextmanager
def _db(path=None):
    with repository._db(path) as con:
        yield con


def _create(con):
    repository._create_schema(con)


def _cid(character_id):
    return _character_id(character_id)


def _row4(row):
    role, content = row[0], row[1]
    stamp = row[2] if len(row) > 2 else ""
    cid = _cid(row[3] if len(row) > 3 else None)
    return role, content, stamp, cid


def _data_dir() -> Path:
    return Path(DB_PATH).parent


def _healthy(path: Path) -> bool:
    return repository._healthy(path)


def read_rows(path):
    return repository.read_rows(path)


def read_rows_full(path):
    # Historical API: (role, content, timestamp, character_id).
    return [(row[1], row[2], row[3], row[4]) for row in repository.read_rows_full(path)]


def _merge(*sources):
    return repository._merge(*sources)


def _write_all(rows):
    return repository._write_all(rows)


def _backup_dirs():
    return repository._backup_dirs()


def _latest_backup_rows():
    rows, path = repository._latest_backup_rows()
    legacy_rows = [(row[1], row[2], row[3], row[4]) for row in rows]
    return legacy_rows, path


def _recover(reason: str):
    result = repository._recover(reason)
    _sync_out()
    return result


def _note_error(exc):
    repository._note_error(exc)
    _sync_out()


def init_db() -> list[str]:
    _sync_in()
    result = repository.init_db()
    _sync_out()
    return result


def add_message(role, content, character_id=None, **options) -> bool:
    _sync_in()
    result = repository.add_message(role, content, character_id, **options)
    _sync_out()
    return result


def recent_messages(limit=12, character_id=None, conversation_id=None):
    _sync_in()
    result = repository.recent_messages(limit, character_id, conversation_id)
    _sync_out()
    return result


def get_messages(limit=1000, character_id=None, conversation_id=None, after_id=0):
    _sync_in()
    return repository.get_messages(limit, character_id, conversation_id, after_id)


def rows_with_ids(limit=3000, after_id=0, character_id=None):
    return repository.rows_with_ids(limit, after_id, character_id)


def max_message_id():
    return repository.max_message_id()


def message_id_for(role, content, character_id=None):
    return repository.message_id_for(role, content, character_id)


def message_count(character_id=None, conversation_id=None):
    try:
        return repository.message_count(character_id, conversation_id)
    except (sqlite3.Error, OSError):
        return 0


def pending_count():
    return repository.pending_count()


def _snapshot(kind: str):
    return repository._snapshot(kind)


def list_snapshots(kind="cleared"):
    return repository.list_snapshots(kind)


def clear_memory(character_id=None):
    _sync_in()
    try:
        return repository.clear_memory(character_id)
    finally:
        _sync_out()


def import_messages(source):
    _sync_in()
    return repository.import_messages(source)


def restore_last_cleared():
    return repository.restore_last_cleared()


def conversation_context(limit=12, max_chars=12000, character_id=None, conversation_id=None):
    _sync_in()
    return repository.conversation_context(limit, max_chars, character_id, conversation_id)


def create_conversation(character_id=None, title="", metadata=None, conversation_id=None):
    return repository.create_conversation(character_id, title, metadata, conversation_id)


def get_or_create_conversation(character_id=None):
    return repository.get_or_create_conversation(character_id)


def get_conversation(conversation_id):
    return repository.get_conversation(conversation_id)


def list_conversations(character_id=None):
    return repository.list_conversations(character_id)


def update_conversation(conversation_id, **changes):
    return repository.update_conversation(conversation_id, **changes)


def close_conversation(conversation_id):
    return repository.close_conversation(conversation_id)


def delete_conversation(conversation_id):
    return repository.delete_conversation(conversation_id)


def update_stream_message(message_id, content, **options):
    return repository.update_stream_message(message_id, content, **options)


if __name__ == "__main__":
    print("Chat database:", DB_PATH)
