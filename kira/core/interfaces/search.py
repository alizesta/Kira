"""Core-owned read ports for chat search and retrieval."""
from __future__ import annotations

from typing import Any, Protocol


class ChatSearchRepositoryPort(Protocol):
    """Read-only message page source; persistence writes are outside Search."""

    def messages_after(
        self, after_id: int = 0, limit: int = 500
    ) -> list[dict[str, Any]]:
        """Return a page ordered by monotonically increasing message ID."""
        ...


class ConversationStatusReaderPort(Protocol):
    """Optional read capability for filtering messages by durable Conversation state."""

    def list_conversations(
        self, character_id: str | None = None
    ) -> list[dict[str, Any]]:
        ...


__all__ = [
    "ChatSearchRepositoryPort",
    "ConversationStatusReaderPort",
]
