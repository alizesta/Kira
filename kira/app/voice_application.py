"""Application-owned Voice lifecycle orchestration.

The service implements the core VoiceService contract while treating Speaker,
Listener and GUI scheduling as injected adapters. It imports no Qt modules.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Callable

from ..core.interfaces.voice_service import VoiceService


WAKE_RE = re.compile(
    r"(?:(?:هی|سلام|hey|hi)[\s\u200c]*)?(?:کی[\s\u200c]?را|کایرا|کیرآ|کیارا|kira|keira|kyra|kiera)",
    re.I,
)
STOP_RE = re.compile(
    r"^\W*(?:بس\s*کن|بسه|ساکت(?:\s*شو)?|صبر\s*کن|وایسا|وایستا|stop|be\s*quiet)\W*$",
    re.I,
)
SLEEP_RE = re.compile(r"بخواب|خداحافظ|شب بخیر|good\s*night", re.I)


@dataclass(frozen=True)
class VoiceTranscriptDecision:
    action: str
    text: str = ""


class VoiceApplicationService(VoiceService):
    """Coordinate speech output and non-blocking microphone worker lifecycle."""

    def __init__(
        self,
        *,
        speaker: Any,
        listener_factory: Callable[[], Any],
        on_heard: Callable[[str], None],
        on_interrupted: Callable[[], None],
        on_state: Callable[[str], None],
        on_error: Callable[[str], None],
        on_note: Callable[[str], None],
        on_finished: Callable[[Any, bool, bool], None],
        on_waiting: Callable[[], None],
    ) -> None:
        if speaker is None or not callable(listener_factory):
            raise TypeError("speaker and listener_factory are required")
        self.speaker = speaker
        self.listener_factory = listener_factory
        self.on_heard = on_heard
        self.on_interrupted = on_interrupted
        self.on_state = on_state
        self.on_error = on_error
        self.on_note = on_note
        self.on_finished = on_finished
        self.on_waiting = on_waiting
        self.listener = None
        self.stopping_listener = None
        self.restart_after_stop = False

    @staticmethod
    def interpret_transcript(
        text: str, *, wake_enabled: bool, awake: bool
    ) -> VoiceTranscriptDecision:
        """Resolve wake/sleep/stop phrases before forwarding speech to Chat."""
        value = str(text or "")
        if wake_enabled:
            if not awake:
                match = WAKE_RE.search(value)
                if not match:
                    return VoiceTranscriptDecision("ignore")
                remainder = value[match.end():].strip(" ،,.!؟?؛")
                if len(remainder) < 2:
                    return VoiceTranscriptDecision("wake_only")
                value = remainder
                return VoiceTranscriptDecision("wake_submit", value)
            if SLEEP_RE.search(value):
                return VoiceTranscriptDecision("sleep", value)
        if STOP_RE.match(value.strip()):
            return VoiceTranscriptDecision("stop")
        return VoiceTranscriptDecision("submit", value)

    def start_recording(self) -> None:
        """Start one listener; defer replacement until the prior QThread has fully exited."""
        if self.listener is not None:
            self.stop_recording()
        previous = self.stopping_listener
        if previous is not None and previous.isRunning():
            self.restart_after_stop = True
            self.on_waiting()
            return
        self.restart_after_stop = False
        listener = self.listener_factory()
        listener.heard.connect(self.on_heard)
        listener.interrupted.connect(self.on_interrupted)
        listener.state.connect(self.on_state)
        listener.error.connect(self.on_error)
        listener.note.connect(self.on_note)
        listener.finished.connect(lambda current=listener: self._listener_finished(current))
        self.listener = listener
        listener.start()

    def stop_recording(self) -> None:
        """Request non-blocking listener shutdown and retain ownership until its finished signal."""
        self.restart_after_stop = False
        if self.listener is not None:
            listener, self.listener = self.listener, None
            listener.stop()
            if listener.isRunning():
                self.stopping_listener = listener

    def _listener_finished(self, listener: Any) -> None:
        was_current = self.listener is listener
        if was_current:
            self.listener = None
        if self.stopping_listener is listener:
            self.stopping_listener = None
        restart_requested = self.restart_after_stop
        self.restart_after_stop = False
        self.on_finished(listener, was_current, restart_requested)

    @property
    def settings(self):
        return self.speaker.settings

    @settings.setter
    def settings(self, value):
        self.speaker.settings = value

    def speak(self, text: str, rate=None, pitch=None, cache=False) -> None:
        self.speaker.speak(text, rate, pitch, cache=cache)

    def stop_speaking(self) -> None:
        self.speaker.stop()

    def stream_reset(self) -> None:
        self.speaker.stream_reset()

    def stream_text(self, text: str, final: bool = False) -> None:
        self.speaker.stream_text(text, final=final)

    def stream_end(self) -> None:
        self.speaker.stream_end()

    def play_file(self, path: str) -> None:
        self.speaker.play_file(path)

    def is_speaking(self) -> bool:
        return bool(getattr(self.speaker, "_began", False))

    def begin_speaking(self) -> None:
        listener = self.listener
        if listener is not None:
            listener.begin_kira_speech()

    def end_speaking(self) -> None:
        listener = self.listener
        if listener is not None:
            listener.end_kira_speech()

    def unmute_if_idle(self) -> None:
        listener = self.listener
        if listener is not None and not getattr(self.speaker, "_began", False):
            listener.muted = False

    def stop_all(self) -> None:
        self.stop_recording()
        self.stop_speaking()
