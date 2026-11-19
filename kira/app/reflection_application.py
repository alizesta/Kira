"""Application boundary for the post-response Reflection lifecycle."""
from __future__ import annotations
from typing import Any
from ..core.interfaces.brain import ReflectionService

class ReflectionApplicationService(ReflectionService):
    """Owns post-response review and optional bounded background reflection."""
    def __init__(self, engine: Any = None) -> None:
        if engine is None:
            from .. import brain as engine
        self._engine = engine
    def after_turn(self, router: Any, settings: Any, decision: Any, user_text: str, reply: str, tools: Any = None, mode_name: str | None = None, tool_expected: bool = False, *, character_id: str | None = None) -> dict:
        return self._engine.after_turn(router, settings, decision, user_text, reply, tools, mode_name, tool_expected, character_id=character_id)
