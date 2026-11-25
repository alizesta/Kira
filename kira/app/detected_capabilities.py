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
    "route_notes",
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

    def mapping_get(self, key: str, item: str, default: Any = None) -> Any:
        """Read one entry from a process-local mapping without leaking mutable state."""
        name = self._check(key)
        with self._lock:
            bucket = self._values.get(name)
            if not isinstance(bucket, dict):
                return deepcopy(default)
            return deepcopy(bucket.get(str(item), default))

    def mapping_set(self, key: str, item: str, value: Any) -> None:
        """Atomically update one entry in a process-local mapping capability."""
        name = self._check(key)
        with self._lock:
            bucket = self._values.setdefault(name, {})
            if not isinstance(bucket, dict):
                raise TypeError(f"Detected capability {name} is not a mapping")
            bucket[str(item)] = deepcopy(value)

    def mapping_pop(self, key: str, item: str, default: Any = None) -> Any:
        """Atomically remove one entry from a process-local mapping capability."""
        name = self._check(key)
        with self._lock:
            bucket = self._values.get(name)
            if not isinstance(bucket, dict):
                return deepcopy(default)
            return deepcopy(bucket.pop(str(item), default))

    def mapping_remove_keys(self, key: str, items) -> None:
        """Remove a collection of entries atomically."""
        name = self._check(key)
        keys = tuple(str(item) for item in items)
        with self._lock:
            bucket = self._values.get(name)
            if isinstance(bucket, dict):
                for item in keys:
                    bucket.pop(item, None)

    def mapping_reconcile(self, key: str, id_remap: dict[str, str], valid_keys) -> None:
        """Move notes across route-ID normalization and discard observations for removed routes."""
        name = self._check(key)
        valid = {str(item) for item in valid_keys}
        with self._lock:
            bucket = self._values.get(name)
            if not isinstance(bucket, dict):
                return
            for old_id, new_id in id_remap.items():
                if old_id in bucket:
                    bucket.setdefault(new_id, bucket[old_id])
                    bucket.pop(old_id, None)
            for item in tuple(bucket):
                if item not in valid:
                    bucket.pop(item, None)

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
