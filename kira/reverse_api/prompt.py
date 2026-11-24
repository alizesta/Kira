"""Flatten Kira's already-built turn into one prompt for web-chat style backends.

Kira stays the single owner of persona, memory, history and tool context: they all arrive through
``system_prompt`` and ``messages`` exactly as for every other provider. This module only serializes them.
"""
from __future__ import annotations

import json
from typing import Any


def build_prompt(messages: list[dict[str, Any]], system_prompt: str) -> str:
    lines: list[str] = []
    system = str(system_prompt or "").strip()
    if system:
        lines += ["### System", system, ""]
    lines.append("### Conversation")
    for item in messages:
        role = str(item.get("role") or "").strip().lower()
        content = str(item.get("content") or "")
        if role == "user":
            label = "User"
        elif role == "tool":
            name = str(item.get("name") or "tool").strip() or "tool"
            call_id = str(item.get("tool_call_id") or "").strip()
            label = f"Tool result ({name}{', call ' + call_id if call_id else ''})"
        else:
            label = "Assistant"
        lines.append(f"{label}: {content}")
        tool_calls = item.get("tool_calls") if role == "assistant" else None
        if tool_calls:
            lines.append("Assistant tool calls (JSON):")
            lines.append(json.dumps(tool_calls, ensure_ascii=False, separators=(",", ":")))
        if item.get("images"):
            lines.append(f"[{len(item['images'])} image attachment(s) included in structured message data]")
    lines += ["", "Assistant:"]
    return "\n".join(lines)
