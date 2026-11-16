"""Chat request coordination boundaries."""

from .persistence import ChatPersistence, ChatRepository, PersistenceError, SqliteChatRepository, create_default_chat_persistence
from .coordinator import ChatCoordinator, ChatProviderDispatcher, ChatRequest, SubmissionResult
from .session_manager import SessionLifecycleError, SessionManager, SessionStateChanged, SessionStatus
from .response_handler import (
    ChatResponseResult,
    ProviderEvent,
    ProviderEventKind,
    ResponseError,
    ResponseEventKind,
    ResponseHandler,
    ResponseStatus,
    ResponseStreamEvent,
)

__all__ = [
    "ChatPersistence",
    "ChatRepository",
    "SqliteChatRepository",
    "PersistenceError",
    "create_default_chat_persistence",
    "ChatCoordinator",
    "ChatProviderDispatcher",
    "ChatRequest",
    "SubmissionResult",
    "SessionLifecycleError",
    "SessionManager",
    "SessionStateChanged",
    "SessionStatus",
    "ChatResponseResult",
    "ProviderEvent",
    "ProviderEventKind",
    "ResponseError",
    "ResponseEventKind",
    "ResponseHandler",
    "ResponseStatus",
    "ResponseStreamEvent",
]
