"""Pure Conversation domain rules and value contracts.

No persistence, event transport, application orchestration, or UI dependency is
allowed in this package. Adapters translate these rules to stored records.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping


class ConversationStatus(str, Enum):
    ACTIVE = "active"
    ARCHIVED = "archived"
    TRASHED = "trashed"
    CLOSED = "closed"  # Legacy durable status; not a runtime Session state.


class ConversationOperation(str, Enum):
    ARCHIVE = "archive"
    RESTORE = "restore"
    TRASH = "trash"
    RESTORE_TRASHED = "restore_trashed"
    PERMANENT_DELETE = "permanent_delete"


class ConversationLifecycleError(RuntimeError):
    """A lifecycle operation could not be completed safely."""

    error_code = "conversation_lifecycle_error"


class ConversationNotFound(ConversationLifecycleError):
    """The requested durable conversation does not exist."""

    error_code = "conversation_not_found"


class InvalidConversationTransition(ConversationLifecycleError):
    """The requested transition is not legal from the current state."""

    error_code = "invalid_conversation_transition"


class PermanentDeleteAuthorizationError(ConversationLifecycleError):
    """Permanent deletion was not explicitly authorized."""

    error_code = "permanent_delete_not_authorized"


@dataclass(frozen=True, slots=True)
class ConversationLifecycleResult:
    conversation_id: str
    previous_status: str
    new_status: str
    changed_at: str
    operation: ConversationOperation
    success: bool
    event_published: bool = False
    details: Mapping[str, Any] | None = None


_ALLOWED_SOURCES: Mapping[ConversationOperation, tuple[ConversationStatus, ...]] = {
    ConversationOperation.ARCHIVE: (ConversationStatus.ACTIVE,),
    ConversationOperation.RESTORE: (ConversationStatus.ARCHIVED,),
    ConversationOperation.TRASH: (
        ConversationStatus.ACTIVE,
        ConversationStatus.ARCHIVED,
        ConversationStatus.CLOSED,
    ),
    ConversationOperation.RESTORE_TRASHED: (ConversationStatus.TRASHED,),
    ConversationOperation.PERMANENT_DELETE: (ConversationStatus.TRASHED,),
}


def allowed_source_statuses(
    operation: ConversationOperation,
) -> tuple[ConversationStatus, ...]:
    """Return the only durable states from which an operation is permitted."""
    try:
        return _ALLOWED_SOURCES[operation]
    except KeyError as exc:
        raise ValueError(f"unsupported conversation operation: {operation!r}") from exc


def is_transition_allowed(
    current: ConversationStatus,
    operation: ConversationOperation,
) -> bool:
    """Evaluate a lifecycle transition without consulting storage or UI state."""
    return current in allowed_source_statuses(operation)


__all__ = [
    "ConversationLifecycleError",
    "ConversationLifecycleResult",
    "ConversationNotFound",
    "ConversationOperation",
    "ConversationStatus",
    "InvalidConversationTransition",
    "PermanentDeleteAuthorizationError",
    "allowed_source_statuses",
    "is_transition_allowed",
]
