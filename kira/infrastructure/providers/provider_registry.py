"""Thread-safe registry for replaceable chat-provider adapters."""
from __future__ import annotations

from collections.abc import Callable, Mapping
from importlib import import_module
from threading import RLock
from typing import Any

# Optional adapters that are imported only when first resolved (keeps startup lazy and avoids import cycles).
# Format: provider id -> "package.module:ClassName".
DEFAULT_LAZY_ADAPTERS: dict[str, str] = {}


class ProviderRegistry:
    """Map stable provider IDs to adapter factories without coupling consumers to classes."""

    def __init__(self, providers: Mapping[str, Callable[..., Any]] | None = None) -> None:
        self._lock = RLock()
        self._providers: dict[str, Callable[..., Any]] = {}
        self._lazy: dict[str, str] = dict(DEFAULT_LAZY_ADAPTERS)
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
            self._lazy.pop(key, None)       # an explicit registration always wins over a lazy default

    def unregister(self, name: str) -> bool:
        key = str(name or "").strip().lower()
        with self._lock:
            removed = self._providers.pop(key, None) is not None
            return self._lazy.pop(key, None) is not None or removed

    def resolve(self, name: str) -> Callable[..., Any] | None:
        key = str(name or "").strip().lower()
        with self._lock:
            factory = self._providers.get(key)
            if factory is not None:
                return factory
            target = self._lazy.get(key)
            if target is None:
                return None
            module_name, _, attr = target.partition(":")
            factory = getattr(import_module(module_name), attr)
            self._providers[key] = factory
            del self._lazy[key]
            return factory

    def snapshot(self) -> dict[str, Callable[..., Any]]:
        with self._lock:
            return dict(self._providers)
