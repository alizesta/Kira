"""UI-side adapters that translate MainWindow callbacks into app ports."""
from __future__ import annotations

from PySide6.QtCore import QTimer

from .. import brain
from ..core.interfaces.application_ports import (
    ChatApplicationPorts,
    VoiceApplicationPorts,
)
from .workers import StreamWorker


def create_chat_application_ports(window) -> ChatApplicationPorts:
    """Expose the minimum UI/provider boundary required by Chat application logic."""
    return ChatApplicationPorts(
        prompt_enricher=lambda value: brain.extend_prompt(
            value, window._brain, window.settings, window.client,
            character_id=window.cur.cid,
        ),
        worker_factory=StreamWorker,
        on_dispatch=window._dispatch_application_request,
        on_event=window._on_chat_application_event,
        schedule=lambda callback: QTimer.singleShot(0, callback),
        cancel_provider=window._cancel_application_provider,
    )


def create_voice_application_ports(window, speaker) -> VoiceApplicationPorts:
    """Expose device and presentation callbacks without leaking MainWindow to app code."""
    return VoiceApplicationPorts(
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
