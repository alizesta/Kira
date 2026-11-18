"""Factories for application-level Chat dependencies.

The application layer receives explicit callback ports. It never imports or
receives a concrete MainWindow instance.
"""
from __future__ import annotations

from typing import Any, Callable

from ..core.interfaces.application_ports import ChatApplicationPorts


def create_chat_application_service_factory(
    *, persistence: Any, event_publisher: Any | None = None
) -> Callable[[ChatApplicationPorts], Any]:
    """Return a factory bound to bootstrap-owned persistence and event ports."""
    if persistence is None:
        raise TypeError("persistence is required")

    def create(ports: ChatApplicationPorts) -> Any:
        if not isinstance(ports, ChatApplicationPorts):
            raise TypeError("ports must be ChatApplicationPorts")
        from ..chat.application_service import ChatApplicationService
        from ..chat.conversation_lifecycle import ConversationLifecycleService
        from ..personality import build_system_prompt

        return ChatApplicationService(
            persistence=persistence,
            system_prompt_builder=build_system_prompt,
            prompt_enricher=ports.prompt_enricher,
            worker_factory=ports.worker_factory,
            on_dispatch=ports.on_dispatch,
            on_event=ports.on_event,
            event_publisher=event_publisher,
            conversation_lifecycle=(
                ConversationLifecycleService(persistence, event_publisher)
                if event_publisher is not None else None
            ),
            schedule=ports.schedule,
            cancel_provider=ports.cancel_provider,
        )

    return create
