"""Typed, immutable Chat notifications built on the application's shared EventBus."""
from __future__ import annotations

from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from threading import RLock
from typing import Any, TYPE_CHECKING
from uuid import uuid4

if TYPE_CHECKING:
    from ..app.event_bus import EventPublishReport, EventBus


class ChatEventType(str, Enum):
    REQUEST_SUBMITTED = "request_submitted"
    REQUEST_STARTED = "request_started"
    REQUEST_COMPLETED = "request_completed"
    REQUEST_FAILED = "request_failed"
    REQUEST_CANCELLED = "request_cancelled"

    STREAM_STARTED = "stream_started"
    STREAM_CHUNK_RECEIVED = "stream_chunk_received"
    STREAM_COMPLETED = "stream_completed"
    STREAM_INTERRUPTED = "stream_interrupted"

    SESSION_CREATED = "session_created"
    SESSION_ACTIVATED = "session_activated"
    SESSION_DEACTIVATED = "session_deactivated"
    SESSION_CLOSED = "session_closed"
    SESSION_FAILED = "session_failed"

    MESSAGE_SAVED = "message_saved"
    HISTORY_LOADED = "history_loaded"
    PERSISTENCE_FAILED = "persistence_failed"

    COMMAND_DISPATCH_STARTED = "command_dispatch_started"
    COMMAND_DISPATCH_COMPLETED = "command_dispatch_completed"
    COMMAND_DISPATCH_FAILED = "command_dispatch_failed"

    CONVERSATION_ARCHIVED = "conversation_archived"
    CONVERSATION_RESTORED = "conversation_restored"
    CONVERSATION_TRASHED = "conversation_trashed"
    CONVERSATION_RESTORED_FROM_TRASH = "conversation_restored_from_trash"
    CONVERSATION_PERMANENTLY_DELETED = "conversation_permanently_deleted"
    CONVERSATION_METADATA_UPDATED = "conversation_metadata_updated"


CHAT_EVENT_TYPES = frozenset(item.value for item in ChatEventType)


