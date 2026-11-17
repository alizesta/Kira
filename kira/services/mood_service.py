"""Application service adapter for the shared companion mood state."""
from __future__ import annotations

from typing import Any

from .. import mood


class MoodStateService:
    def current(self) -> dict[str, Any]:
        return mood.current()

    def reset(self) -> None:
        mood.reset()

    def set_active_character(self, character_id: str, traits: dict[str, Any] | None = None) -> None:
        mood.set_active_character(character_id, traits or {})
