"""UI-agnostic coordination for one character chat request queue."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Mapping, Sequence

from ..core.interfaces.provider_worker import ProviderWorkerPort


@dataclass(frozen=True)
class ChatRequest:
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
        cls, text: str, attachments: Sequence[Mapping[str, Any]] | None = None,
        voice: bool = False, *, request_id: str | None = None,
        session_id: str | None = None,
    ) -> "ChatRequest":
        return cls(
            str(text), tuple(attachments or ()), bool(voice),
            request_id=request_id, session_id=session_id,
        )


class SubmissionResult(str, Enum):
    DISPATCHED = "dispatched"
    QUEUED = "queued"
    FULL = "full"


class ChatProviderDispatcher:
    """Adapt a provider worker factory to explicit response callback ports.

    Worker construction and stream callbacks are injected through a
    toolkit-neutral ProviderWorkerPort contract.
    """

    _EVENTS = frozenset({"tool_event", "event", "chunk", "complete", "error"})

    def __init__(self, worker_factory: Callable[..., ProviderWorkerPort]):
        if not callable(worker_factory):
            raise TypeError("worker_factory must be callable")
        self._worker_factory = worker_factory

    def start(self, *, callbacks: Mapping[str, Callable[..., Any]], **request: Any) -> ProviderWorkerPort:
        unknown = set(callbacks) - self._EVENTS
        if unknown:
            raise ValueError(f"Unsupported provider callbacks: {', '.join(sorted(unknown))}")
        worker: ProviderWorkerPort = self._worker_factory(**request)
        subscribe = getattr(worker, "subscribe", None)
        start = getattr(worker, "start", None)
        if not callable(subscribe) or not callable(start):
            raise TypeError("provider workers must implement subscribe(event, callback) and start()")
        for event_name, callback in callbacks.items():
            if callback is not None:
                subscribe(event_name, callback)
        start()
        return worker


class ChatCoordinator:
    """Own bounded FIFO admission and dispatch through injected boundaries.

    Session storage, provider clients, persistence, and presentation remain
    outside this class. Both request dispatch and provider stream callbacks
    are supplied by application adapters.
    """

    def __init__(self, dispatch: Callable[[ChatRequest], None], *, max_pending: int = 3,
                 provider_dispatcher: ChatProviderDispatcher | None = None):
        if not callable(dispatch):
            raise TypeError("dispatch must be callable")
        if max_pending < 0:
            raise ValueError("max_pending cannot be negative")
        self._dispatch = dispatch
        self._provider_dispatcher = provider_dispatcher
        self._max_pending = int(max_pending)
        self._pending: deque[ChatRequest] = deque()

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    def submit(self, request: ChatRequest, *, busy: bool = False,
               force_queue: bool = False) -> SubmissionResult:
        if not isinstance(request, ChatRequest):
            raise TypeError("request must be a ChatRequest")
        if busy or force_queue or self._pending:
            if len(self._pending) >= self._max_pending:
                return SubmissionResult.FULL
            self._pending.append(request)
            return SubmissionResult.QUEUED
        self._dispatch(request)
        return SubmissionResult.DISPATCHED

    def take_next(self, *, busy: bool = False) -> ChatRequest | None:
        """Return the next queued request only when the active turn is idle."""
        if busy or not self._pending:
            return None
        return self._pending.popleft()

    def clear(self) -> None:
        self._pending.clear()

    def start_provider_request(self, *, callbacks: Mapping[str, Callable[..., Any]], **request: Any) -> Any:
        """Start a provider request and route stream events to injected ports."""
        if self._provider_dispatcher is None:
            raise RuntimeError("No provider dispatcher has been configured")
        return self._provider_dispatcher.start(callbacks=callbacks, **request)
