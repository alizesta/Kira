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


class ChatCoordinator:
    """Own bounded FIFO admission and dispatch through an injected boundary.

    Session storage, provider clients, persistence, and presentation remain
    outside this class. The dispatch callback is the application adapter.
    """

    def __init__(self, dispatch: Callable[[ChatRequest], None], *, max_pending: int = 3):
        if not callable(dispatch):
            raise TypeError("dispatch must be callable")
        if max_pending < 0:
            raise ValueError("max_pending cannot be negative")
        self._dispatch = dispatch
        self._max_pending = int(max_pending)
        self._pending: deque[ChatRequest] = deque()

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    def submit(self, request: ChatRequest, *, busy: bool = False,
               force_queue: bool = False) -> SubmissionResult:
        if not isinstance(request, ChatRequest):
            raise TypeError("request must be a ChatRequest")
        if busy or force_queue:
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
