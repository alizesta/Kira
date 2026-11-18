"""Lifecycle contract implemented by independently managed application modules.

The contracts below describe the capabilities modules may use during
registration. They intentionally live in Core so the application lifecycle
engine can implement them without Core importing concrete application classes.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol


class ModuleServiceRegistry(Protocol):
    """Minimal dependency-registration port exposed to application modules."""

    def register_instance(self, key: str, instance: Any) -> None: ...

    def register_factory(self, key: str, factory: Callable[[], Any]) -> None: ...

    def resolve(self, key: str) -> Any: ...

    def unregister(self, key: str) -> None: ...


class ModuleEventBus(Protocol):
    """Notification port shared with modules during their registration."""

    def subscribe(
        self, event_name: str, callback: Callable[..., Any]
    ) -> Callable[[], None]: ...

    def subscribe_event(
        self, event_type: Any, callback: Callable[[Any], Any]
    ) -> Callable[[], None]: ...

    def publish(self, event_name: str, **payload: Any) -> Any: ...

    def publish_event(self, event: Any) -> Any: ...

    def close(self) -> None: ...


class ApplicationModule(Protocol):
    """A module receives shared infrastructure at registration and owns its resources."""

    def register(
        self, container: ModuleServiceRegistry, event_bus: ModuleEventBus
    ) -> None: ...

    def start(self) -> None: ...

    def stop(self) -> None: ...

    def dispose(self) -> None: ...
