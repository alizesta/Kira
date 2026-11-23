"""Thread-local cancellation context shared by the ToolAgent and process-backed tools."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Iterator


_ACTIVE_CANCEL_EVENT: ContextVar[Any | None] = ContextVar(
    "kira_tool_cancel_event",
    default=None,
)


@contextmanager
def cancellation_scope(event: Any | None) -> Iterator[None]:
    """Expose one request's cancellation event to synchronous nested tool handlers."""
    token = _ACTIVE_CANCEL_EVENT.set(
        event if event is not None else _ACTIVE_CANCEL_EVENT.get()
    )
    try:
        yield
    finally:
        _ACTIVE_CANCEL_EVENT.reset(token)


def current_cancel_event() -> Any | None:
    """Return the cancellation event active in this execution context, if any."""
    return _ACTIVE_CANCEL_EVENT.get()
