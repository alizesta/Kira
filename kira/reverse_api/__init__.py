"""Reverse API integration: a standard ChatProvider plus registered transports."""
from __future__ import annotations

from .registry import TRANSPORTS, TransportRegistry
from .deepseek_transport import DeepSeekBrowserTransport

# The router constructs a fresh provider for each turn; keep one transport instance
# so its registry and request lock remain shared across provider instances.
_DEEPSEEK_TRANSPORT = DeepSeekBrowserTransport()
if TRANSPORTS.resolve("deepseek") is None:
    TRANSPORTS.register("deepseek", lambda config: _DEEPSEEK_TRANSPORT)

__all__ = ["TRANSPORTS", "TransportRegistry", "DeepSeekBrowserTransport"]