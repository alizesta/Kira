"""Thread-safe lazy facade for the optional desktop ToolAgent."""
from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any


class _LazyTaskStore:
    def __init__(self, owner: "LazyToolAgent") -> None:
        self._owner = owner

    def active(self, *args: Any, **kwargs: Any) -> Any:
        return self._owner._get().tasks.active(*args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._owner._get().tasks, name)


class LazyToolAgent:
    """Delay importing and constructing ToolAgent until a real capability is used."""

    def __init__(self, factory: Callable[[], Any]) -> None:
        if not callable(factory):
            raise TypeError("factory must be callable")
        self._factory = factory
        self._instance = None
        self._lock = threading.Lock()
        self._pending_settings = None
        self._pending_competitive_safe_mode = None
        self._tasks_proxy = _LazyTaskStore(self)

    def _get(self) -> Any:
        instance = self._instance
        if instance is not None:
            return instance
        with self._lock:
            if self._instance is None:
                instance = self._factory()
                if instance is None:
                    raise RuntimeError("ToolAgent factory returned None")
                if self._pending_settings is not None:
                    instance.set_settings(self._pending_settings)
                if self._pending_competitive_safe_mode is not None:
                    instance.set_competitive_safe_mode(self._pending_competitive_safe_mode)
                self._instance = instance
            return self._instance

    @property
    def tasks(self) -> _LazyTaskStore:
        return self._tasks_proxy

    def set_settings(self, settings: dict[str, Any]) -> None:
        """Update settings without realizing the agent when startup has not needed it yet."""
        with self._lock:
            if self._instance is None:
                self._pending_settings = settings
                return
            instance = self._instance
        instance.set_settings(settings)

    def set_competitive_safe_mode(self, enabled: bool) -> None:
        """Preserve the active Game Mode restriction even before the agent is realized."""
        with self._lock:
            self._pending_competitive_safe_mode = bool(enabled)
            instance = self._instance
        if instance is not None:
            instance.set_competitive_safe_mode(bool(enabled))

    def request_cancel(self, *args: Any, **kwargs: Any) -> bool:
        """A not-yet-created agent has no running requests to cancel."""
        instance = self._instance
        return bool(instance.request_cancel(*args, **kwargs)) if instance is not None else False

    def clear_session(self, *args: Any, **kwargs: Any) -> Any:
        """An explicit clear request also clears durable task history, so realize the owner."""
        return self._get().clear_session(*args, **kwargs)

    def release_session(self, *args: Any, **kwargs: Any) -> bool:
        """Do not construct tool infrastructure merely to release nonexistent state."""
        instance = self._instance
        return bool(instance.release_session(*args, **kwargs)) if instance is not None else False

    def is_task_running(self, *args: Any, **kwargs: Any) -> bool:
        """Keep callback registration cheap; instantiate only when the callback is invoked."""
        return bool(self._get().is_task_running(*args, **kwargs))

    def __getattr__(self, name: str) -> Any:
        return getattr(self._get(), name)
