"""Application-owned Voice lifecycle orchestration.

The service implements the core VoiceService contract while treating Speaker,
Listener and GUI scheduling as injected adapters. It imports no Qt modules.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Callable

from ..core.interfaces.voice_service import VoiceService
from ..core.interfaces.voice_ports import SpeakerPort, VoiceListenerPort


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
        speaker: SpeakerPort,
        listener_factory: Callable[[], VoiceListenerPort],
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
        self.listener: VoiceListenerPort | None = None
        self.stopping_listener: VoiceListenerPort | None = None
        self.restart_after_stop = False
        self._disposed = False

    def start(self) -> None:
        if self._disposed:
            raise RuntimeError("VoiceApplicationService has been disposed")

    def stop(self) -> None:
        self.stop_all()

    def dispose(self) -> bool:
        """Stop audio and release the listener only after its worker has exited."""
        if self._disposed:
            return True
        self.stop_all()
        if self._is_running(self.listener) or self._is_running(self.stopping_listener):
            return False
        self.listener = None
        self.stopping_listener = None
        self.restart_after_stop = False
        self._disposed = True
        return True

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

    @staticmethod
    def _is_running(listener: VoiceListenerPort | None) -> bool:
        if listener is None:
            return False
        try:
            return bool(listener.is_running())
        except RuntimeError:
            # A worker can be released between its completion notification and a caller action.
            return False

    def start_recording(self) -> None:
        """Start one listener; defer replacement until the prior listener worker has fully exited."""
        if self._disposed:
            raise RuntimeError("VoiceApplicationService has been disposed")
        if self.listener is not None:
            self.stop_recording()
        previous = self.stopping_listener
        if previous is not None and self._is_running(previous):
            self.restart_after_stop = True
            self.on_waiting()
            return
        if previous is not None:
            self.stopping_listener = None
        self.restart_after_stop = False
        listener = self.listener_factory()
        listener.subscribe("heard", self.on_heard)
        listener.subscribe("interrupted", self.on_interrupted)
        listener.subscribe("state", self.on_state)
        listener.subscribe("error", self.on_error)
        listener.subscribe("note", self.on_note)
        listener.subscribe("finished", lambda current=listener: self._listener_finished(current))
        self.listener = listener
        try:
            listener.start()
        except Exception:
            self.listener = None
            raise

    def stop_recording(self) -> None:
        """Request non-blocking listener shutdown and retain ownership until its finished signal."""
        self.restart_after_stop = False
        if self.listener is not None:
            listener, self.listener = self.listener, None
            try:
                listener.stop()
            except RuntimeError:
                self.stopping_listener = None
                return
            if self._is_running(listener):
                self.stopping_listener = listener
            elif self.stopping_listener is listener:
                self.stopping_listener = None

    def _listener_finished(self, listener: VoiceListenerPort) -> None:
        was_current = self.listener is listener
        if was_current:
            self.listener = None
        if self.stopping_listener is listener:
            self.stopping_listener = None
        restart_requested = self.restart_after_stop
        self.restart_after_stop = False
        self.on_finished(listener, was_current, restart_requested)

    def apply_character_settings(self, settings: dict[str, Any], overrides=None):
        """Apply only the supported per-character voice overrides to Speaker."""
        effective = dict(settings)
        effective.update({
            key: value
            for key, value in (overrides or {}).items()
            if key in ("voice_rate", "voice_volume")
        })
        self.settings = effective
        return effective

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
        return bool(self.speaker.is_speaking())

    def begin_speaking(self) -> None:
        listener = self.listener
        if listener is not None:
            listener.begin_speaking()

    def end_speaking(self) -> None:
        listener = self.listener
        if listener is not None:
            listener.end_speaking()

    def unmute_if_idle(self) -> None:
        listener = self.listener
        if listener is not None and not self.speaker.is_speaking():
            listener.set_muted(False)

    def stop_all(self) -> None:
        self.stop_recording()
        self.stop_speaking()
