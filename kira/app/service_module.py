"""Lifecycle adapter for exposing an application service through dependency injection."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..app.dependency_container import DependencyContainer
from ..app.event_bus import EventBus


class ServiceModule:
    """Create, publish and release one service as a managed application module."""

    def __init__(self, service_key: str, factory: Callable[[], Any]) -> None:
        key = str(service_key or "").strip()
        if not key:
            raise ValueError("service_key is required")
        if not callable(factory):
            raise TypeError("service factory must be callable")
        self.service_key = key
        self.factory = factory
        self._container: DependencyContainer | None = None
        self._instance: Any | None = None

    def register(self, container: DependencyContainer, event_bus: EventBus) -> None:
        del event_bus  # Services receive EventBus only when their contract requires it.
        if self._container is not None:
            raise RuntimeError(f"Service module is already registered: {self.service_key}")
        self._container = container

    def start(self) -> None:
        if self._container is None:
            raise RuntimeError(f"Service module is not registered: {self.service_key}")
        if self._instance is not None:
            return
        instance = self.factory()
        try:
            start = getattr(instance, "start", None)
            if callable(start):
                start()
            self._container.register_instance(self.service_key, instance)
            self._instance = instance
        except Exception:
            cleanup = getattr(instance, "dispose", None) or getattr(instance, "close", None)
            if callable(cleanup):
                try:
                    cleanup()
                except Exception:
                    pass
            raise

    def stop(self) -> None:
        if self._instance is None:
            return
        stop = getattr(self._instance, "stop", None)
        if callable(stop):
            stop()

    def dispose(self) -> None:
        instance = self._instance
        if instance is not None:
            cleanup = getattr(instance, "dispose", None) or getattr(instance, "close", None)
            if callable(cleanup):
                cleanup()
        if self._container is not None:
            self._container.unregister(self.service_key)
        self._instance = None
        self._container = None
