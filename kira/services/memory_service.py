"""Application service for character-isolated persona memory."""
from __future__ import annotations

from typing import Any

from .. import persona_memory


class PersonaMemoryService:
    """Wrap the legacy persona-memory store behind a character-explicit API."""

    def list_items(self, character_id: str) -> list[dict[str, Any]]:
        with persona_memory.character_scope(character_id):
            return persona_memory.list_items()

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
