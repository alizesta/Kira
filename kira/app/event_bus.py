"""Small in-process event bus for decoupled module notifications."""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from threading import RLock
from typing import Any


class EventBus:
    def __init__(self) -> None:
        self._subscribers: dict[str, list[Callable[..., Any]]] = defaultdict(list)
        self._lock = RLock()

    def subscribe(self, event_name: str, callback: Callable[..., Any]) -> Callable[[], None]:
        if not event_name or not callable(callback):
            raise ValueError("event_name and callable callback are required")
        with self._lock:
            if callback not in self._subscribers[event_name]:
                self._subscribers[event_name].append(callback)

        def unsubscribe() -> None:
            with self._lock:
                callbacks = self._subscribers.get(event_name, [])
                if callback in callbacks:
                    callbacks.remove(callback)
                if not callbacks:
                    self._subscribers.pop(event_name, None)

        return unsubscribe

    def publish(self, event_name: str, **payload: Any) -> None:
        with self._lock:
            callbacks = tuple(self._subscribers.get(event_name, ()))
        for callback in callbacks:
            callback(**payload)

    def clear(self, event_name: str | None = None) -> None:
        with self._lock:
            if event_name is None:
                self._subscribers.clear()
            else:
                self._subscribers.pop(event_name, None)
