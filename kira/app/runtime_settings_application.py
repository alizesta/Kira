"""Application-level reconfiguration of shared runtime settings."""
from __future__ import annotations

from typing import Any

from .. import evidence_memory, usage


class RuntimeSettingsApplicationService:
    """Apply persisted settings to shared application services and capabilities."""

    @staticmethod
    def configure(settings: dict[str, Any]) -> None:
        """Initialize global settings consumers during application composition."""
        usage.install(settings)
        evidence_memory.configure(settings)

    @staticmethod
    def apply(settings: dict[str, Any], tool_agent=None) -> None:
        """Update capability and global settings consumers after the settings dialog saves."""
        if tool_agent is not None:
            tool_agent.set_settings(settings)
        evidence_memory.configure(settings)
        usage.install(settings)
