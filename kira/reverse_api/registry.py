"""Thread-safe registry of Reverse API transports (browser/session backends plug in here)."""
from __future__ import annotations

from collections.abc import Callable
from threading import RLock
from typing import Any


class TransportRegistry:
    """Map stable transport ids to factories ``factory(config: dict) -> ReverseTransport``."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._factories: dict[str, Callable[[dict[str, Any]], Any]] = {}

    @staticmethod
    def _key(transport_id: str) -> str:
        return str(transport_id or "").strip().lower()

    def register(self, transport_id: str, factory: Callable[[dict[str, Any]], Any], *, replace: bool = False) -> None:
        key = self._key(transport_id)
        if not key:
            raise ValueError("transport id is required")
        if not callable(factory):
            raise TypeError("transport factory must be callable")
        with self._lock:
            if key in self._factories and not replace:
                raise ValueError(f"Transport is already registered: {key}")
            self._factories[key] = factory

    def unregister(self, transport_id: str) -> bool:
        with self._lock:
            return self._factories.pop(self._key(transport_id), None) is not None

    def resolve(self, transport_id: str) -> Callable[[dict[str, Any]], Any] | None:
        with self._lock:
            return self._factories.get(self._key(transport_id))

    def ids(self) -> list[str]:
        with self._lock:
            return sorted(self._factories)


TRANSPORTS = TransportRegistry()
