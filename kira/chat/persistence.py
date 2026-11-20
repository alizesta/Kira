"""Qt-free chat persistence and history."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ..config import DB_PATH  # noqa: F401 - re-exported for compatibility
from .sqlite_repository import (  # noqa: F401 - re-exported for backward compatibility
    DB_NAME,
    DEFAULT_CHARACTER,
    MAX_PENDING_MESSAGES,
    SCHEMA_VERSION,
    SNAPSHOTS_KEEP,
    ChatRepository,
    ChatStoreError,
    PersistenceError,
    SqliteChatRepository,
    _character_id,
    _json_object,
    _legacy_conversation_id,
    _now,
)

class ChatPersistence:
    """Application-facing, replaceable persistence API shared by all characters."""

    def __init__(self, repository: ChatRepository):
        if repository is None:
            raise TypeError("repository is required")
        self._repository = repository

    def _invoke(self, operation, *args, **kwargs):
        try:
            return operation(*args, **kwargs)
        except PersistenceError as exc:
            self._repository.last_error = str(exc)
            raise
        except Exception as exc:
            self._repository.last_error = f"{type(exc).__name__}: {exc}"
            raise PersistenceError(self._repository.last_error) from exc

    @property
    def last_error(self) -> str | None:
        return self._repository.last_error

    def set_last_error(self, message: str | None) -> None:
        self._repository.last_error = str(message) if message else None

    @property
    def startup_notes(self) -> list[str]:
        return list(getattr(self._repository, "startup_notes", []))

    def init_db(self) -> list[str]:
        return self._repository.init_db()

    def flush_pending(self) -> int:
        flusher = getattr(self._repository, "flush_pending", None)
        if not callable(flusher):
            return 0
        return self._invoke(flusher)

    def create_conversation(self, character_id=None, title="", metadata=None, conversation_id=None):
        return self._invoke(self._repository.create_conversation, character_id, title, metadata, conversation_id)

    def get_or_create_conversation(self, character_id=None):
        return self._invoke(self._repository.get_or_create_conversation, character_id)

    def get_conversation(self, conversation_id):
        return self._invoke(self._repository.get_conversation, conversation_id)

    def list_conversations(self, character_id=None):
        return self._invoke(self._repository.list_conversations, character_id)

    def update_conversation(self, conversation_id, **changes):
        return self._invoke(self._repository.update_conversation, conversation_id, **changes)

    def close_conversation(self, conversation_id):
        return self._invoke(self._repository.close_conversation, conversation_id)

    def delete_conversation(self, conversation_id, **options):
        return self._invoke(self._repository.delete_conversation, conversation_id, **options)

    def update_conversation_lifecycle(self, changes):
        return self._invoke(self._repository.update_conversation_lifecycle, changes)

    def mutate_conversations(self, mutations):
        return self._invoke(self._repository.mutate_conversations, mutations)

    def mutate_all_conversations(self, character_id, mutator):
        return self._invoke(
            self._repository.mutate_all_conversations, character_id, mutator
        )

    def add_message(self, role, content, character_id=None, **options):
        try:
            return self._repository.add_message(role, content, character_id, **options)
        except (PersistenceError, ValueError, TypeError) as exc:
            if isinstance(exc, PersistenceError):
                self._repository.last_error = str(exc)
            raise
        except Exception as exc:
            self._repository.last_error = f"{type(exc).__name__}: {exc}"
            raise PersistenceError(self._repository.last_error) from exc

    def update_stream_message(self, message_id, content, **options):
        return self._invoke(self._repository.update_stream_message, message_id, content, **options)

    def conversation_context(self, limit=12, max_chars=12000, character_id=None, conversation_id=None):
        return self._repository.conversation_context(limit, max_chars, character_id, conversation_id)

    def recent_messages(self, limit=12, character_id=None, conversation_id=None):
        return self._repository.recent_messages(limit, character_id, conversation_id)

    def recent_message_records(self, limit=2000, character_id=None):
        return self._invoke(self._repository.recent_message_records, limit, character_id)

    def get_messages(self, limit=1000, character_id=None, conversation_id=None, after_id=0):
        return self._invoke(self._repository.get_messages, limit, character_id, conversation_id, after_id)

    def messages_after(self, after_id=0, limit=500):
        return self._invoke(self._repository.messages_after, after_id, limit)

    def get_transfer_messages(self, conversation_id, character_id, after_created_at="", after_id=0, limit=1000):
        return self._invoke(self._repository.get_transfer_messages, conversation_id, character_id, after_created_at, after_id, limit)

    def message_id_for(self, role, content, character_id=None):
        return self._invoke(self._repository.message_id_for, role, content, character_id)

    def rows_with_ids(self, limit=3000, after_id=0, character_id=None):
        return self._invoke(self._repository.rows_with_ids, limit, after_id, character_id)

    def max_message_id(self):
        return self._invoke(self._repository.max_message_id)

    def message_count(self, character_id=None, conversation_id=None):
        return self._invoke(self._repository.message_count, character_id, conversation_id)

    def pending_count(self):
        return self._invoke(self._repository.pending_count)

    def list_snapshots(self, kind="cleared"):
        return self._invoke(self._repository.list_snapshots, kind)

    def clear_memory(self, character_id=None):
        try:
            return self._invoke(self._repository.clear_memory, character_id)
        except PersistenceError:
            raise
        except Exception as exc:
            raise PersistenceError(str(exc)) from exc

    def restore_last_cleared(self):
        try:
            return self._invoke(self._repository.restore_last_cleared)
        except PersistenceError:
            raise
        except Exception as exc:
            raise PersistenceError(str(exc)) from exc

    def import_messages(self, source):
        try:
            return self._invoke(self._repository.import_messages, source)
        except PersistenceError:
            raise
        except Exception as exc:
            raise PersistenceError(str(exc)) from exc

    def import_transfer_records(self, conversations, messages):
        return self._invoke(self._repository.import_transfer_records, conversations, messages)


def create_default_chat_persistence(db_path=None) -> ChatPersistence:
    return ChatPersistence(SqliteChatRepository(db_path=db_path))


# Backward-compatible default repository API used by kira.memory.
_DEFAULT_REPOSITORY = SqliteChatRepository(db_path=lambda: DB_PATH)
