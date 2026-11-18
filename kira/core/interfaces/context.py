"""Core-owned callback ports used by provider-neutral context composition."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol


class SystemPromptBuilderPort(Protocol):
    """Build the base system prompt from an immutable settings snapshot."""

    def __call__(self, settings: Mapping[str, Any], **kwargs: Any) -> str: ...


class PromptEnricherPort(Protocol):
    """Apply one injected, toolkit-neutral prompt enrichment step."""

    def __call__(self, prompt: str) -> str: ...


__all__ = ["PromptEnricherPort", "SystemPromptBuilderPort"]
