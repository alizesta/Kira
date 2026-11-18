"""Core-owned ports for conversation organization use cases."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol


class ConversationOrganizationRepositoryPort(Protocol):
    """Atomic conversation metadata access supplied by Persistence."""

    def get_conversation(self, conversation_id: str) -> dict[str, Any] | None: ...

    def list_conversations(
        self, character_id: str | None = None
    ) -> list[dict[str, Any]]: ...

    def mutate_conversations(
        self,
        mutations: list[
            tuple[str, Callable[[dict[str, Any]], dict[str, Any]]]
        ],
    ) -> dict[str, dict[str, Any]]: ...

    def mutate_all_conversations(
        self,
        character_id: str | None,
        mutator: Callable[[dict[str, Any]], dict[str, Any]],
    ) -> dict[str, dict[str, Any]]: ...


class ConversationMetadataEventPublisherPort(Protocol):
    """Notification-only publisher for committed organization metadata changes."""

    def publish(self, event_type: Any, *, payload: Any = None, **kwargs: Any) -> Any: ...


__all__ = [
    "ConversationMetadataEventPublisherPort",
    "ConversationOrganizationRepositoryPort",
]
