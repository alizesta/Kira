"""Lifecycle adapter for registering an application service as a managed module."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..app.dependency_container import DependencyContainer
from ..app.event_bus import EventBus


class ServiceModule:
    """Expose one service factory through DI and own its registration lifecycle."""

    def __init__(self, service_key: str, factory: Callable[[], Any]) -> None:
        key = str(service_key or "").strip()
        if not key:
            raise ValueError("service_key is required")
        if not callable(factory):
            raise TypeError("service factory must be callable")
        self.service_key = key
        self.factory = factory
        self._container: DependencyContainer | None = None
        self._registered = False

    def register(self, container: DependencyContainer, event_bus: EventBus) -> None:
        del event_bus  # Services receive EventBus only when their contract requires it.
        if self._registered:
            raise RuntimeError(f"Service module is already registered: {self.service_key}")
        container.register_factory(self.service_key, self.factory)
        self._container = container
        self._registered = True

    def start(self) -> None:
        if not self._registered or self._container is None:
            raise RuntimeError(f"Service module is not registered: {self.service_key}")

    def stop(self) -> None:
        # Services currently expose request-scoped or application-owned resources;
        # concrete shutdown hooks will be added to their service contracts as needed.
        return None

    def dispose(self) -> None:
        if self._container is not None and self._registered:
            self._container.unregister(self.service_key)
        self._container = None
        self._registered = False
