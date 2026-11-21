"""Provider-neutral assembly of chat messages and system prompts.

This module owns prompt composition only. It deliberately knows nothing about
Qt, windows, sessions, persistence, providers, or a particular character.
All application-specific behavior enters through immutable request data and
injected prompt-building/enrichment callables.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping, Sequence


from ..core.interfaces.context import (
    PromptEnricherPort,
    SystemPromptBuilderPort,
)
from ..domain.chat import ContextRequest, ContextResult
from ..ui_design_guidance import guidance_for_task

# Preserve historical type names and imports during the migration.
SystemPromptBuilder = SystemPromptBuilderPort
PromptEnricher = PromptEnricherPort


def latest_user_text(messages: Sequence[Mapping[str, Any]]) -> str:
    """Return the newest user message without mistaking assistant/system text for input."""
    for message in reversed(messages or ()):
        if not isinstance(message, Mapping) or message.get("role") != "user":
            continue
        content = message.get("content", "")
        return content if isinstance(content, str) else str(content or "")
    return ""


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
        # Apply Kira's UI-design workflow only to relevant turns; other characters
        # and non-UI tasks keep the exact historical prompt.
        if str(request.character_id or "").strip().lower() == "kira":
            ui_guidance = guidance_for_task(latest_user_text(messages))
            if ui_guidance:
                prompt = (prompt + "\\n\\n" + ui_guidance).strip()

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

        # Legacy shape remains supported while callers migrate to structured
        # attachment content. ContextBuilder owns provider-facing composition.
        if "model" in extra:
            messages[-1]["content"] = extra["model"]
            if "images" in extra:
                messages[-1]["images"] = deepcopy(extra["images"])
            return messages

        if "files" not in extra and "text" not in extra:
            return messages
        user_text = str(extra.get("text") or "").strip()
        files = [item for item in (extra.get("files") or ()) if isinstance(item, Mapping)]
        images = [item for item in (extra.get("images") or ()) if isinstance(item, Mapping)]
        content = user_text
        if not content:
            if images and not files:
                content = (
                    "این تصویر چیست؟ با کمک نتایج جست‌وجوی وب بگو."
                    if extra.get("search") else "این تصویر را ببین و نظرت را بگو."
                )
            elif files and not images:
                content = "این فایل را بخوان و درباره‌اش نظر بده."
            elif files or images:
                content = "این ضمیمه‌ها را ببین و نظرت را بگو."

        try:
            file_limit = max(1, int(extra.get("max_file_chars", 30000)))
        except (TypeError, ValueError):
            file_limit = 30000
        for item in files:
            name = str(item.get("name") or "attachment")
            body = str(item.get("text") or "")
            truncated = bool(item.get("truncated")) or len(body) > file_limit
            body = body[:file_limit]
            content += f"\n\n--- فایل ضمیمه: {name} ---\n{body}"
            if truncated:
                content += "\n[... بقیه‌ی فایل بریده شد ...]"
            content += "\n--- پایان فایل ---"
        if images:
            content += "\n\n" + "\n".join(
                f"[تصویر ضمیمه: {str(item.get('name') or 'image')}]" for item in images
            )
            messages[-1]["images"] = deepcopy(images)
        messages[-1]["content"] = content
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

            # Remove the oldest complete conversational turn, not just its
            # user message. This avoids leaving an orphaned assistant answer.
            end = candidate + 1
            if kept[candidate].get("role") == "user":
                next_user = next(
                    (i for i in range(candidate + 1, len(kept))
                     if kept[i].get("role") == "user"),
                    None,
                )
                if next_user is not None:
                    end = next_user
            removed = end - candidate
            del kept[candidate:end]
            dropped += removed
            if newest_user is not None and candidate < newest_user:
                newest_user -= removed
        return kept, dropped
