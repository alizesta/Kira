"""Bootstrap factory for the Voice application lifecycle service."""
from __future__ import annotations

from typing import Any, Callable

from .voice_application import VoiceApplicationService


def create_voice_application_service_factory() -> Callable[[Any, Any], VoiceApplicationService]:
    """Create the Voice service after the window has supplied its device/UI adapters."""
    def create(window: Any, speaker: Any) -> VoiceApplicationService:
        return VoiceApplicationService(
            speaker=speaker,
            listener_factory=window._create_voice_listener,
            on_heard=window.on_heard,
            on_interrupted=window.on_user_barge_in,
            on_state=window.on_listener_state,
            on_error=window.on_listener_error,
            on_note=window.on_voice_note,
            on_finished=window.voice_listener_finished.emit,
            on_waiting=lambda: window.set_status("st_loading"),
        )

    return create
