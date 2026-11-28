"""Application adapter for the replaceable chat-persistence boundary."""
from __future__ import annotations

from pathlib import Path

from .. import memory as chat_store
from ..chat.persistence import ChatPersistence, ChatRepository, PersistenceError
from ..core.exceptions import ChatHistoryError


class SqliteChatHistoryService:
    """Backward-compatible application service backed by the extracted repository."""

    def __init__(self, repository: ChatRepository | ChatPersistence | None = None):
        if isinstance(repository, ChatPersistence):
            self._persistence = repository
        elif repository is not None:
            self._persistence = ChatPersistence(repository)
        else:
            # One shared repository instance preserves the in-process pending-write queue.
            self._persistence = chat_store.chat_persistence

    @property
    def last_error(self) -> str | None:
        chat_store.last_error = self._persistence.last_error
        return self._persistence.last_error

    def set_last_error(self, message: str | None) -> None:
        self._persistence.set_last_error(message)
        chat_store.last_error = self._persistence.last_error

    def init_db(self) -> list[str]:
        return self._persistence.init_db()

    def start(self) -> list[str]:
        """Initialize durable storage before dependent application features start."""
        return self.init_db()

    def flush_pending(self) -> int:
        """Flush both the in-memory cache and the durable emergency queue."""
        flush = getattr(self._persistence, "flush_pending", None)
        return int(flush() or 0) if callable(flush) else 0

    def stop(self) -> int:
        """Flush queued writes before the persistence module is released."""
        return self.flush_pending()

    def add_message(self, role: str, content: str, character_id: str | None = None, **options) -> bool:
        return self._persistence.add_message(role, content, character_id, **options)

    def conversation_context(
        self, limit: int = 12, max_chars: int = 12000, character_id: str | None = None,
        conversation_id: str | None = None
    ) -> list[dict[str, str]]:
        return self._persistence.conversation_context(limit, max_chars, character_id, conversation_id)

    def recent_messages(
        self, limit: int = 12, character_id: str | None = None, conversation_id: str | None = None
    ) -> list[dict[str, str]]:
        return self._persistence.recent_messages(limit, character_id, conversation_id)

    def recent_message_records(
        self, limit: int = 2000, character_id: str | None = None, conversation_id: str | None = None
    ):
        """Expose bounded durable message metadata for recovery and timestamped history rendering."""
        return self._persistence.recent_message_records(limit, character_id, conversation_id)

    def get_messages(self, limit=1000, character_id=None, conversation_id=None, after_id=0):
        return self._persistence.get_messages(limit, character_id, conversation_id, after_id)

    def create_conversation(self, character_id=None, title="", metadata=None, conversation_id=None):
        return self._persistence.create_conversation(character_id, title, metadata, conversation_id)

    def get_or_create_conversation(self, character_id=None):
        return self._persistence.get_or_create_conversation(character_id)

    def get_conversation(self, conversation_id):
        return self._persistence.get_conversation(conversation_id)

    def list_conversations(self, character_id=None):
        return self._persistence.list_conversations(character_id)

    def update_conversation(self, conversation_id, **changes):
        return self._persistence.update_conversation(conversation_id, **changes)

    def close_conversation(self, conversation_id):
        return self._persistence.close_conversation(conversation_id)

    def delete_conversation(self, conversation_id, *, expected_status: str | None = None):
        return self._persistence.delete_conversation(
            conversation_id, expected_status=expected_status
        )

    def update_conversation_lifecycle(self, changes):
        return self._persistence.update_conversation_lifecycle(changes)

    def update_stream_message(self, message_id, content, **options):
        return self._persistence.update_stream_message(message_id, content, **options)

    def mutate_conversations(self, mutations):
        """Expose atomic per-conversation metadata mutations to application use cases."""
        return self._persistence.mutate_conversations(mutations)

    def mutate_all_conversations(self, character_id, mutator):
        """Expose atomic character-scoped metadata mutations to application use cases."""
        return self._persistence.mutate_all_conversations(character_id, mutator)

    def messages_after(self, after_id=0, limit=500):
        """Read a stable, monotonically ordered page for Chat Search."""
        return self._persistence.messages_after(after_id, limit)

    def get_transfer_messages(
        self, conversation_id, character_id, after_created_at="", after_id=0, limit=1000
    ):
        """Read a bounded Conversation page for export without exposing SQL."""
        return self._persistence.get_transfer_messages(
            conversation_id, character_id, after_created_at, after_id, limit
        )

    def import_transfer_records(self, conversations, messages):
        """Commit a previously validated transfer through Persistence's atomic transaction."""
        return self._persistence.import_transfer_records(conversations, messages)

    def message_count(self, character_id: str | None = None, conversation_id: str | None = None) -> int:
        return self._persistence.message_count(character_id, conversation_id)

    def clear_memory(self, character_id: str | None = None) -> None:
        try:
            self._persistence.clear_memory(character_id)
        except PersistenceError as exc:
            raise ChatHistoryError(str(exc)) from exc

    def restore_last_cleared(self) -> int:
        try:
            return self._persistence.restore_last_cleared()
        except PersistenceError as exc:
            raise ChatHistoryError(str(exc)) from exc

    def import_messages(self, source: str | Path) -> int:
        try:
            return self._persistence.import_messages(source)
        except PersistenceError as exc:
            raise ChatHistoryError(str(exc)) from exc
