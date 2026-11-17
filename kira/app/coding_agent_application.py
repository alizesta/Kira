"""Application boundary for Coding Agent interception and session shutdown."""
from __future__ import annotations

from typing import Any, Callable


class CodingAgentApplicationService:
    """Route eligible chat turns to the existing Coding Agent lifecycle."""

    @staticmethod
    def dispatch(
        *,
        code_chat: Any | None,
        text: str,
        voice: bool,
        attachments,
        request_id: str | None,
        complete_local_request: Callable[[str], Any],
    ) -> bool:
        """Intercept only attachment-free turns and complete their Chat request on handoff."""
        if code_chat is None or attachments:
            return False
        if not code_chat.handle(text, bool(voice)):
            return False
        if request_id:
            complete_local_request(request_id)
        return True

    @staticmethod
    def stop_session(code_chat: Any | None, session: Any | None) -> bool:
        """Stop the Coding Agent session if one is active."""
        if code_chat is None or session is None:
            return False
        code_chat.stop(session)
        return True
