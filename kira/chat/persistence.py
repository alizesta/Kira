"""Qt-free persistence boundary for chat history.

The application talks to ChatPersistence; storage engines are supplied through
ChatRepository. The legacy SQLite adapter is intentionally kept at the edge
until the on-disk schema can be migrated without losing existing user data.
"""
from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable


class PersistenceError(RuntimeError):
    """A persistence operation failed; callers may safely report this error."""


@runtime_checkable
class ChatRepository(Protocol):
    """Replaceable repository contract; no database-specific types escape it."""

    @property
    def last_error(self) -> str | None: ...

    @last_error.setter
    def last_error(self, value: str | None) -> None: ...

    def init_db(self) -> list[str]: ...
    def add_message(self, role: str, content: str, character_id: str | None = None) -> bool: ...
    def conversation_context(self, limit: int = 12, max_chars: int = 12000,
                             character_id: str | None = None) -> list[dict[str, str]]: ...
    def recent_messages(self, limit: int = 12,
                        character_id: str | None = None) -> list[dict[str, str]]: ...
    def message_count(self, character_id: str | None = None) -> int: ...
    def clear_memory(self, character_id: str | None = None) -> None: ...
    def restore_last_cleared(self) -> int: ...
    def import_messages(self, source: str | Path) -> int: ...


class ChatPersistence:
    """Application-facing persistence API shared by every character/session.

    Character scoping is data metadata, not a dependency on character objects.
    The repository owns ordering, timestamps, transactions, recovery and the
    durable representation.
    """

    def __init__(self, repository: ChatRepository):
        if repository is None:
            raise TypeError("repository is required")
        self._repository = repository

    @property
    def last_error(self) -> str | None:
        return self._repository.last_error

    def set_last_error(self, message: str | None) -> None:
        self._repository.last_error = str(message) if message else None

    def init_db(self) -> list[str]:
        return self._repository.init_db()

    def add_message(self, role: str, content: str, character_id: str | None = None) -> bool:
        return self._repository.add_message(role, content, character_id)

    def conversation_context(self, limit: int = 12, max_chars: int = 12000,
                             character_id: str | None = None) -> list[dict[str, str]]:
        return self._repository.conversation_context(limit, max_chars, character_id)

    def recent_messages(self, limit: int = 12,
                        character_id: str | None = None) -> list[dict[str, str]]:
        return self._repository.recent_messages(limit, character_id)

    def message_count(self, character_id: str | None = None) -> int:
        return self._repository.message_count(character_id)

    def clear_memory(self, character_id: str | None = None) -> None:
        try:
            self._repository.clear_memory(character_id)
        except Exception as exc:
            raise PersistenceError(str(exc)) from exc

    def restore_last_cleared(self) -> int:
        try:
            return self._repository.restore_last_cleared()
        except Exception as exc:
            raise PersistenceError(str(exc)) from exc

    def import_messages(self, source: str | Path) -> int:
        try:
            return self._repository.import_messages(source)
        except Exception as exc:
            raise PersistenceError(str(exc)) from exc


class LegacyMemoryRepository:
    """Compatibility adapter over Kira's established, data-preserving chat store.

    This adapter deliberately preserves the current SQLite file, schema,
    snapshots, corruption quarantine, pending-write recovery and import rules.
    It is the only persistence module component that knows the legacy store API.
    """

    def __init__(self, store=None):
        if store is None:
            from .. import memory as store
        self._store = store

    @property
    def last_error(self) -> str | None:
        return self._store.last_error

    @last_error.setter
    def last_error(self, value: str | None) -> None:
        self._store.last_error = value

    def init_db(self) -> list[str]:
        return self._store.init_db()

    def add_message(self, role: str, content: str, character_id: str | None = None) -> bool:
        return self._store.add_message(role, content, character_id)

    def conversation_context(self, limit: int = 12, max_chars: int = 12000,
                             character_id: str | None = None) -> list[dict[str, str]]:
        return self._store.conversation_context(limit, max_chars, character_id)

    def recent_messages(self, limit: int = 12,
                        character_id: str | None = None) -> list[dict[str, str]]:
        return self._store.recent_messages(limit, character_id)

    def message_count(self, character_id: str | None = None) -> int:
        return self._store.message_count(character_id)

    def clear_memory(self, character_id: str | None = None) -> None:
        self._store.clear_memory(character_id)

    def restore_last_cleared(self) -> int:
        return self._store.restore_last_cleared()

    def import_messages(self, source: str | Path) -> int:
        return self._store.import_messages(source)


def create_default_chat_persistence(store=None) -> ChatPersistence:
    """Compose the compatibility repository; callers may inject a different store."""
    return ChatPersistence(LegacyMemoryRepository(store))
