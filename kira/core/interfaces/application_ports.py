"""Typed UI callback ports passed into application-service composition.

Application services depend on these contracts rather than concrete MainWindow
objects. Qt widgets, workers and signal relays are supplied by UI adapters.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True, slots=True)
class ChatApplicationPorts:
    prompt_enricher: Callable[[str], str]
    worker_factory: Callable[..., Any]
    on_dispatch: Callable[[Any], Any]
    on_event: Callable[[Any], Any]
    schedule: Callable[[Callable[[], Any]], Any]
    cancel_provider: Callable[[Any, Any], Any]


@dataclass(frozen=True, slots=True)
class VoiceApplicationPorts:
    speaker: Any
    listener_factory: Callable[[], Any]
    on_heard: Callable[[str], None]
    on_interrupted: Callable[[], None]
    on_state: Callable[[str], None]
    on_error: Callable[[str], None]
    on_note: Callable[[str], None]
    on_finished: Callable[[Any, bool, bool], None]
    on_waiting: Callable[[], None]
