"""Provider-neutral contract consumed by the hybrid route router."""
from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class ChatProvider(Protocol):
    """Minimum transport contract for local and remote chat providers."""

    name: str
    upload_progress: Callable[[int], None] | None
    last_usage: dict[str, Any] | None
    cancel_event: Any | None

    def enabled(self) -> bool: ...

    def abort(self) -> None: ...

    def chat(self, messages: list[dict[str, Any]], system_prompt: str, temperature: float = 0.7) -> str: ...

    def stream(
        self,
        messages: list[dict[str, Any]],
        system_prompt: str,
        temperature: float = 0.7,
        on_connect: Callable[[], None] | None = None,
        max_tokens: int | None = None,
    ) -> Iterable[str]: ...
