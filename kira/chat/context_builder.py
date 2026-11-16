"""Provider-neutral assembly of chat messages and system prompts.

This module owns prompt composition only. It deliberately knows nothing about
Qt, windows, sessions, persistence, providers, or a particular character.
All application-specific behavior enters through immutable request data and
injected prompt-building/enrichment callables.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Protocol, Sequence


class SystemPromptBuilder(Protocol):
    def __call__(self, settings: Mapping[str, Any], **kwargs: Any) -> str: ...


class PromptEnricher(Protocol):
    def __call__(self, prompt: str) -> str: ...


@dataclass(frozen=True)
class ContextRequest:
    """All data needed for one turn; values are snapshots, never live UI objects."""

    messages: Sequence[Mapping[str, Any]] = field(default_factory=tuple)
    character_id: str = ""
    character_profile: Mapping[str, Any] = field(default_factory=dict)
    settings: Mapping[str, Any] = field(default_factory=dict)
    memory: str = ""
    mood: str = ""
    character_context: str = ""
    format_hint: str = ""
    voice_input: bool = False
    mode: Any = None
    body_context: str = ""
    tool_context: str = ""
    active_capabilities: Sequence[str] = field(default_factory=tuple)
    turn_extra: Mapping[str, Any] | None = None
    max_context_chars: int = 0


@dataclass(frozen=True)
class ContextResult:
    """Final provider-neutral system prompt and ordered message snapshot."""

    system_prompt: str
    messages: tuple[dict[str, Any], ...]
    character_id: str
    retained_context_chars: int
    dropped_messages: int = 0


class ContextBuilder:
    """Build one isolated turn context using explicitly injected collaborators."""

    def __init__(
        self,
        system_prompt_builder: SystemPromptBuilder,
        *,
        prompt_enricher: PromptEnricher | None = None,
    ) -> None:
        if not callable(system_prompt_builder):
            raise TypeError("system_prompt_builder must be callable")
        if prompt_enricher is not None and not callable(prompt_enricher):
            raise TypeError("prompt_enricher must be callable")
        self._system_prompt_builder = system_prompt_builder
        self._prompt_enricher = prompt_enricher

    def build(self, request: ContextRequest) -> ContextResult:
        if not isinstance(request, ContextRequest):
            raise TypeError("request must be a ContextRequest")

        messages = self._snapshot_messages(request.messages)
        messages = self._apply_turn_attachment(messages, request.turn_extra)
        messages, dropped = self._fit_history(messages, request.max_context_chars)

        prompt = self._system_prompt_builder(
            dict(request.settings),
            format_hint=request.format_hint,
            memory_block=request.memory,
            voice_input=bool(request.voice_input),
            mode=request.mode,
            mood_block=request.mood,
            character_profile=dict(request.character_profile),
        )
        prompt = str(prompt or "").strip()

        # Keep the historical order: base character/policy prompt, character
        # service layer, body-control notes, then the deterministic brain hint.
        layers = [
            request.character_context,
            request.body_context,
            request.tool_context,
        ]
        capabilities = tuple(str(item).strip() for item in request.active_capabilities if str(item).strip())
        if capabilities:
            layers.append("ACTIVE CAPABILITIES:\n- " + "\n- ".join(capabilities))
        for layer in layers:
            text = str(layer or "").strip()
            if text:
                prompt = (prompt + "\n\n" + text).strip() if prompt else text

        if self._prompt_enricher is not None:
            prompt = str(self._prompt_enricher(prompt) or prompt)

        return ContextResult(
            system_prompt=prompt,
            messages=tuple(messages),
            character_id=str(request.character_id or ""),
            retained_context_chars=self._context_chars(messages),
            dropped_messages=dropped,
        )

    @staticmethod
    def _snapshot_messages(messages: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for message in messages or ():
            if not isinstance(message, Mapping):
                continue
            result.append(deepcopy(dict(message)))
        return result

    @staticmethod
    def _apply_turn_attachment(
        messages: list[dict[str, Any]], extra: Mapping[str, Any] | None
    ) -> list[dict[str, Any]]:
        if not extra or not messages or messages[-1].get("role") != "user":
            return messages
        if "model" not in extra:
            return messages
        messages[-1]["content"] = extra["model"]
        if "images" in extra:
            messages[-1]["images"] = deepcopy(extra["images"])
        return messages

    @staticmethod
    def _context_chars(messages: Sequence[Mapping[str, Any]]) -> int:
        total = 0
        for message in messages:
            content = message.get("content", "")
            total += len(content if isinstance(content, str) else str(content))
            images = message.get("images")
            if images:
                total += len(str(images))
        return total

    @classmethod
    def _fit_history(
        cls, messages: list[dict[str, Any]], max_chars: int
    ) -> tuple[list[dict[str, Any]], int]:
        """Drop oldest conversational turns first; never reorder or truncate the current turn.

        A zero/negative limit preserves the legacy unbounded behavior. System
        messages are retained. The newest user message is always retained even
        when it alone exceeds the requested soft budget.
        """
        try:
            budget = int(max_chars)
        except (TypeError, ValueError):
            budget = 0
        if budget <= 0 or cls._context_chars(messages) <= budget:
            return messages, 0

        kept = list(messages)
        dropped = 0
        newest_user = next(
            (i for i in range(len(kept) - 1, -1, -1) if kept[i].get("role") == "user"),
            None,
        )
        while cls._context_chars(kept) > budget:
            candidate = next(
                (i for i, item in enumerate(kept)
                 if item.get("role") != "system" and i != newest_user),
                None,
            )
            if candidate is None:
                break
            kept.pop(candidate)
            dropped += 1
            if newest_user is not None and candidate < newest_user:
                newest_user -= 1
        return kept, dropped
