"""Consumer-facing contract for persisted chat history."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol


class ChatHistoryService(Protocol):
    @property
    def last_error(self) -> str | None: ...

    def set_last_error(self, message: str | None) -> None: ...

    def init_db(self) -> list[str]: ...

    def add_message(self, role: str, content: str, character_id: str | None = None) -> bool: ...

    def conversation_context(
        self,
        limit: int = 12,
        max_chars: int = 12000,
        character_id: str | None = None,
    ) -> list[dict[str, str]]: ...

    def recent_messages(
        self,
        limit: int = 12,
        character_id: str | None = None,
    ) -> list[dict[str, str]]: ...

    def message_count(self, character_id: str | None = None) -> int: ...

    def clear_memory(self, character_id: str | None = None) -> None: ...

    def restore_last_cleared(self) -> int: ...

    def import_messages(self, source: str | Path) -> int: ...
