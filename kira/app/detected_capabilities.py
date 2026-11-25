"""Process-local facts discovered from providers and the host system.

DetectedCapabilities is independent from Persistent Settings and RuntimeState:
it has no settings reference, is never serialized, and is owned by a runtime
service whose lifetime matches the capabilities it observes.
"""
from __future__ import annotations

from copy import deepcopy
from threading import RLock
from typing import Any


CAPABILITY_KEYS = frozenset({
    "api_registry",
    "ollama_models",
    "model_catalog_refreshed_at",
    "model_tests",
})


class DetectedCapabilities:
    """Small thread-safe store for facts reported by live capability probes."""

    __slots__ = ("_values", "_lock")

    def __init__(self) -> None:
        self._values: dict[str, Any] = {}
        self._lock = RLock()

    @staticmethod
    def _check(key: str) -> str:
        name = str(key)
        if name not in CAPABILITY_KEYS:
            raise KeyError(f"Detected capability is not declared: {name}")
        return name

    def get(self, key: str, default: Any = None) -> Any:
        name = self._check(key)
        with self._lock:
            return self._values.get(name, default)

    def set(self, key: str, value: Any) -> None:
        name = self._check(key)
        with self._lock:
            self._values[name] = value

    def setdefault(self, key: str, default: Any) -> Any:
        name = self._check(key)
        with self._lock:
            return self._values.setdefault(name, default)

    def pop(self, key: str, default: Any = None) -> Any:
        name = self._check(key)
        with self._lock:
            return self._values.pop(name, default)

    def snapshot(self) -> dict[str, Any]:
        """Return a detached snapshot suitable for diagnostics and tests."""
        with self._lock:
            return deepcopy(self._values)

    def clear(self) -> None:
        with self._lock:
            self._values.clear()
