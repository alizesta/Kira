"""Contract consumed by UI/chat; implementation is supplied by Voice module."""
from __future__ import annotations

from typing import Protocol


class VoiceService(Protocol):
    def start_recording(self) -> None: ...

    def stop_recording(self) -> None: ...

    def speak(self, text: str) -> None: ...

    def stop_speaking(self) -> None: ...
