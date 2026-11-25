"""Process-local state for application and presentation lifecycles.

RuntimeState deliberately knows nothing about persisted settings or detected
capabilities. Its allowed field set is supplied by the owning composition root.
"""
from __future__ import annotations

from threading import RLock
from typing import Any, Iterable


class RuntimeState:
    """Strict, in-memory state bucket with an explicit field contract."""

    __slots__ = ("_fields", "_values", "_lock")

    def __init__(self, fields: Iterable[str], initial: dict[str, Any] | None = None) -> None:
        self._fields = frozenset(str(name) for name in fields)
        self._values: dict[str, Any] = {}
        self._lock = RLock()
        for name, value in (initial or {}).items():
            self.set(name, value)

    def _check(self, name: str) -> str:
        key = str(name)
        if key not in self._fields:
            raise KeyError(f"Runtime state field is not declared: {key}")
        return key

    def set(self, name: str, value: Any) -> None:
        key = self._check(name)
        with self._lock:
            self._values[key] = value

    def get(self, name: str, default: Any = None) -> Any:
        key = self._check(name)
        with self._lock:
            return self._values.get(key, default)

    def contains(self, name: str) -> bool:
        key = self._check(name)
        with self._lock:
            return key in self._values

    def snapshot(self) -> dict[str, Any]:
        """Return a detached mapping while retaining identity of live runtime objects."""
        with self._lock:
            return dict(self._values)

    def clear(self, name: str | None = None) -> None:
        with self._lock:
            if name is None:
                self._values.clear()
            else:
                self._values.pop(self._check(name), None)
