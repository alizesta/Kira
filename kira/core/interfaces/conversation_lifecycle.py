"""Core-owned ports for Conversation lifecycle application orchestration."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol


class ConversationLifecycleRepositoryPort(Protocol):
    """Durable read/transaction boundary required by Conversation lifecycle."""

    def get_conversation(self, conversation_id: str) -> dict[str, Any] | None: ...

    def list_conversations(
        self, character_id: str | None = None
    ) -> list[dict[str, Any]]: ...

    def update_conversation_lifecycle(
        self, changes: Sequence[Mapping[str, Any]]
    ) -> bool: ...

    def delete_conversation(
        self, conversation_id: str, *, expected_status: str | None = None
    ) -> int: ...


class ConversationEventPublisherPort(Protocol):
    """Notification-only port; it must not be used for request/response calls."""

    def publish(
        self, event_type: Any, *, payload: Any = None, metadata: Any = None, **kwargs: Any
    ) -> Any: ...


class PermanentDeleteAuthorizationPort(Protocol):
    """Explicit authorization for permanent deletion of one exact Conversation."""

    def authorize_permanent_delete(self, conversation_id: str) -> bool: ...


__all__ = [
    "ConversationEventPublisherPort",
    "ConversationLifecycleRepositoryPort",
    "PermanentDeleteAuthorizationPort",
]
