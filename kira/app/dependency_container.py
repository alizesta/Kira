"""Minimal dependency container for explicit service wiring."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any


class DependencyContainer:
    def __init__(self) -> None:
        self._providers: dict[str, Callable[[], Any]] = {}
        self._instances: dict[str, Any] = {}

    def register_instance(self, key: str, instance: Any) -> None:
        self._providers.pop(key, None)
        self._instances[key] = instance

    def register_factory(self, key: str, factory: Callable[[], Any]) -> None:
        if not callable(factory):
            raise TypeError("factory must be callable")
        self._instances.pop(key, None)
        self._providers[key] = factory

    def resolve(self, key: str) -> Any:
        if key in self._instances:
            return self._instances[key]
        if key not in self._providers:
            raise KeyError(f"Dependency is not registered: {key}")
        instance = self._providers[key]()
        self._instances[key] = instance
        return instance

    def unregister(self, key: str) -> None:
        self._providers.pop(key, None)
        self._instances.pop(key, None)
