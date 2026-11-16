"""UI-agnostic coordination for one character chat request queue."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Mapping, Sequence


@dataclass(frozen=True)
class ChatRequest:
    text: str
    attachments: tuple[Mapping[str, Any], ...] = ()
    voice: bool = False

    @classmethod
    def create(cls, text: str, attachments: Sequence[Mapping[str, Any]] | None = None,
               voice: bool = False) -> "ChatRequest":
        return cls(str(text), tuple(attachments or ()), bool(voice))


class SubmissionResult(str, Enum):
    DISPATCHED = "dispatched"
    QUEUED = "queued"
    FULL = "full"


class ChatProviderDispatcher:
    """Adapt a provider worker factory to explicit response callback ports.

    The worker may be Qt-backed, but this adapter imports no Qt. Worker
    construction and stream callbacks are injected by the application.
    """

    _SIGNALS = {
        "tool_event": "tool_event",
        "event": "event",
        "chunk": "chunk",
        "complete": "finished_ok",
        "error": "failed",
    }

    def __init__(self, worker_factory: Callable[..., Any]):
        if not callable(worker_factory):
            raise TypeError("worker_factory must be callable")
        self._worker_factory = worker_factory

    def start(self, *, callbacks: Mapping[str, Callable[..., Any]], **request: Any) -> Any:
        unknown = set(callbacks) - set(self._SIGNALS)
        if unknown:
            raise ValueError(f"Unsupported provider callbacks: {', '.join(sorted(unknown))}")
        worker = self._worker_factory(**request)
        for callback_name, signal_name in self._SIGNALS.items():
            callback = callbacks.get(callback_name)
            if callback is not None:
                getattr(worker, signal_name).connect(callback)
        worker.start()
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
