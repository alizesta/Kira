"""Application adapter for the replaceable chat-persistence boundary."""
from __future__ import annotations

from pathlib import Path

from .. import memory as chat_store
from ..chat.persistence import PersistenceError, create_default_chat_persistence
from ..core.exceptions import ChatHistoryError


class SqliteChatHistoryService:
    """Backward-compatible application service backed by the legacy SQLite repository."""

    def __init__(self, repository=None):
        self._persistence = (
            repository if repository is not None
            else create_default_chat_persistence(chat_store)
        )

    @property
    def last_error(self) -> str | None:
        return self._persistence.last_error

    def set_last_error(self, message: str | None) -> None:
        self._persistence.set_last_error(message)

    def init_db(self) -> list[str]:
        return self._persistence.init_db()

    def add_message(self, role: str, content: str, character_id: str | None = None) -> bool:
        return self._persistence.add_message(role, content, character_id)

    def conversation_context(
        self, limit: int = 12, max_chars: int = 12000, character_id: str | None = None
    ) -> list[dict[str, str]]:
        return self._persistence.conversation_context(limit, max_chars, character_id)

    def recent_messages(
        self, limit: int = 12, character_id: str | None = None
    ) -> list[dict[str, str]]:
        return self._persistence.recent_messages(limit, character_id)

    def message_count(self, character_id: str | None = None) -> int:
        return self._persistence.message_count(character_id)

    def clear_memory(self, character_id: str | None = None) -> None:
        try:
            self._persistence.clear_memory(character_id)
        except PersistenceError as exc:
            raise ChatHistoryError(str(exc)) from exc

    def restore_last_cleared(self) -> int:
        try:
            return self._persistence.restore_last_cleared()
        except PersistenceError as exc:
            raise ChatHistoryError(str(exc)) from exc

    def import_messages(self, source: str | Path) -> int:
        try:
            return self._persistence.import_messages(source)
        except PersistenceError as exc:
            raise ChatHistoryError(str(exc)) from exc
