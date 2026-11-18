"""Toolkit-neutral contract for asynchronous provider workers."""
from __future__ import annotations

from typing import Any, Callable, Protocol


class ProviderWorkerPort(Protocol):
    """Minimal provider execution contract consumed by Chat application services."""

    def subscribe(self, event: str, callback: Callable[..., Any]) -> Callable[[], Any] | None:
        """Subscribe to a named provider event; return an optional unsubscribe callback."""
        ...

    def start(self) -> Any:
        """Begin provider execution without blocking the caller."""
        ...
