"""Core-owned structural ports shared by application services.

These contracts describe capabilities at layer boundaries without importing
concrete Chat, Session, EventBus, Qt, or persistence implementations.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class RuntimeSessionPort(Protocol):
    """Minimal runtime Session data consumed by application orchestration."""

    session_id: str
    cid: str
    status: str
    conversation_id: str | None
    loaded: bool
    busy: bool
    worker: Any | None
    _search_worker: Any | None


@runtime_checkable
class SessionStateEventPort(Protocol):
    """Immutable state-transition notification emitted by Session ownership."""

    session_id: str
    character_id: str
    previous_status: str | None
    status: str


@runtime_checkable
class SessionManagerPort(Protocol):
    """Runtime Session lifecycle operations required by application services."""

    @property
    def sessions_by_character(self) -> Mapping[str, RuntimeSessionPort]: ...

    def subscribe(
        self, listener: Callable[[SessionStateEventPort], None]
    ) -> Callable[[], bool]: ...

    def create_session(self, character_id: str) -> RuntimeSessionPort: ...

    def get_session_for_character(
        self, character_id: str
    ) -> RuntimeSessionPort | None: ...

    def activate_session(self, session_id: str) -> bool: ...

    def reopen_session(self, session_id: str) -> bool: ...

    def close_session(self, session_id: str) -> bool: ...

    def list_sessions(self) -> tuple[RuntimeSessionPort, ...]: ...

    def dispose(self) -> bool: ...


@runtime_checkable
class ChatApplicationPort(Protocol):
    """Chat use cases required by Session lifecycle orchestration."""

    def get_or_create_conversation(self, character_id: str) -> Mapping[str, Any]: ...

    def has_active_request(self, session_id: str) -> bool: ...

    def has_pending_work(self, session_id: str) -> bool: ...


@runtime_checkable
class ApplicationEventPublisherPort(Protocol):
    """Notification-only publisher; it is not a request/response service locator."""

    def publish(self, event_type: str, **payload: Any) -> Any: ...
