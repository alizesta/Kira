"""Application boundary for the shared, character-scoped companion mood state.

This is the only production adapter allowed to import the legacy kira.mood
module. Consumers use the injected MoodStateService contract instead.
"""
from __future__ import annotations

from contextlib import AbstractContextManager
from typing import Any, Sequence

from .. import mood


class MoodStateService:
    """Expose the complete Mood API behind one injectable application service."""

    def current(self, now: float | None = None, query: str | None = None) -> dict[str, Any]:
        return mood.current(now=now, query=query)

    def build_block(
        self, mode_name: str = "chat", now: float | None = None, query: str | None = None
    ) -> str:
        return mood.build_block(mode_name=mode_name, now=now, query=query)

    def detect_user_states(self, text: str) -> list[str]:
        return mood.detect_user_states(text)

    def on_user_message(self, text: str, now: float | None = None) -> list[str]:
        return mood.on_user_message(text, now=now)

    def on_reply(
        self,
        emotions: Sequence[str] | None,
        intensity: float | None = None,
        now: float | None = None,
        text: str = "",
    ) -> None:
        mood.on_reply(emotions, intensity=intensity, now=now, text=text)

    def on_event(self, name: str, detail: Any = None) -> Any:
        return mood.on_event(name, detail)

    def avatar_hint(self, now: float | None = None) -> tuple[str, int] | None:
        return mood.avatar_hint(now=now)

    def set_active_character(self, character_id: str, traits: dict[str, Any] | None = None) -> str:
        return mood.set_active_character(character_id, traits)

    def set_character_traits(self, character_id: str, traits: dict[str, Any] | None = None) -> dict[str, Any]:
        return mood.set_character_traits(character_id, traits)

    def character_scope(
        self, character_id: str, traits: dict[str, Any] | None = None
    ) -> AbstractContextManager[Any]:
        return mood.character_scope(character_id, traits)

    def mark_initiative_sent(self, memory_id: str | None = None, now: float | None = None) -> None:
        mood.mark_initiative_sent(memory_id=memory_id, now=now)

    def reset(self) -> None:
        mood.reset()
