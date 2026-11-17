"""Public contracts for the independent chat feature."""

from .persistence import ChatPersistence, ChatRepository, PersistenceError, SqliteChatRepository, create_default_chat_persistence
from .events import CHAT_EVENT_TYPES, ChatEvent, ChatEventDispatch, ChatEventPublisher, ChatEventType
from .coordinator import ChatCoordinator, ChatProviderDispatcher, ChatRequest, SubmissionResult
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

from .attachments import Attachment, AttachmentError, AttachmentManager, AttachmentSource, AttachmentStatus

from .application_service import (
    ApplicationEventKind,
    ChatApplicationEvent,
    ChatApplicationRequest,
    ChatApplicationService,
    PersistenceOutcome,
    RequestStatus,
    Submission,
)

from .session_manager import SessionManager, SessionState, SessionStateChanged

__all__ = [
    "CHAT_EVENT_TYPES",
    "ChatEvent",
    "ChatEventDispatch",
    "ChatEventPublisher",
    "ChatEventType",
    "Attachment",
    "AttachmentError",
    "AttachmentManager",
    "AttachmentSource",
    "AttachmentStatus",
    "ChatPersistence",
    "ChatRepository",
    "SqliteChatRepository",
    "PersistenceError",
    "create_default_chat_persistence",
    "ChatCoordinator",
    "ChatProviderDispatcher",
    "ChatRequest",
    "SubmissionResult",
    "ChatResponseResult",
    "ProviderEvent",
    "ProviderEventKind",
    "ResponseError",
    "ResponseEventKind",
    "ResponseHandler",
    "ResponseStatus",
    "ResponseStreamEvent",
    "ApplicationEventKind",
    "ChatApplicationEvent",
    "ChatApplicationRequest",
    "ChatApplicationService",
    "PersistenceOutcome",
    "RequestStatus",
    "Submission",
    "SessionManager",
    "SessionState",
    "SessionStateChanged",
]
