"""Qt-free provider response lifecycle and normalization.

The handler owns per-request stream aggregation and exactly-once terminal
transitions. It does not know about UI widgets, chat sessions, persistence,
provider clients, prompt/context construction, or request scheduling.
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from threading import RLock
from typing import Any, Mapping


from ..domain.chat import (
    ChatResponseResult,
    ProviderEvent,
    ProviderEventKind,
    ResponseError,
    ResponseEventKind,
    ResponseStatus,
    ResponseStreamEvent,
)


@dataclass
class _RequestState:
    session_id: str
    chunks: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class ResponseHandler:
    """Thread-safe, character-neutral response lifecycle manager.

    Call begin_request once before provider dispatch, then pass provider
    callbacks to handle(). A terminal event atomically removes the active
    state. Late chunks and duplicate terminal callbacks are ignored.
    """

    def __init__(self, *, completed_history_limit: int = 512) -> None:
        if completed_history_limit < 1:
            raise ValueError("completed_history_limit must be at least 1")
        self._lock = RLock()
        self._active: dict[str, _RequestState] = {}
        self._completed: OrderedDict[str, str] = OrderedDict()
        self._completed_history_limit = int(completed_history_limit)

    @property
    def active_request_count(self) -> int:
        with self._lock:
            return len(self._active)

    def begin_request(
        self,
        request_id: str,
        session_id: str,
        *,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        request_id = str(request_id or "").strip()
        session_id = str(session_id or "").strip()
        if not request_id:
            raise ValueError("request_id must not be empty")
        if not session_id:
            raise ValueError("session_id must not be empty")
        with self._lock:
            if request_id in self._active or request_id in self._completed:
                raise ValueError(f"request_id is already known: {request_id}")
            self._active[request_id] = _RequestState(
                session_id=session_id,
                metadata=dict(metadata or {}),
            )

    def handle(self, event: ProviderEvent) -> ResponseStreamEvent | None:
        if not isinstance(event, ProviderEvent):
            raise TypeError("event must be a ProviderEvent")
        if not event.request_id or not event.session_id:
            return None

        with self._lock:
            state = self._active.get(event.request_id)
            if state is None or state.session_id != event.session_id:
                return None

            if event.kind is ProviderEventKind.CHUNK:
                if not isinstance(event.payload, str):
                    raise TypeError("chunk payload must be str")
                state.chunks.append(event.payload)
                content = "".join(state.chunks)
                return ResponseStreamEvent(
                    request_id=event.request_id,
                    session_id=event.session_id,
                    kind=ResponseEventKind.CHUNK,
                    chunk=event.payload,
                    content=content,
                )

            status, error, provider_metadata = self._terminal_details(event)
            content = "".join(state.chunks)
            if "text" in provider_metadata:
                final_text = str(provider_metadata.pop("text") or "")
                # A provider may omit final text while still having streamed
                # chunks. Never discard those chunks because of an empty field.
                if final_text or not content:
                    content = final_text

            metadata = dict(state.metadata)
            metadata.update(provider_metadata)
            metadata["chunk_count"] = len(state.chunks)
            metadata["streamed"] = bool(state.chunks)
            metadata["empty_response"] = not bool(content.strip())
            metadata["incomplete"] = status is not ResponseStatus.COMPLETED
            result = ChatResponseResult(
                request_id=event.request_id,
                session_id=event.session_id,
                status=status,
                content=content,
                error=error,
                metadata=metadata,
            )

            # Terminal transition and cleanup happen while holding one lock.
            # Retain a bounded tombstone so duplicate/late events are rejected.
            del self._active[event.request_id]
            self._completed[event.request_id] = event.session_id
            self._completed.move_to_end(event.request_id)
            while len(self._completed) > self._completed_history_limit:
                self._completed.popitem(last=False)

            return ResponseStreamEvent(
                request_id=event.request_id,
                session_id=event.session_id,
                kind=ResponseEventKind.FINAL,
                content=result.content,
                result=result,
            )

    @staticmethod
    def _terminal_details(
        event: ProviderEvent,
    ) -> tuple[ResponseStatus, ResponseError | None, dict[str, Any]]:
        if event.kind is ProviderEventKind.CANCELLED:
            return ResponseStatus.CANCELLED, None, {}

        if event.kind is ProviderEventKind.FAILED:
            if isinstance(event.error, ResponseError):
                error = event.error
            else:
                error = ResponseError(
                    code="provider_error",
                    message=str(event.error or "Provider request failed"),
                    recoverable=bool(event.recoverable),
                )
            return ResponseStatus.FAILED, error, {}

        if event.kind is not ProviderEventKind.COMPLETED:
            raise ValueError(f"Unsupported provider event kind: {event.kind}")

        if not isinstance(event.payload, Mapping):
            raise TypeError("completed payload must be a mapping")
        metadata = dict(event.payload)
        if metadata.get("stopped"):
            return ResponseStatus.CANCELLED, None, metadata
        interrupted = metadata.get("interrupted")
        if interrupted:
            return (
                ResponseStatus.FAILED,
                ResponseError(
                    code="provider_interrupted",
                    message=str(interrupted),
                    recoverable=False,
                ),
                metadata,
            )
        return ResponseStatus.COMPLETED, None, metadata
