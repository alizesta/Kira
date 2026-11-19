"""Consumer-facing contract for the shared companion mood state."""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any, ContextManager, Protocol


class MoodService(Protocol):
    """Complete provider-neutral and character-scoped Mood capability contract."""

    def current(
        self, now: float | None = None, query: str | None = None, *,
        character_id: str | None = None, traits: dict[str, Any] | None = None,
    ) -> dict[str, Any]: ...

    def build_block(
        self, mode_name: str = "chat", now: float | None = None, query: str | None = None, *,
        character_id: str | None = None, traits: dict[str, Any] | None = None,
    ) -> str: ...

    def detect_user_states(self, text: str) -> list[str]: ...

    def on_user_message(
        self, text: str, now: float | None = None, *,
        character_id: str | None = None, traits: dict[str, Any] | None = None,
    ) -> list[str]: ...

    def on_reply(
        self, emotions: Sequence[str] | None, intensity: float | None = None,
        now: float | None = None, text: str = "", *,
        character_id: str | None = None, traits: dict[str, Any] | None = None,
    ) -> None: ...

    def on_event(
        self, name: str, detail: Any = None, *,
        character_id: str | None = None, traits: dict[str, Any] | None = None,
    ) -> Any: ...

    def avatar_hint(
        self, now: float | None = None, *,
        character_id: str | None = None, traits: dict[str, Any] | None = None,
    ) -> tuple[str, int] | None: ...

    def set_active_character(self, character_id: str, traits: dict[str, Any] | None = None) -> str: ...

    def set_character_traits(
        self, character_id: str, traits: dict[str, Any] | None = None
    ) -> dict[str, Any]: ...

    def character_scope(
        self, character_id: str, traits: dict[str, Any] | None = None
    ) -> ContextManager[Any]: ...

    def mark_initiative_sent(
        self, memory_id: str | None = None, now: float | None = None, *,
        character_id: str | None = None, traits: dict[str, Any] | None = None,
    ) -> None: ...

    def reset(
        self, *, character_id: str | None = None, traits: dict[str, Any] | None = None
    ) -> None: ...
