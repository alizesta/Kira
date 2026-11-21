"""Application boundary for Kode request interception and session shutdown."""
from __future__ import annotations

from typing import Any, Callable


class KodeApplicationService:
    """Single application boundary for all Kode analysis and coding missions."""

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
        """Stop the active Kode session, whether it is analyzing or executing a mission."""
        if code_chat is None or session is None:
            return False
        return bool(code_chat.stop(session))


# Backward-compatible name for existing dependency registrations.
CodingAgentApplicationService = KodeApplicationService
