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
                self._instance = instance
            return self._instance

    @property
    def tasks(self) -> _LazyTaskStore:
        return self._tasks_proxy

    def is_task_running(self, *args: Any, **kwargs: Any) -> bool:
        """Keep callback registration cheap; instantiate only when the callback is invoked."""
        return bool(self._get().is_task_running(*args, **kwargs))

    def __getattr__(self, name: str) -> Any:
        return getattr(self._get(), name)
