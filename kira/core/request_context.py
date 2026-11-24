"""Request-local context shared with browser-backed provider transports."""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar


_conversation_id: ContextVar[str | None] = ContextVar(
    "kira_request_conversation_id", default=None
)


@contextmanager
def conversation_scope(conversation_id: str | None) -> Iterator[None]:
    """Expose the active Kira conversation to providers for the current worker thread."""
    value = str(conversation_id).strip() if conversation_id is not None else ""
    token = _conversation_id.set(value or None)
    try:
        yield
    finally:
        _conversation_id.reset(token)


def current_conversation_id() -> str | None:
    """Return the conversation identity attached to the active provider request."""
    return _conversation_id.get()


__all__ = ["conversation_scope", "current_conversation_id"]
