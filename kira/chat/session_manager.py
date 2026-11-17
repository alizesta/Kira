"""Qt-free lifecycle and state management for chat sessions."""
from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from threading import RLock
from typing import Any
from uuid import uuid4


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class SessionStatus(str, Enum):
    CREATED = "created"
    ACTIVE = "active"
    IDLE = "idle"
    CLOSING = "closing"
    CLOSED = "closed"
    FAILED = "failed"


class SessionLifecycleError(RuntimeError):
    """Raised when a lifecycle operation cannot be completed safely."""


@dataclass(frozen=True)
class SessionStateChanged:
    session_id: str
    character_id: str
    previous_status: str | None
    status: str
    updated_at: str


class _CharacterSessionView(Mapping[str, Any]):
    """Live, read-only character-to-Session compatibility view."""

    def __init__(self, manager: "SessionManager") -> None:
        self._manager = manager

    def __getitem__(self, character_id: str) -> Any:
        session = self._manager.get_session_for_character(character_id)
        if session is None:
            raise KeyError(character_id)
        return session

    def __iter__(self) -> Iterator[str]:
        return iter(self._manager.character_ids())

    def __len__(self) -> int:
        return len(self._manager.character_ids())


class SessionManager:
    """Thread-safe owner of in-memory chat Session lifecycle.

    Durable conversation identity and message history belong to Persistence.
    This manager deliberately has no Persistence dependency; the application
    layer binds a conversation_id to the runtime Session after creation.

    Closing uses graceful drain. New activation is rejected while already
    admitted work completes. The injected disposer releases external resources
    without importing or depending on Qt here.
    """

    _ALLOWED = {
        SessionStatus.CREATED.value: {
            SessionStatus.ACTIVE.value, SessionStatus.IDLE.value,
            SessionStatus.CLOSING.value, SessionStatus.FAILED.value,
        },
        SessionStatus.ACTIVE.value: {
            SessionStatus.IDLE.value, SessionStatus.CLOSING.value,
            SessionStatus.FAILED.value,
        },
        SessionStatus.IDLE.value: {
            SessionStatus.ACTIVE.value, SessionStatus.CLOSING.value,
            SessionStatus.FAILED.value,
        },
        SessionStatus.CLOSING.value: {
            SessionStatus.IDLE.value, SessionStatus.CLOSED.value,
            SessionStatus.FAILED.value,
        },
        SessionStatus.FAILED.value: {SessionStatus.CLOSING.value},
        SessionStatus.CLOSED.value: set(),
    }

    def __init__(
        self,
        session_factory: Callable[..., Any],
        *,
        has_pending_work: Callable[[Any], bool] | None = None,
        dispose_callback: Callable[[Any], None] | None = None,
    ) -> None:
        if not callable(session_factory):
            raise TypeError("session_factory must be callable")
        self._session_factory = session_factory
        self._has_pending_work = has_pending_work or (lambda _session: False)
        self._dispose_callback = dispose_callback
        self._lock = RLock()
        self._sessions: dict[str, Any] = {}
        self._by_character: dict[str, str] = {}
        self._active_session_id: str | None = None
        self._listeners: set[Callable[[SessionStateChanged], None]] = set()
        self._finalizing: set[str] = set()
        self._closed_ids: set[str] = set()
        self._disposing = False
        self._disposed = False
        self._character_view = _CharacterSessionView(self)

    @property
    def sessions_by_character(self) -> Mapping[str, Any]:
        """Live, read-only registry retained for legacy composition adapters."""
        return self._character_view

    @property
    def active_session_id(self) -> str | None:
        with self._lock:
            return self._active_session_id

    @property
    def is_disposed(self) -> bool:
        with self._lock:
            return self._disposed

    def set_runtime_callbacks(
        self,
        *,
        has_pending_work: Callable[[Any], bool] | None = None,
        dispose_callback: Callable[[Any], None] | None = None,
    ) -> None:
        """Inject application-specific work inspection and resource cleanup."""
        if has_pending_work is not None and not callable(has_pending_work):
            raise TypeError("has_pending_work must be callable")
        if dispose_callback is not None and not callable(dispose_callback):
            raise TypeError("dispose_callback must be callable")
        with self._lock:
            if self._disposed or self._disposing:
                raise SessionLifecycleError("SessionManager is shutting down")
            if has_pending_work is not None:
                self._has_pending_work = has_pending_work
            if dispose_callback is not None:
                self._dispose_callback = dispose_callback

    @staticmethod
    def _character_id(value: str) -> str:
        character_id = str(value or "").strip().lower()
        if not character_id:
            raise ValueError("character_id is required")
        return character_id

    def _transition_locked(
        self, session: Any, target: SessionStatus
    ) -> SessionStateChanged | None:
        current = str(getattr(session, "status", SessionStatus.CREATED.value))
        target_value = target.value
        if current == target_value:
            return None
        if target_value not in self._ALLOWED.get(current, set()):
            raise SessionLifecycleError(
                f"Invalid Session transition: {current} -> {target_value}"
            )
        updated_at = _now()
        session.status = target_value
        session.updated_at = updated_at
        return SessionStateChanged(
            session_id=str(session.session_id),
            character_id=str(session.cid),
            previous_status=current,
            status=target_value,
            updated_at=updated_at,
        )

    def _publish(self, events: list[SessionStateChanged]) -> None:
        if not events:
            return
        with self._lock:
            listeners = tuple(self._listeners)
        for event in events:
            for listener in listeners:
                try:
                    listener(event)
                except Exception:
                    continue

    def subscribe(
        self, listener: Callable[[SessionStateChanged], None]
    ) -> Callable[[], bool]:
        if not callable(listener):
            raise TypeError("listener must be callable")
        with self._lock:
            if self._disposed or self._disposing:
                raise SessionLifecycleError("SessionManager is shutting down")
            self._listeners.add(listener)

        def unsubscribe() -> bool:
            with self._lock:
                if listener not in self._listeners:
                    return False
                self._listeners.remove(listener)
                return True

        return unsubscribe

    def create_session(
        self,
        character_id: str,
        *,
        session_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> Any:
        """Create or return the one live runtime Session for a character."""
        cid = self._character_id(character_id)
        with self._lock:
            if self._disposing or self._disposed:
                raise SessionLifecycleError("SessionManager is shutting down")
            existing_id = self._by_character.get(cid)
            existing = self._sessions.get(existing_id) if existing_id else None
            if existing is not None and existing.status != SessionStatus.CLOSED.value:
                if existing.status == SessionStatus.CLOSING.value:
                    raise SessionLifecycleError(
                        f"Session for {cid!r} is closing and cannot be replaced"
                    )
                return existing

            sid = str(session_id or uuid4())
            if not sid.strip() or sid in self._sessions or sid in self._closed_ids:
                raise ValueError("session_id must be a new, non-empty identifier")

            session = self._session_factory(cid, session_id=sid)
            if str(getattr(session, "session_id", "")) != sid:
                raise SessionLifecycleError(
                    "session_factory must preserve the requested immutable session_id"
                )
            created_at = _now()
            session.cid = cid
            session.character_id = cid
            session.status = SessionStatus.CREATED.value
            session.created_at = created_at
            session.updated_at = created_at
            session.metadata = dict(metadata or {})
            session.last_error = None
            self._sessions[sid] = session
            self._by_character[cid] = sid
            event = SessionStateChanged(
                session_id=sid,
                character_id=cid,
                previous_status=None,
                status=SessionStatus.CREATED.value,
                updated_at=created_at,
            )
        self._publish([event])
        return session

    def get_session(self, session_id: str) -> Any | None:
        with self._lock:
            return self._sessions.get(str(session_id))

    def get_session_for_character(self, character_id: str) -> Any | None:
        cid = self._character_id(character_id)
        with self._lock:
            session_id = self._by_character.get(cid)
            return self._sessions.get(session_id) if session_id else None

    def get_active_session(self) -> Any | None:
        with self._lock:
            if self._active_session_id is None:
                return None
            return self._sessions.get(self._active_session_id)

    def character_ids(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(
                cid for cid, sid in self._by_character.items()
                if sid in self._sessions
            )

    def list_sessions(self, *, include_closed: bool = False) -> tuple[Any, ...]:
        with self._lock:
            sessions = tuple(self._sessions.values())
        if include_closed:
            return sessions
        return tuple(
            session for session in sessions
            if session.status != SessionStatus.CLOSED.value
        )

    def activate_session(self, session_id: str) -> bool:
        """Activate a Session and atomically idle the previously active one."""
        events: list[SessionStateChanged] = []
        sid = str(session_id)
        with self._lock:
            target = self._sessions.get(sid)
            if target is None or target.status not in (
                SessionStatus.CREATED.value, SessionStatus.IDLE.value,
                SessionStatus.ACTIVE.value,
            ):
                return False
            if self._active_session_id == sid and target.status == SessionStatus.ACTIVE.value:
                return True

            previous = self._sessions.get(self._active_session_id) if self._active_session_id else None
            if previous is not None and previous is not target:
                event = self._transition_locked(previous, SessionStatus.IDLE)
                if event:
                    events.append(event)
            event = self._transition_locked(target, SessionStatus.ACTIVE)
            if event:
                events.append(event)
            self._active_session_id = sid
        self._publish(events)
        return True

    def deactivate_session(self, session_id: str) -> bool:
        """Deactivate a Session; repeated deactivation of an idle Session is safe."""
        sid = str(session_id)
        events: list[SessionStateChanged] = []
        with self._lock:
            session = self._sessions.get(sid)
            if session is None:
                return sid in self._closed_ids
            status = session.status
            if status == SessionStatus.IDLE.value:
                return True
            if status not in (SessionStatus.CREATED.value, SessionStatus.ACTIVE.value):
                return False
            event = self._transition_locked(session, SessionStatus.IDLE)
            if event:
                events.append(event)
            if self._active_session_id == sid:
                self._active_session_id = None
        self._publish(events)
        return True

    def reopen_session(self, session_id: str) -> bool:
        """Cancel a pending graceful close when its character becomes valid again."""
        sid = str(session_id)
        events: list[SessionStateChanged] = []
        with self._lock:
            session = self._sessions.get(sid)
            if session is None or sid in self._finalizing:
                return False
            if session.status in (SessionStatus.CREATED.value, SessionStatus.IDLE.value):
                self._by_character[session.cid] = sid
                return True
            if session.status != SessionStatus.CLOSING.value:
                return False
            if self._by_character.get(session.cid) not in (None, sid):
                return False
            event = self._transition_locked(session, SessionStatus.IDLE)
            if event:
                events.append(event)
            self._by_character[session.cid] = sid
        self._publish(events)
        return True

    def fail_session(self, session_id: str, error: BaseException | str) -> bool:
        """Mark a live Session failed and retain its diagnostic for the caller."""
        sid = str(session_id)
        events: list[SessionStateChanged] = []
        with self._lock:
            session = self._sessions.get(sid)
            if session is None or session.status == SessionStatus.CLOSED.value:
                return False
            if session.status == SessionStatus.FAILED.value:
                session.last_error = str(error)
                return True
            event = self._transition_locked(session, SessionStatus.FAILED)
            session.last_error = str(error)
            if self._active_session_id == sid:
                self._active_session_id = None
            if event:
                events.append(event)
        self._publish(events)
        return True

    def close_session(self, session_id: str) -> bool:
        """Gracefully close a Session, returning False while owned work is draining."""
        sid = str(session_id)
        events: list[SessionStateChanged] = []
        with self._lock:
            session = self._sessions.get(sid)
            if session is None:
                return sid in self._closed_ids
            if session.status == SessionStatus.CLOSED.value:
                return True
            if sid in self._finalizing:
                return False
            if session.status != SessionStatus.CLOSING.value:
                event = self._transition_locked(session, SessionStatus.CLOSING)
                if event:
                    events.append(event)
            if self._active_session_id == sid:
                self._active_session_id = None
            self._finalizing.add(sid)
            pending_check = self._has_pending_work
            disposer = self._dispose_callback
        self._publish(events)

        try:
            pending = bool(pending_check(session))
        except Exception as exc:
            session.last_error = f"pending-work check failed: {type(exc).__name__}: {exc}"
            with self._lock:
                self._finalizing.discard(sid)
            return False
        if pending:
            with self._lock:
                self._finalizing.discard(sid)
            return False

        try:
            if disposer is not None:
                disposer(session)
        except Exception as exc:
            with self._lock:
                session.last_error = f"resource disposal failed: {type(exc).__name__}: {exc}"
                event = self._transition_locked(session, SessionStatus.FAILED)
                self._finalizing.discard(sid)
            self._publish([event] if event else [])
            return False

        with self._lock:
            self._finalizing.discard(sid)
            if session.status != SessionStatus.CLOSING.value:
                return False
            event = self._transition_locked(session, SessionStatus.CLOSED)
            self._by_character.pop(session.cid, None)
            self._closed_ids.add(sid)
        self._publish([event] if event else [])
        return True

    def dispose(self) -> bool:
        """Drain and close every Session; safe to call more than once."""
        with self._lock:
            if self._disposed:
                return True
            self._disposing = True
            session_ids = tuple(self._sessions)
        complete = True
        for session_id in session_ids:
            if not self.close_session(session_id):
                complete = False
        with self._lock:
            if not complete or any(
                session.status != SessionStatus.CLOSED.value
                for session in self._sessions.values()
            ):
                return False
            self._sessions.clear()
            self._by_character.clear()
            self._active_session_id = None
            self._listeners.clear()
            self._disposed = True
            return True
