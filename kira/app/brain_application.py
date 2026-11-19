"""Application boundary for per-turn Brain planning and hint-state lifecycle."""
from __future__ import annotations
from typing import Any
from ..core.interfaces.brain import BrainService

class BrainApplicationService(BrainService):
    """Owns turn planning and prompt contribution; contains no Qt/UI dependencies."""
    def __init__(self, engine: Any = None) -> None:
        if engine is None:
            from .. import brain as engine
        self._engine = engine
    def decide(self, text: str, mode: Any = None, plan: Any = None, has_attachment: bool = False, has_task: bool = False, settings: Any = None) -> Any:
        return self._engine.decide(text, mode, plan, has_attachment, has_task, settings)
    def default_decision(self) -> Any:
        return self._engine.Decision()
    def extend_prompt(self, prompt: str, decision: Any, settings: Any = None, router: Any = None, *, character_id: str | None = None) -> str:
        return self._engine.extend_prompt(prompt, decision, settings, router, character_id=character_id)
    def reset_state(self, character_id: str | None = None) -> None:
        self._engine.reset_state(character_id)
    def status(self, character_id: str | None = None) -> dict:
        return self._engine.status(character_id)
