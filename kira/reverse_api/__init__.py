"""Reverse API integration: a standard ChatProvider plus registered transports."""
from __future__ import annotations

from .registry import TRANSPORTS, TransportRegistry
from .deepseek_transport import DeepSeekBrowserTransport

# The router constructs a fresh provider for each turn; keep one transport instance
# so its registry and request lock remain shared across provider instances.
_DEEPSEEK_TRANSPORT = DeepSeekBrowserTransport()
if TRANSPORTS.resolve("deepseek") is None:
    TRANSPORTS.register("deepseek", lambda config: _DEEPSEEK_TRANSPORT.configure(config))

def set_deepseek_browser_active(active: bool) -> None:
    """Tie the visible DeepSeek Chromium lifetime to the selected chat model."""
    _DEEPSEEK_TRANSPORT.activate(bool(active))


__all__ = [
    "TRANSPORTS",
    "TransportRegistry",
    "DeepSeekBrowserTransport",
    "set_deepseek_browser_active",
]