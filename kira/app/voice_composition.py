"""Bootstrap factory for the Voice application lifecycle service.

Voice receives explicit device/UI callback ports instead of a MainWindow object.
"""
from __future__ import annotations

from typing import Callable

from ..core.interfaces.application_ports import VoiceApplicationPorts
from .voice_application import VoiceApplicationService


def create_voice_application_service_factory() -> Callable[[VoiceApplicationPorts], VoiceApplicationService]:
    """Create Voice service from an explicit set of device and presentation ports."""
    def create(ports: VoiceApplicationPorts) -> VoiceApplicationService:
        if not isinstance(ports, VoiceApplicationPorts):
            raise TypeError("ports must be VoiceApplicationPorts")
        return VoiceApplicationService(
            speaker=ports.speaker,
            listener_factory=ports.listener_factory,
            on_heard=ports.on_heard,
            on_interrupted=ports.on_interrupted,
            on_state=ports.on_state,
            on_error=ports.on_error,
            on_note=ports.on_note,
            on_finished=ports.on_finished,
            on_waiting=ports.on_waiting,
        )

    return create
