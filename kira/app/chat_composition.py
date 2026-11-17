"""Factories for application-level Chat dependencies.

Bootstrap owns service construction. The window is supplied only as the UI
adapter after it exists, so MainWindow does not compose feature services.
"""
from __future__ import annotations

from typing import Any, Callable


def create_chat_application_service_factory(
    *, persistence: Any, event_publisher: Any | None = None
) -> Callable[[Any], Any]:
    """Return a factory bound to bootstrap-owned persistence and event ports."""
    if persistence is None:
        raise TypeError("persistence is required")

    def create(window: Any) -> Any:
        from .. import brain
        from ..chat.application_service import ChatApplicationService
        from ..personality import build_system_prompt
        from ..ui.workers import StreamWorker

        return ChatApplicationService(
            persistence=persistence,
            system_prompt_builder=build_system_prompt,
            prompt_enricher=lambda value: brain.extend_prompt(
                value, window._brain, window.settings, window.client
            ),
            worker_factory=StreamWorker,
            on_dispatch=window._dispatch_application_request,
            on_event=window._on_chat_application_event,
            event_publisher=event_publisher,
            schedule=window._schedule_chat_callback,
            cancel_provider=window._cancel_application_provider,
        )

    return create
