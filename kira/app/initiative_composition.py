"""Composition factory for the window-scoped Initiative application service."""
from __future__ import annotations

from typing import Any, Callable

from .initiative_application import InitiativeApplicationService


def create_initiative_application_service_factory(
    *, memory_service: Any, mood_service: Any
) -> Callable[[Any], InitiativeApplicationService]:
    """Bind application-wide memory/mood services to a window's Chat application."""
    def create(chat_application_service: Any) -> InitiativeApplicationService:
        return InitiativeApplicationService(
            memory_service=memory_service,
            mood_service=mood_service,
            chat_application_service=chat_application_service,
        )

    return create
