"""Bootstrap factory for the Qt-free session application service."""
from __future__ import annotations

from typing import Any, Callable

from .session_application import SessionApplicationService


def create_session_application_service_factory(
    *, event_publisher: Any | None = None
) -> Callable[[Any, Any], SessionApplicationService]:
    """Bind shared event publishing and return a factory for runtime services."""
    def create(session_manager: Any, chat_application_service: Any) -> SessionApplicationService:
        return SessionApplicationService(
            session_manager=session_manager,
            chat_application_service=chat_application_service,
            event_publisher=event_publisher,
        )

    return create
