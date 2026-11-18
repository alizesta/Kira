"""Thread-safe registry for replaceable chat-provider adapters."""
from __future__ import annotations

from collections.abc import Callable, Mapping
from threading import RLock
from typing import Any


class ProviderRegistry:
    """Map stable provider IDs to adapter factories without coupling consumers to classes."""

    def __init__(self, providers: Mapping[str, Callable[..., Any]] | None = None) -> None:
        self._lock = RLock()
        self._providers: dict[str, Callable[..., Any]] = {}
        for name, factory in (providers or {}).items():
            self.register(name, factory)

    def register(self, name: str, factory: Callable[..., Any], *, replace: bool = False) -> None:
        key = str(name or "").strip().lower()
        if not key:
            raise ValueError("provider name is required")
        if not callable(factory):
            raise TypeError("provider factory must be callable")
        with self._lock:
            if key in self._providers and not replace:
                raise ValueError(f"Provider is already registered: {key}")
            self._providers[key] = factory

    def unregister(self, name: str) -> bool:
        key = str(name or "").strip().lower()
        with self._lock:
            return self._providers.pop(key, None) is not None

    def resolve(self, name: str) -> Callable[..., Any] | None:
        key = str(name or "").strip().lower()
        with self._lock:
            return self._providers.get(key)

    def snapshot(self) -> dict[str, Callable[..., Any]]:
        with self._lock:
            return dict(self._providers)
