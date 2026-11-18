"""UI-side adapters that translate MainWindow callbacks into app ports."""
from __future__ import annotations

from PySide6.QtCore import QTimer

from .. import brain
from ..core.interfaces.application_ports import (
    ChatApplicationPorts,
    VoiceApplicationPorts,
)
from .workers import StreamWorker


class QtProviderWorkerAdapter:
    """Translate Qt worker signals into the toolkit-neutral provider worker port."""

    _SIGNALS = {
        "tool_event": "tool_event",
        "event": "event",
        "chunk": "chunk",
        "complete": "finished_ok",
        "error": "failed",
    }

    def __init__(self, worker):
        self._worker = worker

    def subscribe(self, event, callback):
        try:
            signal_name = self._SIGNALS[event]
        except KeyError as exc:
            raise ValueError(f"Unsupported provider event: {event}") from exc
        signal = getattr(self._worker, signal_name)
        signal.connect(callback)

        def unsubscribe():
            try:
                signal.disconnect(callback)
                return True
            except (RuntimeError, TypeError):
                return False

        return unsubscribe

    def start(self):
        return self._worker.start()

    def __getattr__(self, name):
        # Preserve worker cancellation/diagnostic hooks for existing UI adapters.
        return getattr(self._worker, name)


def create_chat_application_ports(window) -> ChatApplicationPorts:
    """Expose the minimum UI/provider boundary required by Chat application logic."""
    return ChatApplicationPorts(
        prompt_enricher=lambda value: brain.extend_prompt(
            value, window._brain, window.settings, window.client,
            character_id=window.cur.cid,
        ),
        worker_factory=lambda **request: QtProviderWorkerAdapter(StreamWorker(**request)),
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
