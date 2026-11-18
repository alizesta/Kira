"""Consumer-facing contract for character-scoped long-term memory."""
from __future__ import annotations

from typing import Any, Protocol


class MemoryService(Protocol):
    def list_items(self, character_id: str) -> list[dict[str, Any]]: ...

    def add_note(self, character_id: str, text: str) -> bool: ...

    def update_item(self, character_id: str, item_id: str, text: str) -> bool: ...

    def delete_item(self, character_id: str, item_id: str) -> bool: ...

    def forget_all(self, character_id: str) -> None: ...

    def forget_conversation(self, character_id: str) -> None: ...

    def observe(self, character_id: str, role: str, content: str) -> None: ...

    def build_block(
        self,
        character_id: str,
        older: list[dict[str, Any]] | None = None,
        *,
        voice_samples: bool = True,
        query: str | None = None,
        budget: int | None = None,
    ) -> str: ...

    def needs_summary(self, character_id: str, total: int, window: int) -> bool: ...

    def maintain(self, character_id: str, rows: list[dict[str, Any]], window: int) -> bool: ...
