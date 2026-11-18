"""Lifecycle contract implemented by independently managed application modules."""
from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, Protocol


class DependencyRegistry(Protocol):
    """Minimal DI operations available to a managed module.

    This structural contract deliberately lives in core: concrete containers
    belong to the outer application composition layer.
    """

    def register_instance(self, key: str, instance: Any) -> None: ...

    def register_factory(self, key: str, factory: Callable[[], Any]) -> None: ...

    def resolve(self, key: str) -> Any: ...

    def unregister(self, key: str) -> None: ...


class PublishedEvent(Protocol):
    """Immutable event envelope accepted by the shared application EventBus."""

    event_type: Any
    event_id: str
    timestamp: Any
    session_id: str | None
    request_id: str | None
    payload: Mapping[str, Any]
    metadata: Mapping[str, Any]


class EventPublicationReport(Protocol):
    """Result returned after a typed event publication is dispatched."""

    event_name: str
    sequence: int
    delivered: int
    failures: tuple[Any, ...]
    queued: bool


class ModuleEventBus(Protocol):
    """Notification operations exposed to application modules."""

    def subscribe(
        self, event_name: str, callback: Callable[..., Any]
    ) -> Callable[[], None]: ...

    def subscribe_event(
        self, event_type: Any, callback: Callable[[Any], Any]
    ) -> Callable[[], None]: ...

    def publish(self, event_name: str, **payload: Any) -> Any: ...

    def publish_event(self, event: PublishedEvent) -> EventPublicationReport: ...


class ApplicationModule(Protocol):
    """A module receives shared infrastructure at registration and owns its resources."""

    def register(
        self, container: DependencyRegistry, event_bus: ModuleEventBus
    ) -> None: ...

    def start(self) -> None: ...

    def stop(self) -> None: ...

    def dispose(self) -> None: ...
