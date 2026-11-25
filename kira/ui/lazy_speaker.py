"""Lazy Qt Speaker proxy.

The audio backend and voice implementation are imported only when speech is first
requested. Signal names and the SpeakerPort surface remain stable for composition.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, Signal


class LazySpeaker(QObject):
    started = Signal()
    finished = Signal()
    cancelled = Signal()
    level = Signal(float)
    error = Signal(str)

    def __init__(self, factory: Callable[[], Any], *, settings: dict, parent=None) -> None:
        super().__init__(parent)
        if not callable(factory):
            raise TypeError("Speaker factory must be callable")
        self._factory = factory
        self._settings = settings
        self._speaker = None
        self._disposed = False

    @property
    def initialized(self) -> bool:
        return self._speaker is not None

    @property
    def settings(self):
        speaker = self._speaker
        return speaker.settings if speaker is not None else self._settings

    @settings.setter
    def settings(self, value):
        self._settings = value
        if self._speaker is not None:
            self._speaker.settings = value

    def _ensure(self):
        if self._disposed:
            raise RuntimeError("Speaker has been disposed")
        if self._speaker is None:
            speaker = self._factory()
            required = ("speak", "stop", "stream_reset", "stream_text", "stream_end", "play_file")
            missing = [name for name in required if not callable(getattr(speaker, name, None))]
            if missing:
                raise TypeError("Speaker implementation is missing: " + ", ".join(missing))
            self._speaker = speaker
            for name in ("started", "finished", "cancelled", "level", "error"):
                signal = getattr(speaker, name, None)
                if signal is not None and callable(getattr(signal, "connect", None)):
                    signal.connect(getattr(self, name).emit)
        return self._speaker

    def speak(self, text, rate=None, pitch=None, cache=False):
        return self._ensure().speak(text, rate, pitch, cache=cache)

    def stop(self):
        if self._speaker is not None:
            return self._speaker.stop()
        return None

    def stream_reset(self):
        return self._ensure().stream_reset()

    def stream_text(self, text, final=False):
        return self._ensure().stream_text(text, final=final)

    def stream_end(self):
        return self._ensure().stream_end()

    def play_file(self, path):
        return self._ensure().play_file(path)

    def is_speaking(self):
        return bool(getattr(self._speaker, "_began", False)) if self._speaker is not None else False

    def is_idle(self):
        if self._speaker is None:
            return True
        checker = getattr(self._speaker, "is_idle", None)
        return bool(checker()) if callable(checker) else not self.is_speaking()

    def dispose(self):
        if self._disposed:
            return True
        self.stop()
        self._disposed = True
        return True
