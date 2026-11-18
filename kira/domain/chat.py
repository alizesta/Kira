"""Pure Chat request, response and application event contracts.

These values carry request/session identity across Chat components. They contain
no provider SDK, persistence, coordinator, Application service or UI dependency.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Sequence


class RequestStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ApplicationEventKind(str, Enum):
    REQUEST_STARTED = "request_started"
    PROVIDER_CHUNK = "provider_chunk"
    PROVIDER_FINAL = "provider_final"
    REQUEST_COMPLETED = "request_completed"
    REQUEST_FAILED = "request_failed"
    REQUEST_CANCELLED = "request_cancelled"
    PERSISTENCE_WARNING = "persistence_warning"


class ProviderEventKind(str, Enum):
    CHUNK = "chunk"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ResponseStatus(str, Enum):
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ResponseEventKind(str, Enum):
    CHUNK = "chunk"
    FINAL = "final"


@dataclass(frozen=True)
class ResponseError:
    """Provider failure normalized without depending on a provider SDK."""

    code: str
    message: str
    recoverable: bool = False


@dataclass(frozen=True)
class ProviderEvent:
    """One provider callback, explicitly scoped to a request and Chat Session."""

    request_id: str
    session_id: str
    kind: ProviderEventKind
    payload: Any = None
    error: str | ResponseError | None = None
    recoverable: bool = False

    @classmethod
    def chunk(cls, request_id: str, session_id: str, content: str) -> "ProviderEvent":
        return cls(request_id, session_id, ProviderEventKind.CHUNK, payload=content)

    @classmethod
    def completed(
        cls, request_id: str, session_id: str, response: Mapping[str, Any]
    ) -> "ProviderEvent":
        return cls(request_id, session_id, ProviderEventKind.COMPLETED, payload=response)

    @classmethod
    def failed(
        cls,
        request_id: str,
        session_id: str,
        error: str | ResponseError,
        *,
        recoverable: bool = False,
    ) -> "ProviderEvent":
        return cls(
            request_id,
            session_id,
            ProviderEventKind.FAILED,
            error=error,
            recoverable=recoverable,
        )

    @classmethod
    def cancelled(cls, request_id: str, session_id: str) -> "ProviderEvent":
        return cls(request_id, session_id, ProviderEventKind.CANCELLED)


@dataclass(frozen=True)
class ChatResponseResult:
    """Stable final response contract for the Chat application layer."""

    request_id: str
    session_id: str
    status: ResponseStatus
    content: str
    error: ResponseError | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ResponseStreamEvent:
    """Normalized streaming event: either a chunk or exactly one terminal result."""

    request_id: str
    session_id: str
    kind: ResponseEventKind
    chunk: str = ""
    content: str = ""
    result: ChatResponseResult | None = None



@dataclass(frozen=True)
class ContextRequest:
    """Immutable snapshot of all values needed to build one provider turn."""

    messages: Sequence[Mapping[str, Any]] = field(default_factory=tuple)
    character_id: str = ""
    character_profile: Mapping[str, Any] = field(default_factory=dict)
    settings: Mapping[str, Any] = field(default_factory=dict)
    memory: str = ""
    mood: str = ""
    character_context: str = ""
    format_hint: str = ""
    voice_input: bool = False
    mode: Any = None
    body_context: str = ""
    tool_context: str = ""
    active_capabilities: Sequence[str] = field(default_factory=tuple)
    turn_extra: Mapping[str, Any] | None = None
    max_context_chars: int = 0


@dataclass(frozen=True)
class ContextResult:
    """Provider-neutral prompt and ordered message snapshot for one turn."""

    system_prompt: str
    messages: tuple[dict[str, Any], ...]
    character_id: str
    retained_context_chars: int
    dropped_messages: int = 0

@dataclass(frozen=True)
class ChatRequest:
    """Coordinator admission request with an optional paired identity scope."""

    text: str
    attachments: tuple[Mapping[str, Any], ...] = ()
    voice: bool = False
    request_id: str | None = None
    session_id: str | None = None

    def __post_init__(self) -> None:
        request_id = str(self.request_id).strip() if self.request_id is not None else None
        session_id = str(self.session_id).strip() if self.session_id is not None else None
        if request_id == "":
            raise ValueError("request_id must not be empty")
        if session_id == "":
            raise ValueError("session_id must not be empty")
        if (request_id is None) != (session_id is None):
            raise ValueError("request_id and session_id must be provided together")
        object.__setattr__(self, "request_id", request_id)
        object.__setattr__(self, "session_id", session_id)

    @classmethod
    def create(
        cls,
        text: str,
        attachments: Sequence[Mapping[str, Any]] | None = None,
        voice: bool = False,
        *,
        request_id: str | None = None,
        session_id: str | None = None,
    ) -> "ChatRequest":
        return cls(
            str(text),
            tuple(attachments or ()),
            bool(voice),
            request_id=request_id,
            session_id=session_id,
        )


class SubmissionResult(str, Enum):
    DISPATCHED = "dispatched"
    QUEUED = "queued"
    FULL = "full"


@dataclass(frozen=True)
class ChatApplicationRequest:
    request_id: str
    session_id: str
    text: str
    attachments: tuple[Mapping[str, Any], ...] = ()
    voice: bool = False
    conversation_id: str | None = None
    character_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ChatApplicationEvent:
    request_id: str
    session_id: str
    kind: ApplicationEventKind
    status: RequestStatus
    content: str = ""
    chunk: str = ""
    result: ChatResponseResult | None = None
    error: str | None = None
    persistence_ok: bool | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Submission:
    request: ChatApplicationRequest
    status: RequestStatus
    queued: bool
    accepted: bool


@dataclass(frozen=True)
class PersistenceOutcome:
    ok: bool
    error: str | None = None


__all__ = [
    "ApplicationEventKind",
    "ChatApplicationEvent",
    "ChatApplicationRequest",
    "ContextRequest",
    "ContextResult",
    "ChatRequest",
    "ChatResponseResult",
    "PersistenceOutcome",
    "ProviderEvent",
    "ProviderEventKind",
    "RequestStatus",
    "ResponseError",
    "ResponseEventKind",
    "ResponseStatus",
    "ResponseStreamEvent",
    "Submission",
    "SubmissionResult",
]
