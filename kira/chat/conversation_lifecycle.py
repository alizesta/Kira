"""Application orchestration for durable Conversation lifecycle operations.

Domain transition rules live in kira.domain; repository and notification
implementations are supplied through Core-owned ports. This module coordinates
atomic persistence and post-commit notifications.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from ..core.interfaces.conversation_lifecycle import (
    ConversationEventPublisherPort,
    ConversationLifecycleRepositoryPort,
    PermanentDeleteAuthorizationPort,
)
from ..domain.conversations import (
    ConversationLifecycleError,
    ConversationLifecycleResult,
    ConversationNotFound,
    ConversationOperation,
    ConversationStatus,
    InvalidConversationTransition,
    PermanentDeleteAuthorizationError,
    allowed_source_statuses,
)

# Backward-compatible names for callers that imported ports from this module.
PermanentDeleteAuthorization = PermanentDeleteAuthorizationPort
ConversationLifecycleRepository = ConversationLifecycleRepositoryPort
ConversationEventPublisher = ConversationEventPublisherPort


class ConversationLifecycleService:
    """Coordinate domain transitions, durable writes and post-commit events.

    Lifecycle timestamps live in the existing conversation metadata JSON field;
    no second database, table or message store is introduced. Group transitions
    use the repository's single atomic batch operation.
    """

    _STATUS_EVENTS = {
        ConversationOperation.ARCHIVE: "conversation_archived",
        ConversationOperation.RESTORE: "conversation_restored",
        ConversationOperation.TRASH: "conversation_trashed",
        ConversationOperation.RESTORE_TRASHED: "conversation_restored_from_trash",
        ConversationOperation.PERMANENT_DELETE: "conversation_permanently_deleted",
    }

    def __init__(
        self,
        repository: ConversationLifecycleRepositoryPort,
        event_publisher: ConversationEventPublisherPort,
        *,
        clock=None,
    ) -> None:
        if repository is None:
            raise TypeError("repository is required")
        if event_publisher is None or not callable(getattr(event_publisher, "publish", None)):
            raise TypeError("the shared ChatEventPublisher is required")
        for method in (
            "get_conversation",
            "list_conversations",
            "update_conversation_lifecycle",
            "delete_conversation",
        ):
            if not callable(getattr(repository, method, None)):
                raise TypeError(f"repository must implement {method}()")
        self._repository = repository
        self._events = event_publisher
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def _now(self) -> str:
        value = self._clock()
        if not isinstance(value, datetime):
            raise TypeError("clock must return a datetime")
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("clock must return a timezone-aware datetime")
        return value.astimezone(timezone.utc).isoformat()

    @staticmethod
    def _metadata(conversation: Mapping[str, Any]) -> dict[str, Any]:
        raw = conversation.get("metadata")
        metadata = dict(raw) if isinstance(raw, Mapping) else {}
        lifecycle = metadata.get("_conversation_lifecycle")
        metadata["_conversation_lifecycle"] = (
            dict(lifecycle) if isinstance(lifecycle, Mapping) else {}
        )
        return metadata

    def list_conversations(
        self,
        *,
        character_id: str | None = None,
        statuses: Sequence[ConversationStatus | str] = (ConversationStatus.ACTIVE,),
    ) -> list[dict[str, Any]]:
        wanted = {self._status(item).value for item in statuses}
        if not wanted:
            return []
        return [
            row
            for row in self._repository.list_conversations(character_id)
            if str(row.get("status") or ConversationStatus.ACTIVE.value) in wanted
        ]

    @staticmethod
    def _status(value: ConversationStatus | str) -> ConversationStatus:
        try:
            return value if isinstance(value, ConversationStatus) else ConversationStatus(str(value))
        except ValueError as exc:
            raise ValueError(f"unsupported conversation status: {value!r}") from exc

    def archive(self, conversation_id: str) -> ConversationLifecycleResult:
        return self._transition(conversation_id, ConversationOperation.ARCHIVE)

    def restore(self, conversation_id: str) -> ConversationLifecycleResult:
        return self._transition(conversation_id, ConversationOperation.RESTORE)

    def trash(self, conversation_id: str) -> ConversationLifecycleResult:
        return self._transition(conversation_id, ConversationOperation.TRASH)

    def restore_trashed(self, conversation_id: str) -> ConversationLifecycleResult:
        return self._transition(conversation_id, ConversationOperation.RESTORE_TRASHED)

    def archive_many(
        self, conversation_ids: Sequence[str]
    ) -> tuple[ConversationLifecycleResult, ...]:
        return self._transition_many(conversation_ids, ConversationOperation.ARCHIVE)

    def trash_many(
        self, conversation_ids: Sequence[str]
    ) -> tuple[ConversationLifecycleResult, ...]:
        return self._transition_many(conversation_ids, ConversationOperation.TRASH)

    def _transition(
        self, conversation_id: str, operation: ConversationOperation
    ) -> ConversationLifecycleResult:
        return self._transition_many((conversation_id,), operation)[0]

    def _transition_many(
        self,
        conversation_ids: Sequence[str],
        operation: ConversationOperation,
    ) -> tuple[ConversationLifecycleResult, ...]:
        ids = tuple(dict.fromkeys(str(value).strip() for value in conversation_ids))
        if not ids or any(not value for value in ids):
            raise ValueError("at least one non-empty conversation ID is required")

        now = self._now()
        target, timestamp_key = {
            ConversationOperation.ARCHIVE: (ConversationStatus.ARCHIVED, "archived_at"),
            ConversationOperation.RESTORE: (ConversationStatus.ACTIVE, "restored_at"),
            ConversationOperation.TRASH: (ConversationStatus.TRASHED, "deleted_at"),
            ConversationOperation.RESTORE_TRASHED: (
                ConversationStatus.ACTIVE,
                "restored_from_trash_at",
            ),
        }[operation]
        allowed = allowed_source_statuses(operation)

        records = []
        for conv_id in ids:
            row = self._repository.get_conversation(conv_id)
            if row is None or str(row.get("id") or "") != conv_id:
                raise ConversationNotFound(f"conversation not found: {conv_id}")
            previous = self._status(
                str(row.get("status") or ConversationStatus.ACTIVE.value)
            )
            if previous not in allowed:
                raise InvalidConversationTransition(
                    f"cannot {operation.value} conversation {conv_id} from {previous.value}"
                )
            metadata = self._metadata(row)
            lifecycle = metadata["_conversation_lifecycle"]
            lifecycle[timestamp_key] = now
            lifecycle["last_operation"] = operation.value
            lifecycle["changed_at"] = now
            records.append({
                "id": conv_id,
                "status": target.value,
                "metadata": metadata,
                "previous_status": previous.value,
            })

        # One repository transaction prevents partially-applied group operations.
        if not self._repository.update_conversation_lifecycle(records):
            raise ConversationLifecycleError("repository rejected the lifecycle batch")

        results = []
        for record in records:
            event_published = self._publish(
                operation, record["id"], record["previous_status"], target.value, now
            )
            results.append(ConversationLifecycleResult(
                conversation_id=record["id"],
                previous_status=record["previous_status"],
                new_status=target.value,
                changed_at=now,
                operation=operation,
                success=True,
                event_published=event_published,
            ))
        return tuple(results)

    def permanent_delete(
        self,
        conversation_id: str,
        *,
        authorization: PermanentDeleteAuthorizationPort,
    ) -> ConversationLifecycleResult:
        conv_id = str(conversation_id or "").strip()
        if not conv_id:
            raise ValueError("conversation_id is required")
        if authorization is None or not callable(
            getattr(authorization, "authorize_permanent_delete", None)
        ):
            raise PermanentDeleteAuthorizationError(
                "explicit authorization provider is required"
            )
        row = self._repository.get_conversation(conv_id)
        if row is None or str(row.get("id") or "") != conv_id:
            raise ConversationNotFound(f"conversation not found: {conv_id}")
        previous = self._status(
            str(row.get("status") or ConversationStatus.ACTIVE.value)
        )
        if previous not in allowed_source_statuses(ConversationOperation.PERMANENT_DELETE):
            raise InvalidConversationTransition(
                "permanent deletion requires a trashed conversation"
            )
        if authorization.authorize_permanent_delete(conv_id) is not True:
            raise PermanentDeleteAuthorizationError(
                "permanent deletion was not explicitly authorized"
            )

        now = self._now()
        # Persistence owns the safety snapshot and deletes only rows with this conversation_id.
        self._repository.delete_conversation(
            conv_id, expected_status=ConversationStatus.TRASHED.value
        )
        if self._repository.get_conversation(conv_id) is not None:
            raise ConversationLifecycleError(
                "repository did not remove the requested conversation"
            )
        published = self._publish(
            ConversationOperation.PERMANENT_DELETE,
            conv_id,
            previous.value,
            "deleted",
            now,
        )
        return ConversationLifecycleResult(
            conversation_id=conv_id,
            previous_status=previous.value,
            new_status="deleted",
            changed_at=now,
            operation=ConversationOperation.PERMANENT_DELETE,
            success=True,
            event_published=published,
        )

    def _publish(
        self,
        operation: ConversationOperation,
        conversation_id: str,
        previous_status: str,
        new_status: str,
        changed_at: str,
    ) -> bool:
        try:
            from .events import ChatEventType

            event_type = ChatEventType(self._STATUS_EVENTS[operation])
            result = self._events.publish(
                event_type,
                payload={
                    "conversation_id": conversation_id,
                    "previous_status": previous_status,
                    "new_status": new_status,
                    "changed_at": changed_at,
                    "operation": operation.value,
                },
            )
            return not bool(getattr(result, "duplicate", False))
        except Exception:
            # Persistence has already committed; notification failure must not
            # misreport the durable transition as rolled back.
            return False


__all__ = [
    "ConversationEventPublisher",
    "ConversationLifecycleError",
    "ConversationLifecycleRepository",
    "ConversationLifecycleResult",
    "ConversationLifecycleService",
    "ConversationNotFound",
    "ConversationOperation",
    "ConversationStatus",
    "InvalidConversationTransition",
    "PermanentDeleteAuthorization",
    "PermanentDeleteAuthorizationError",
]
