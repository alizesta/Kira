"""Application service for character-isolated persona memory."""
from __future__ import annotations

from typing import Any

from .. import persona_memory


class PersonaMemoryService:
    """Wrap the legacy persona-memory store behind a character-explicit API."""

    def list_items(self, character_id: str, now: float | None = None) -> list[dict[str, Any]]:
        with persona_memory.character_scope(character_id):
            return persona_memory.list_items(now=now)

    def add_note(self, character_id: str, text: str) -> bool:
        with persona_memory.character_scope(character_id):
            return bool(persona_memory.add_note(text))

    def update_item(self, character_id: str, item_id: str, text: str) -> bool:
        with persona_memory.character_scope(character_id):
            return bool(persona_memory.update_item(item_id, text))

    def delete_item(self, character_id: str, item_id: str) -> bool:
        with persona_memory.character_scope(character_id):
            return bool(persona_memory.delete_item(item_id))

    def forget_all(self, character_id: str) -> None:
        with persona_memory.character_scope(character_id):
            persona_memory.forget_all()

    def forget_conversation(self, character_id: str) -> None:
        with persona_memory.character_scope(character_id):
            persona_memory.forget_conversation()

    def observe(self, character_id: str, role: str, content: str) -> None:
        with persona_memory.character_scope(character_id):
            persona_memory.observe(role, content)

    def build_block(
        self,
        character_id: str,
        older: list[dict[str, Any]] | None = None,
        *,
        voice_samples: bool = True,
        query: str | None = None,
        budget: int | None = None,
    ) -> str:
        with persona_memory.character_scope(character_id):
            return persona_memory.build_block(
                older,
                voice_samples=voice_samples,
                query=query,
                budget=budget,
            )

    def needs_summary(self, character_id: str, total: int, window: int) -> bool:
        with persona_memory.character_scope(character_id):
            return persona_memory.needs_summary(total, window)

    def maintain(self, character_id: str, rows: list[dict[str, Any]], window: int) -> bool:
        with persona_memory.character_scope(character_id):
            return persona_memory.maintain(rows, window)
