"""History and durable conversation operations for ChatApplicationService."""
from __future__ import annotations

from typing import Any


class ChatHistoryFacade:
    """Expose character-scoped history and conversation operations."""

    def __init__(self, persistence: Any, conversation_lifecycle: Any | None = None) -> None:
        if persistence is None:
            raise TypeError("persistence is required")
        self._persistence = persistence
        self._conversation_lifecycle = conversation_lifecycle

    @property
    def last_persistence_error(self) -> str | None:
        return getattr(self._persistence, "last_error", None)

    def set_persistence_error(self, message: str | None) -> None:
        setter = getattr(self._persistence, "set_last_error", None)
        if callable(setter):
            setter(message)

    def init_history(self) -> list[str]:
        initializer = getattr(self._persistence, "init_db", None)
        return list(initializer() or []) if callable(initializer) else []

    def get_or_create_conversation(self, character_id: str) -> dict[str, Any]:
        owner = str(character_id or "").strip()
        if not owner:
            raise ValueError("character_id must not be empty")
        return self._persistence.get_or_create_conversation(owner)

    def create_conversation(
        self, character_id: str, title: str = "", metadata: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        owner = str(character_id or "").strip()
        if not owner:
            raise ValueError("character_id must not be empty")
        creator = getattr(self._persistence, "create_conversation", None)
        if not callable(creator):
            raise RuntimeError("Chat persistence does not support creating conversations")
        return creator(owner, title, metadata)

    def list_conversations(self, character_id: str | None = None, *, statuses=None):
        lifecycle = self._require_conversation_lifecycle()
        options = {} if statuses is None else {"statuses": statuses}
        return lifecycle.list_conversations(character_id=character_id, **options)

    def archive_conversation(self, conversation_id: str):
        return self._require_conversation_lifecycle().archive(conversation_id)

    def archive_conversations(self, conversation_ids):
        return self._require_conversation_lifecycle().archive_many(conversation_ids)

    def restore_conversation(self, conversation_id: str):
        return self._require_conversation_lifecycle().restore(conversation_id)

    def trash_conversation(self, conversation_id: str):
        return self._require_conversation_lifecycle().trash(conversation_id)

    def trash_conversations(self, conversation_ids):
        return self._require_conversation_lifecycle().trash_many(conversation_ids)

    def restore_trashed_conversation(self, conversation_id: str):
        return self._require_conversation_lifecycle().restore_trashed(conversation_id)

    def permanently_delete_conversation(self, conversation_id: str, *, authorization):
        return self._require_conversation_lifecycle().permanent_delete(
            conversation_id, authorization=authorization
        )

    def _require_conversation_lifecycle(self):
        if self._conversation_lifecycle is None:
            raise RuntimeError("Conversation Lifecycle service is not configured")
        return self._conversation_lifecycle

    def recent_messages(
        self, limit: int = 12, character_id: str | None = None,
        conversation_id: str | None = None,
    ):
        return self._persistence.recent_messages(limit, character_id, conversation_id)

    def recent_message_records(
        self, limit: int = 2000, character_id: str | None = None
    ):
        return self._persistence.recent_message_records(limit, character_id)

    def conversation_context(
        self, limit: int = 12, max_chars: int = 12000,
        character_id: str | None = None, conversation_id: str | None = None,
        *, session_id: str | None = None,
    ):
        owner = character_id if character_id is not None else session_id
        return self._persistence.conversation_context(
            limit, max_chars, owner, conversation_id
        )

    def message_count(
        self, character_id: str | None = None, conversation_id: str | None = None
    ) -> int:
        return self._persistence.message_count(character_id, conversation_id)

    def clear_history(self, character_id: str | None = None) -> Any:
        return self._persistence.clear_memory(character_id)

    def restore_history(self) -> int:
        return self._persistence.restore_last_cleared()

    def import_history(self, source: Any) -> int:
        return self._persistence.import_messages(source)