def _freeze_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, Enum):
        return _freeze_value(value.value)
    if isinstance(value, Mapping):
        frozen = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("event payload mapping keys must be strings")
            frozen[key] = _freeze_value(item)
        from types import MappingProxyType
        return MappingProxyType(frozen)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_value(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(_freeze_value(item) for item in value)
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("event payload datetimes must be timezone-aware")
        return value.astimezone(timezone.utc).isoformat()
    raise TypeError(
        f"event payload values must be JSON-like and immutable-compatible, got {type(value).__name__}"
    )


def _freeze_mapping(value: Mapping[str, Any] | None, field_name: str) -> Mapping[str, Any]:
    if value is None:
        value = {}
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be a mapping")
    frozen = _freeze_value(value)
    return frozen


@dataclass(frozen=True, slots=True)
class ChatEvent:
    event_type: ChatEventType
    event_id: str = field(default_factory=lambda: uuid4().hex)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    session_id: str | None = None
    request_id: str | None = None
    payload: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        try:
            event_type = self.event_type if isinstance(self.event_type, ChatEventType) else ChatEventType(str(self.event_type))
        except ValueError as exc:
            raise ValueError(f"unsupported Chat event type: {self.event_type!r}") from exc
        object.__setattr__(self, "event_type", event_type)

        event_id = str(self.event_id or "").strip()
        if not event_id:
            raise ValueError("event_id is required")
        object.__setattr__(self, "event_id", event_id)

        if not isinstance(self.timestamp, datetime):
            raise TypeError("timestamp must be a datetime")
        if self.timestamp.tzinfo is None or self.timestamp.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")
        object.__setattr__(self, "timestamp", self.timestamp.astimezone(timezone.utc))

        for field_name in ("session_id", "request_id"):
            value = getattr(self, field_name)
            if value is not None:
                normalized = str(value).strip()
                if not normalized:
                    raise ValueError(f"{field_name} must be non-empty when provided")
                object.__setattr__(self, field_name, normalized)

        object.__setattr__(self, "payload", _freeze_mapping(self.payload, "payload"))
        object.__setattr__(self, "metadata", _freeze_mapping(self.metadata, "metadata"))

    @classmethod
    def create(
        cls,
        event_type: ChatEventType | str,
        *,
        session_id: str | None = None,
        request_id: str | None = None,
        payload: Mapping[str, Any] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> "ChatEvent":
        return cls(
            event_type=event_type,
            session_id=session_id,
            request_id=request_id,
            payload=payload or {},
            metadata=metadata or {},
        )


@dataclass(frozen=True, slots=True)
class ChatEventDispatch:
    event: ChatEvent
    report: "EventPublishReport | None"
    duplicate: bool = False

    @property
    def delivered(self) -> int:
        return self.report.delivered if self.report is not None else 0

    @property
    def failures(self) -> tuple[Any, ...]:
        return self.report.failures if self.report is not None else ()


class ChatEventPublisher:
    """Creates ChatEvent contracts and publishes them through the shared EventBus.

    Request, stream and session terminal notifications are de-duplicated per
    lifecycle identity. The publisher owns notification bookkeeping only; it
    does not own request, queue, session or persistence state transitions.
    """

    _TERMINAL_FAMILY = {
        ChatEventType.REQUEST_COMPLETED: "request",
        ChatEventType.REQUEST_FAILED: "request",
        ChatEventType.REQUEST_CANCELLED: "request",
        ChatEventType.STREAM_COMPLETED: "stream",
        ChatEventType.STREAM_INTERRUPTED: "stream",
        ChatEventType.SESSION_CLOSED: "session",
        ChatEventType.SESSION_FAILED: "session",
        ChatEventType.COMMAND_DISPATCH_COMPLETED: "command",
        ChatEventType.COMMAND_DISPATCH_FAILED: "command",
    }

    def __init__(self, event_bus: "EventBus", *, terminal_history_limit: int = 8192):
        if event_bus is None or not callable(getattr(event_bus, "publish_event", None)):
            raise TypeError("a shared EventBus with publish_event() is required")
        if terminal_history_limit < 1:
            raise ValueError("terminal_history_limit must be positive")
        self._event_bus = event_bus
        self._terminal_history_limit = int(terminal_history_limit)
        self._terminal_events: OrderedDict[tuple[str, ...], str] = OrderedDict()
        self._lock = RLock()

    def subscribe(
        self, event_type: ChatEventType | str, callback
    ):
        """Subscribe to typed immutable events; returned function releases the subscription."""
        return self._event_bus.subscribe_event(event_type, callback)

    def publish(
        self,
        event_type: ChatEventType | str,
        *,
        session_id: str | None = None,
        request_id: str | None = None,
        payload: Mapping[str, Any] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> ChatEventDispatch:
        event = ChatEvent.create(
            event_type,
            session_id=session_id,
            request_id=request_id,
            payload=payload,
            metadata=metadata,
        )

        with self._lock:
            if event.event_type is ChatEventType.SESSION_CREATED and event.session_id:
                self._terminal_events.pop(("session", event.session_id), None)

            key = self._terminal_key(event)
            if key is not None and key in self._terminal_events:
                return ChatEventDispatch(event=event, report=None, duplicate=True)
            if key is not None:
                self._terminal_events[key] = event.event_id
                self._terminal_events.move_to_end(key)
                while len(self._terminal_events) > self._terminal_history_limit:
                    self._terminal_events.popitem(last=False)

        report = self._event_bus.publish_event(event)
        return ChatEventDispatch(event=event, report=report)

    def _terminal_key(self, event: ChatEvent) -> tuple[str, ...] | None:
        family = self._TERMINAL_FAMILY.get(event.event_type)
        if family is None:
            return None
        if family == "session":
            return (family, event.session_id) if event.session_id else None
        if event.session_id and event.request_id:
            if family == "stream":
                provider_request_id = (
                    event.payload.get("provider_request_id")
                    or event.metadata.get("provider_request_id")
                )
                if provider_request_id:
                    return (family, event.session_id, event.request_id, str(provider_request_id))
            return (family, event.session_id, event.request_id)
        return None

    def clear_terminal_history(self) -> None:
        """Release terminal de-duplication state, e.g. during application shutdown."""
        with self._lock:
            self._terminal_events.clear()
