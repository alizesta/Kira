"""Reverse API integration: a standard ChatProvider plus a pluggable transport registry.

The provider itself lives in kira.reverse_api.provider and is resolved lazily by the provider registry.
"""
from __future__ import annotations

from .registry import TRANSPORTS, TransportRegistry

__all__ = ["TRANSPORTS", "TransportRegistry"]
