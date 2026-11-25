"""Router-scoped health, cooldown and quota state for hybrid provider execution.

Each HybridRouter owns one instance by default. Nothing in this module is
process-global or persisted. A higher-level application owner may explicitly
share individual maps across a related group of routers; independent groups
remain isolated unless such sharing is deliberately configured.
"""
from __future__ import annotations

import threading
import time
from typing import Any


class ProviderRuntimeState:
    """Own transient provider state for exactly one router lifecycle."""

    def __init__(self) -> None:
        self.cooldowns: dict[str, float] = {}
        self.quota_blocks: dict[tuple, dict[str, Any]] = {}
        self.states: dict[str, dict[str, Any]] = {}
        self._lock = threading.RLock()

    def state_for(self, route_id: str) -> dict[str, Any]:
        """Return the mutable health record owned by this router."""
        defaults = {
            "health": "unknown", "last_error": None, "last_ms": None,
            "latency_ms": None, "last_ok_at": None, "last_attempt_at": None,
            "failures": 0, "last_kind": None, "retryable": None,
            "failure_class": None,
        }
        with self._lock:
            return self.states.setdefault(str(route_id), defaults)

    def cooldown_remaining(self, route_id: str, *, now: float | None = None) -> float:
        instant = time.monotonic() if now is None else float(now)
        with self._lock:
            return max(0.0, float(self.cooldowns.get(str(route_id), 0.0)) - instant)

    def set_cooldown(self, route_id: str, deadline: float) -> None:
        with self._lock:
            self.cooldowns[str(route_id)] = float(deadline)

    def clear_cooldown(self, route_id: str) -> None:
        with self._lock:
            self.cooldowns.pop(str(route_id), None)

    def reset_cooldowns(self, route_id: str | None = None) -> None:
        with self._lock:
            if route_id:
                self.cooldowns.pop(str(route_id), None)
            else:
                self.cooldowns.clear()

    def quota_status(self, scope: tuple, *, now: float | None = None) -> dict[str, Any] | None:
        instant = time.monotonic() if now is None else float(now)
        with self._lock:
            entry = self.quota_blocks.get(scope)
            if not entry:
                return None
            expires_at = entry.get("expires_at")
            if expires_at is not None and float(expires_at) <= instant:
                self.quota_blocks.pop(scope, None)
                return None
            return dict(entry)

    def set_quota_block(self, scope: tuple, entry: dict[str, Any]) -> None:
        with self._lock:
            self.quota_blocks[scope] = dict(entry)

    def clear_quota_block(self, scope: tuple) -> None:
        with self._lock:
            self.quota_blocks.pop(scope, None)

    def reset_quota_blocks(self) -> None:
        with self._lock:
            self.quota_blocks.clear()
