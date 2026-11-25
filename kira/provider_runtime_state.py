"""Router-scoped health, cooldown and quota state for hybrid provider execution."""
from __future__ import annotations
import threading
import time
from typing import Any

class ProviderRuntimeState:
    """Own transient state; related routers may deliberately share this owner."""
    def __init__(self, *, states=None, cooldowns=None, quota_blocks=None) -> None:
        self.cooldowns = cooldowns if isinstance(cooldowns, dict) else {}
        self.quota_blocks = quota_blocks if isinstance(quota_blocks, dict) else {}
        self.states = states if isinstance(states, dict) else {}
        self._lock = threading.RLock()

    @staticmethod
    def _defaults() -> dict[str, Any]:
        return {"health": "unknown", "last_error": None, "last_ms": None,
                "latency_ms": None, "last_ok_at": None, "last_attempt_at": None,
                "failures": 0, "last_kind": None, "retryable": None,
                "failure_class": None, "model_failures": 0}

    def state_for(self, route_id: str) -> dict[str, Any]:
        with self._lock:
            return self.states.setdefault(str(route_id), self._defaults())

    def state_snapshot(self, route_id: str) -> dict[str, Any]:
        with self._lock:
            return dict(self.states.setdefault(str(route_id), self._defaults()))

    def update_state(self, route_id: str, values=None, *, increments=None) -> dict[str, Any]:
        with self._lock:
            state = self.states.setdefault(str(route_id), self._defaults())
            if values:
                state.update(values)
            for key, amount in (increments or {}).items():
                state[key] = int(state.get(key, 0) or 0) + int(amount)
            return dict(state)

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
