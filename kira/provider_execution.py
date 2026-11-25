"""Small Event-compatible cancellation view shared by provider adapters."""
from __future__ import annotations

from threading import Event


class CancellationToken:
    """Read-only cancellation view over the router and caller-owned events."""

    def __init__(self, *events: Event | None) -> None:
        self._events = tuple(event for event in events if event is not None)

    def is_set(self) -> bool:
        return any(event.is_set() for event in self._events)
