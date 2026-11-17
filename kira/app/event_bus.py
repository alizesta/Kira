"""Thread-safe in-process notification bus shared by application modules.

The legacy keyword-payload API remains supported. Typed chat notifications use
subscribe_event() / publish_event() on this same bus; no parallel event bus is
created.
"""
from __future__ import annotations

import logging
from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass, field
from threading import Condition, Event as ThreadEvent, RLock, get_ident
from typing import Any


_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SubscriberFailure:
    event_name: str
    callback: Callable[..., Any]
    error: Exception


@dataclass(frozen=True, slots=True)
class EventPublishReport:
    event_name: str
    sequence: int
    delivered: int
    failures: tuple[SubscriberFailure, ...] = ()
    queued: bool = False


@dataclass(eq=False, slots=True)
class _Subscriber:
    callback: Callable[..., Any]
    receives_event: bool = False


@dataclass(slots=True)
class _PendingPublication:
    event_name: str
    payload: dict[str, Any]
    sequence: int
    chat_event: Any | None = None
    completed: ThreadEvent = field(default_factory=ThreadEvent)
    report: EventPublishReport | None = None


class EventBus:
    """One ordered in-process notification channel for all application modules.

    Subscriber changes are protected by a lock and callbacks run outside that
    lock. Publications are serialized through a FIFO queue. A callback may
    publish another event: that event is queued until every subscriber has
    received the current event, avoiding re-entrant delivery and deadlocks.
    Concurrent publishers wait for their own delivery report.
    """

    def __init__(self) -> None:
        self._subscribers: dict[str, list[_Subscriber]] = defaultdict(list)
        self._condition = Condition(RLock())
        self._pending: deque[_PendingPublication] = deque()
        self._sequence = 0
        self._dispatching = False
        self._dispatcher_thread: int | None = None
        self._closed = False

    @staticmethod
    def _event_name(event_name: Any) -> str:
        value = getattr(event_name, "value", event_name)
        name = str(value or "").strip()
        if not name:
            raise ValueError("event_name is required")
        return name

    @staticmethod
    def _same_callback(left: Callable[..., Any], right: Callable[..., Any]) -> bool:
        if left is right:
            return True
        try:
            return bool(left == right)
        except Exception:
            return False

    def subscribe(self, event_name: str, callback: Callable[..., Any]) -> Callable[[], None]:
        """Subscribe to legacy keyword-payload events."""
        return self._subscribe(event_name, callback, receives_event=False)

    def subscribe_event(self, event_type: Any, callback: Callable[[Any], Any]) -> Callable[[], None]:
        """Subscribe to typed ChatEvent instances published on this same bus."""
        return self._subscribe(event_type, callback, receives_event=True)

    def _subscribe(
        self, event_name: Any, callback: Callable[..., Any], *, receives_event: bool
    ) -> Callable[[], None]:
        name = self._event_name(event_name)
        if not callable(callback):
            raise ValueError("a callable callback is required")
        with self._condition:
            if self._closed:
                raise RuntimeError("EventBus is closed")
            subscribers = self._subscribers[name]
            for existing in subscribers:
                if existing.receives_event == receives_event and self._same_callback(existing.callback, callback):
                    return self._unsubscribe_callback(name, existing)
            subscriber = _Subscriber(callback, receives_event)
            subscribers.append(subscriber)
            return self._unsubscribe_callback(name, subscriber)

    def _unsubscribe_callback(self, event_name: str, subscriber: _Subscriber) -> Callable[[], None]:
        removed = False

        def unsubscribe() -> None:
            nonlocal removed
            with self._condition:
                if removed:
                    return
                removed = True
                current = self._subscribers.get(event_name)
                if current is None:
                    return
                try:
                    current.remove(subscriber)
                except ValueError:
                    return
                if not current:
                    self._subscribers.pop(event_name, None)

        return unsubscribe

    def publish(self, event_name: str, **payload: Any) -> EventPublishReport:
        """Publish a legacy event with keyword payload (backward compatible)."""
        return self._enqueue(event_name, dict(payload), chat_event=None)

    def publish_event(self, event: Any) -> EventPublishReport:
        """Publish one immutable ChatEvent through the shared application bus."""
        from ..chat.events import ChatEvent

        if not isinstance(event, ChatEvent):
            raise TypeError("event must be a ChatEvent")
        event_name = self._event_name(event.event_type)
        payload = {
            "event": event,
            "event_id": event.event_id,
            "event_type": event.event_type.value,
            "timestamp": event.timestamp,
            "session_id": event.session_id,
            "request_id": event.request_id,
            "payload": event.payload,
            "metadata": event.metadata,
        }
        return self._enqueue(event_name, payload, chat_event=event)

    def _enqueue(
        self, event_name: Any, payload: dict[str, Any], *, chat_event: Any | None
    ) -> EventPublishReport:
        name = self._event_name(event_name)
        publication = None
        should_drain = False
        current_thread = get_ident()

        with self._condition:
            if self._closed:
                raise RuntimeError("EventBus is closed")
            self._sequence += 1
            publication = _PendingPublication(name, payload, self._sequence, chat_event)
            self._pending.append(publication)
            if not self._dispatching:
                self._dispatching = True
                self._dispatcher_thread = current_thread
                should_drain = True
            elif self._dispatcher_thread == current_thread:
                # Nested publication is delivered after the current fan-out.
                return EventPublishReport(name, publication.sequence, 0, queued=True)

        if should_drain:
            self._drain()
        else:
            publication.completed.wait()

        return publication.report or EventPublishReport(
            name, publication.sequence, 0, queued=True
        )

    def _drain(self) -> None:
        while True:
            with self._condition:
                if not self._pending:
                    self._dispatching = False
                    self._dispatcher_thread = None
                    self._condition.notify_all()
                    return
                publication = self._pending.popleft()
                subscribers = tuple(self._subscribers.get(publication.event_name, ()))

            delivered = 0
            failures: list[SubscriberFailure] = []
            for subscriber in subscribers:
                try:
                    if subscriber.receives_event:
                        if publication.chat_event is None:
                            continue
                        subscriber.callback(publication.chat_event)
                    else:
                        subscriber.callback(**publication.payload)
                    delivered += 1
                except Exception as exc:
                    failures.append(
                        SubscriberFailure(publication.event_name, subscriber.callback, exc)
                    )
                    _LOGGER.exception(
                        "Event subscriber failed: event=%s callback=%r",
                        publication.event_name,
                        subscriber.callback,
                    )

            report = EventPublishReport(
                publication.event_name,
                publication.sequence,
                delivered,
                tuple(failures),
            )
            with self._condition:
                publication.report = report
                publication.completed.set()

    def subscriber_count(self, event_name: str | None = None) -> int:
        with self._condition:
            if event_name is None:
                return sum(len(items) for items in self._subscribers.values())
            return len(self._subscribers.get(self._event_name(event_name), ()))

    def clear(self, event_name: str | None = None) -> None:
        """Remove subscribers; current fan-out snapshots are allowed to finish."""
        with self._condition:
            if event_name is None:
                self._subscribers.clear()
            else:
                self._subscribers.pop(self._event_name(event_name), None)

    def close(self) -> None:
        """Release all subscriptions and reject future publications/subscriptions."""
        with self._condition:
            if self._closed:
                return
            self._closed = True
            self._subscribers.clear()
