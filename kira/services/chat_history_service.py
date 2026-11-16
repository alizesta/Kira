"""Application adapter for the existing SQLite chat-history store."""
from __future__ import annotations

from pathlib import Path

from .. import memory as chat_store
from ..core.exceptions import ChatHistoryError


class SqliteChatHistoryService:
    """Expose chat persistence through a stable UI-facing service contract."""

    @property
    def last_error(self) -> str | None:
        return chat_store.last_error

    def set_last_error(self, message: str | None) -> None:
        chat_store.last_error = str(message) if message else None

    def init_db(self) -> list[str]:
        return chat_store.init_db()

    def add_message(self, role: str, content: str, character_id: str | None = None) -> bool:
        return chat_store.add_message(role, content, character_id)

    def conversation_context(
        self,
        limit: int = 12,
        max_chars: int = 12000,
        character_id: str | None = None,
    ) -> list[dict[str, str]]:
        return chat_store.conversation_context(limit, max_chars, character_id)

    def recent_messages(
        self,
        limit: int = 12,
        character_id: str | None = None,
    ) -> list[dict[str, str]]:
        return chat_store.recent_messages(limit, character_id)

    def message_count(self, character_id: str | None = None) -> int:
        return chat_store.message_count(character_id)

    def clear_memory(self, character_id: str | None = None) -> None:
        try:
            chat_store.clear_memory(character_id)
        except chat_store.ChatStoreError as exc:
            raise ChatHistoryError(str(exc)) from exc

    def restore_last_cleared(self) -> int:
        try:
            return chat_store.restore_last_cleared()
        except chat_store.ChatStoreError as exc:
            raise ChatHistoryError(str(exc)) from exc

    def import_messages(self, source: str | Path) -> int:
        try:
            return chat_store.import_messages(source)
        except chat_store.ChatStoreError as exc:
            raise ChatHistoryError(str(exc)) from exc
