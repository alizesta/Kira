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


class QtVoiceListenerAdapter:
    """Translate a Qt microphone worker into the toolkit-neutral listener port."""

    _SIGNALS = {
        "heard": "heard",
        "interrupted": "interrupted",
        "state": "state",
        "error": "error",
        "note": "note",
        "finished": "finished",
    }

    def __init__(self, listener):
        self.raw_listener = listener

    def subscribe(self, event, callback):
        try:
            signal_name = self._SIGNALS[event]
        except KeyError as exc:
            raise ValueError(f"Unsupported voice event: {event}") from exc
        signal = getattr(self.raw_listener, signal_name)
        signal.connect(callback)

        def unsubscribe():
            try:
                signal.disconnect(callback)
                return True
            except (RuntimeError, TypeError):
                return False

        return unsubscribe

    def start(self):
        return self.raw_listener.start()

    def stop(self):
        return self.raw_listener.stop()

    def is_running(self):
        try:
            return bool(self.raw_listener.isRunning())
        except RuntimeError:
            return False

    # Compatibility for existing UI status rendering; application code uses is_running().
    def isRunning(self):
        return self.is_running()

    def begin_speaking(self):
        return self.raw_listener.begin_kira_speech()

    def end_speaking(self):
        return self.raw_listener.end_kira_speech()

    def set_muted(self, muted):
        self.raw_listener.muted = bool(muted)

    def __getattr__(self, name):
        return getattr(self.raw_listener, name)


class QtSpeakerAdapter:
    """Expose the desktop Speaker implementation through the core SpeakerPort."""

    def __init__(self, speaker):
        self._speaker = speaker

    @property
    def settings(self):
        return self._speaker.settings

    @settings.setter
    def settings(self, value):
        self._speaker.settings = value

    def speak(self, text, rate=None, pitch=None, cache=False):
        return self._speaker.speak(text, rate, pitch, cache=cache)

    def stop(self):
        return self._speaker.stop()

    def stream_reset(self):
        return self._speaker.stream_reset()

    def stream_text(self, text, final=False):
        return self._speaker.stream_text(text, final=final)

    def stream_end(self):
        return self._speaker.stream_end()

    def play_file(self, path):
        return self._speaker.play_file(path)

    def is_speaking(self):
        return bool(getattr(self._speaker, "_began", False))


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
        speaker=QtSpeakerAdapter(speaker),
        listener_factory=lambda: QtVoiceListenerAdapter(window._create_voice_listener()),
        on_heard=window.on_heard,
        on_interrupted=window.on_user_barge_in,
        on_state=window.on_listener_state,
        on_error=window.on_listener_error,
        on_note=window.on_voice_note,
        on_finished=lambda listener, was_current, restart: window.voice_listener_finished.emit(
            listener.raw_listener, was_current, restart
        ),
        on_waiting=lambda: window.set_status("st_loading"),
    )
