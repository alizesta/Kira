"""Application boundary for the shared, character-scoped companion mood state.

This is the only production adapter allowed to import the legacy kira.mood
module. Consumers use the injected MoodStateService contract instead.
"""
from __future__ import annotations

from contextlib import AbstractContextManager
from typing import Any, Callable, Sequence, TypeVar

from .. import mood

_Result = TypeVar("_Result")


class MoodStateService:
    """Expose the complete Mood API behind one injectable application service.

    Every stateful operation accepts an optional character_id. When supplied,
    the operation is executed inside Mood's ContextVar-backed character scope,
    so background Sessions cannot mutate or read the visible character's state.
    """

    def _for_character(
        self,
        character_id: str | None,
        traits: dict[str, Any] | None,
        operation: Callable[[], _Result],
    ) -> _Result:
        if not character_id:
            return operation()
        with self.character_scope(character_id, traits):
            return operation()

    def current(
        self, now: float | None = None, query: str | None = None, *,
        character_id: str | None = None, traits: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._for_character(
            character_id, traits, lambda: mood.current(now=now, query=query)
        )

    def build_block(
        self, mode_name: str = "chat", now: float | None = None, query: str | None = None, *,
        character_id: str | None = None, traits: dict[str, Any] | None = None,
    ) -> str:
        return self._for_character(
            character_id, traits,
            lambda: mood.build_block(mode_name=mode_name, now=now, query=query),
        )

    def detect_user_states(self, text: str) -> list[str]:
        return mood.detect_user_states(text)

    def on_user_message(
        self, text: str, now: float | None = None, *,
        character_id: str | None = None, traits: dict[str, Any] | None = None,
    ) -> list[str]:
        return self._for_character(
            character_id, traits, lambda: mood.on_user_message(text, now=now)
        )

    def on_reply(
        self,
        emotions: Sequence[str] | None,
        intensity: float | None = None,
        now: float | None = None,
        text: str = "",
        *,
        character_id: str | None = None,
        traits: dict[str, Any] | None = None,
    ) -> None:
        self._for_character(
            character_id, traits,
            lambda: mood.on_reply(emotions, intensity=intensity, now=now, text=text),
        )

    def on_model_user_states(
        self, states: Sequence[str] | None, now: float | None = None, *,
        character_id: str | None = None, traits: dict[str, Any] | None = None,
    ) -> list[str]:
        return self._for_character(
            character_id, traits, lambda: mood.on_model_user_states(states, now=now)
        )

    def on_event(
        self, name: str, detail: Any = None, *,
        character_id: str | None = None, traits: dict[str, Any] | None = None,
    ) -> Any:
        return self._for_character(
            character_id, traits, lambda: mood.on_event(name, detail)
        )

    def avatar_hint(
        self, now: float | None = None, *,
        character_id: str | None = None, traits: dict[str, Any] | None = None,
    ) -> tuple[str, int] | None:
        return self._for_character(
            character_id, traits, lambda: mood.avatar_hint(now=now)
        )

    def set_active_character(self, character_id: str, traits: dict[str, Any] | None = None) -> str:
        return mood.set_active_character(character_id, traits)

    def set_character_traits(
        self, character_id: str, traits: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        return mood.set_character_traits(character_id, traits)

    def character_scope(
        self, character_id: str, traits: dict[str, Any] | None = None
    ) -> AbstractContextManager[Any]:
        return mood.character_scope(character_id, traits)

    def mark_initiative_sent(
        self, memory_id: str | None = None, now: float | None = None, *,
        character_id: str | None = None, traits: dict[str, Any] | None = None,
    ) -> None:
        self._for_character(
            character_id, traits,
            lambda: mood.mark_initiative_sent(memory_id=memory_id, now=now),
        )

    def reset(
        self, *, character_id: str | None = None, traits: dict[str, Any] | None = None
    ) -> None:
        self._for_character(character_id, traits, mood.reset)
