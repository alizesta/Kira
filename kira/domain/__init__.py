"""Pure business rules and value contracts for Kira's domain layer."""

from .conversations import (
    ConversationLifecycleError,
    ConversationLifecycleResult,
    ConversationNotFound,
    ConversationOperation,
    ConversationStatus,
    InvalidConversationTransition,
    PermanentDeleteAuthorizationError,
    allowed_source_statuses,
    is_transition_allowed,
)

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
