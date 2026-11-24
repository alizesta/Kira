"""Flatten Kira's already-built turn into one prompt for web-chat style backends.

Kira stays the single owner of persona, memory, history and tool context: they all arrive through
``system_prompt`` and ``messages`` exactly as for every other provider. This module only serializes them.
"""
from __future__ import annotations

from typing import Any


def build_prompt(messages: list[dict[str, Any]], system_prompt: str) -> str:
    lines: list[str] = []
    system = str(system_prompt or "").strip()
    if system:
        lines += ["### System", system, ""]
    lines.append("### Conversation")
    for item in messages:
        role = "User" if item.get("role") == "user" else "Assistant"
        lines.append(f"{role}: {item.get('content') or ''}")
    lines += ["", "Assistant:"]
    return "\n".join(lines)
