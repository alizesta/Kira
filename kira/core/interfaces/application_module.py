"""Lifecycle contract implemented by independently managed application modules."""
from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from ...app.dependency_container import DependencyContainer
    from ...app.event_bus import EventBus


class ApplicationModule(Protocol):
    """A module receives shared infrastructure at registration and owns its resources."""

    def register(self, container: "DependencyContainer", event_bus: "EventBus") -> None: ...

    def start(self) -> None: ...

    def stop(self) -> None: ...

    def dispose(self) -> None: ...
