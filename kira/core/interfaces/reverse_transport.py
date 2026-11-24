"""Transport contract behind the Reverse API provider.

The Reverse API provider (kira/reverse_api/provider.py) is an ordinary ChatProvider. It never talks to a
service itself: it delegates the wire work to a ReverseTransport registered under a stable id. Concrete
transports (browser, login, session storage, headless runtime) are separate modules and plug in through
kira.reverse_api.registry.TRANSPORTS without touching the provider or the router.

Stdlib only: this module belongs to the Core layer.
"""
from __future__ import annotations

import threading
from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol, runtime_checkable


class TransportState(str, Enum):
    UNAVAILABLE = "unavailable"      # transport cannot work on this machine (missing runtime / dependency)
    DISCONNECTED = "disconnected"    # no usable session: the person must sign in / connect first
    CONNECTING = "connecting"        # a session is being established
    CONNECTED = "connected"          # ready to answer
    ERROR = "error"                  # was connected, now failing


@dataclass(frozen=True)
class TransportStatus:
    state: TransportState
    detail: str = ""                 # short human-readable reason; must never contain credentials
    supports_images: bool = False


@dataclass(frozen=True)
class ReverseRequest:
    """One chat turn, already assembled by Kira (persona, memory, history and tool context are inside)."""
    prompt: str                      # full flattened prompt: system prompt + conversation
    system_prompt: str
    messages: tuple[dict[str, Any], ...]   # normalized user/assistant turns, for transports that want structure
    model: str
    temperature: float = 0.7
    max_tokens: int | None = None
    conversation_id: str | None = None


class ReverseTransportError(RuntimeError):
    """Raised by a transport. ``kind`` uses the ProviderError vocabulary:
    auth | model | request | rate | server | network | timeout | response | empty | missing."""

    def __init__(self, message: str, *, kind: str = "server", retryable: bool = True) -> None:
        super().__init__(message)
        self.kind = kind
        self.retryable = retryable


@runtime_checkable
class ReverseTransport(Protocol):
    """What a concrete Reverse API backend must provide.

    The factory registered in the TransportRegistry is called for every request (the router builds a fresh
    provider each time), so a transport that owns a session must return a shared instance from its factory.
    """

    def status(self) -> TransportStatus: ...

    def stream(self, request: ReverseRequest, cancel: threading.Event) -> Iterable[str]:
        """Yield answer text pieces. May yield an empty string to signal that the connection is open.
        Must stop promptly when ``cancel`` is set."""
        ...

    def abort(self) -> None:
        """Interrupt the running request from another thread (Stop button)."""
        ...
