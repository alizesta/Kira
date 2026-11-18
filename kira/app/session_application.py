"""Application policy for per-character chat sessions.

This service owns session/conversation binding, character-profile synchronization,
and lifecycle event translation. Qt resource construction remains an injected UI
adapter so the service stays independent of the desktop toolkit.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any


class SessionApplicationService:
    """Coordinate runtime Session lifecycle with durable Chat conversations."""

    _EVENT_TYPES = {
        "created": "session_created",
        "active": "session_activated",
        "idle": "session_deactivated",
        "closed": "session_closed",
        "failed": "session_failed",
    }

    def __init__(
        self,
        session_manager: Any,
        chat_application_service: Any,
        event_publisher: Any | None = None,
    ) -> None:
        if session_manager is None:
            raise TypeError("session_manager is required")
        if chat_application_service is None:
            raise TypeError("chat_application_service is required")
        self.session_manager = session_manager
        self.chat_application_service = chat_application_service
        self.event_publisher = event_publisher
        self._unsubscribe = (
            self.session_manager.subscribe(self.publish_state_change)
            if self.event_publisher is not None else None
        )

    def create_active_session(self, character_id: str) -> Any:
        """Create the initial runtime Session and make it the active conversation."""
        session = self.session_manager.create_session(character_id)
        if not self.session_manager.activate_session(session.session_id):
            self.session_manager.close_session(session.session_id)
            raise RuntimeError(f"Could not activate initial Session for {character_id!r}")
        return session

    def activate_session(self, session_id: str) -> bool:
        """Apply the canonical SessionManager activation transition."""
        return self.session_manager.activate_session(session_id)

    def list_sessions(self) -> tuple[Any, ...]:
        """Return the manager's stable Session snapshot for shutdown coordination."""
        return self.session_manager.list_sessions()

    def dispose(self) -> bool:
        """Dispose runtime Sessions and release this service's event subscription."""
        if not self.session_manager.dispose():
            return False
        unsubscribe, self._unsubscribe = self._unsubscribe, None
        if callable(unsubscribe):
            unsubscribe()
        return True

    def bind_conversation(self, session: Any) -> str | None:
        """Bind a runtime Session to durable history without blocking on storage failure."""
        existing = getattr(session, "conversation_id", None)
        if existing:
            return existing
        try:
            record = self.chat_application_service.get_or_create_conversation(session.cid)
            conversation_id = (
                record.get("id") or record.get("conversation_id")
                if isinstance(record, dict) else None
            )
            session.conversation_id = str(conversation_id) if conversation_id else None
        except Exception:
            session.conversation_id = None
        return session.conversation_id

    def publish_state_change(self, event: Any) -> None:
        """Translate SessionManager state transitions into shared application events."""
        if self.event_publisher is None:
            return
        event_type = self._EVENT_TYPES.get(str(event.status))
        if event_type is None:
            return
        try:
            self.event_publisher.publish(
                event_type,
                session_id=event.session_id,
                payload={
                    "character_id": event.character_id,
                    "previous_status": event.previous_status,
                    "status": event.status,
                },
            )
        except Exception:
            return

    def publish_history_loaded(self, session: Any) -> None:
        """Publish a best-effort notification after a character history is restored."""
        if self.event_publisher is None:
            return
        try:
            self.event_publisher.publish(
                "history_loaded",
                session_id=session.session_id,
                payload={
                    "character_id": session.cid,
                    "conversation_id": session.conversation_id,
                },
            )
        except Exception:
            return

    def ensure_session(
        self,
        character_id: str,
        profile: Mapping[str, Any],
        *,
        ensure_resources: Callable[[Any, Mapping[str, Any]], None],
    ) -> Any | None:
        """Resolve/reopen/create one character Session, then ask the UI to attach resources."""
        session = self.session_manager.get_session_for_character(character_id)
        if session is not None and session.status == "closing":
            if not self.session_manager.reopen_session(session.session_id):
                return None
        elif session is not None and session.status == "failed":
            if not self.session_manager.close_session(session.session_id):
                return None
            session = None
        if session is None:
            session = self.session_manager.create_session(character_id)
        self.bind_conversation(session)
        ensure_resources(session, profile)
        return session

    def sync_sessions(
        self,
        profiles: Mapping[str, Mapping[str, Any]],
        *,
        ensure_resources: Callable[[Any, Mapping[str, Any]], None],
        restore_history: Callable[[Any], None],
        vision_session: Any | None = None,
        vision_worker: Any | None = None,
    ) -> tuple[str, ...]:
        """Synchronize runtime Sessions with character profiles and drain deleted profiles."""
        order = [
            character_id
            for character_id in ("kira", "ren", "mika")
            if character_id in profiles
        ]
        order.extend(
            character_id
            for character_id in profiles
            if character_id not in ("kira", "ren", "mika")
        )
        for character_id in order:
            session = self.ensure_session(
                character_id,
                profiles[character_id],
                ensure_resources=ensure_resources,
            )
            if session is None:
                continue
            if not session.loaded:
                try:
                    restored = restore_history(session)
                except Exception:
                    # A transient history/storage failure must not permanently mark
                    # this Session as loaded; a later synchronization can retry.
                    continue
                if restored is False:
                    continue
                session.loaded = True
                self.publish_history_loaded(session)

        sessions = self.session_manager.sessions_by_character
        order.extend(character_id for character_id in sessions if character_id not in order)
        for character_id, session in tuple(sessions.items()):
            if character_id in profiles:
                continue
            if self.has_pending_work(
                session,
                vision_session=vision_session,
                vision_worker=vision_worker,
            ):
                continue
            self.close_session(session)
        return tuple(order)

    @staticmethod
    def worker_is_running(worker: Any | None) -> bool:
        if worker is None:
            return False
        try:
            return bool(worker.isRunning())
        except RuntimeError:
            return False

    def has_pending_work(
        self,
        session: Any,
        *,
        vision_session: Any | None = None,
        vision_worker: Any | None = None,
    ) -> bool:
        """Check application requests and owned worker activity before graceful close."""
        if (
            session.busy
            or self.chat_application_service.has_active_request(session.session_id)
            or self.chat_application_service.has_pending_work(session.session_id)
        ):
            return True
        if self.worker_is_running(getattr(session, "worker", None)) or self.worker_is_running(
            getattr(session, "_search_worker", None)
        ):
            return True
        return vision_session is session and self.worker_is_running(vision_worker)

    def close_session(self, session: Any) -> bool:
        """Delegate graceful lifecycle closure to the canonical SessionManager."""
        return self.session_manager.close_session(session.session_id)
