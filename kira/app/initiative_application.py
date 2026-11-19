"""Application-owned orchestration for proactive Initiative check-ins.

The Qt controller decides whether the desktop is in a safe presentation state.
This service owns the non-visual policy, character-scoped memory/mood access,
durable message write, and duplicate/rate-limit history calculation.
"""
from __future__ import annotations

import logging
import math
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ..character.initiative import (
    InitiativeEngine,
    build_checkin_message,
    initiative_history_state,
    persisted_checkin_events,
    sessions_are_idle,
)

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class InitiativeCheckIn:
    """A successfully persisted proactive message and its updated settings history."""

    character_id: str
    message: str
    history: tuple[dict[str, Any], ...]


class InitiativeApplicationService:
    """Coordinate Initiative policy with injected character memory, mood and Chat ports."""

    def __init__(self, memory_service: Any, mood_service: Any, chat_application_service: Any):
        if memory_service is None or mood_service is None or chat_application_service is None:
            raise TypeError("memory_service, mood_service and chat_application_service are required")
        self.memory_service = memory_service
        self.mood_service = mood_service
        self.chat_application_service = chat_application_service

    @staticmethod
    def merge_settings_history(settings: Mapping[str, Any], result: InitiativeCheckIn) -> dict[str, Any]:
        """Merge a successful check-in into persisted per-character history.

        Malformed legacy settings are treated as an empty history rather than
        raising after the assistant message has already been durably written.
        """
        existing = settings.get("character_initiative_history")
        updated = dict(existing) if isinstance(existing, dict) else {}
        updated[result.character_id] = list(result.history)
        return updated

    def run_checkin(
        self,
        session: Any,
        profiles: Mapping[str, Mapping[str, Any]],
        traits_by_character: Mapping[str, Mapping[str, Any]],
        settings: Mapping[str, Any],
        sessions: tuple[Any, ...],
        *,
        now: float | None = None,
    ) -> InitiativeCheckIn | None:
        """Persist one eligible check-in; return None when policy or persistence rejects it."""
        current = time.time() if now is None else float(now)
        character_id = str(getattr(session, "cid", "") or "")
        if not character_id or not isinstance(profiles, Mapping) or character_id not in profiles:
            return None
        if not sessions_are_idle(sessions):
            return None

        emotional = None
        latest_user_age = None
        for profile_id in profiles:
            cid = str(profile_id)
            traits = traits_by_character.get(cid, {})
            with self.mood_service.character_scope(cid, dict(traits)):
                profile_mood = self.mood_service.current(now=current)
            try:
                age = float(profile_mood.get("age", 0.0))
            except (TypeError, ValueError, OverflowError):
                return None
            # 1e9 means no user message has ever been recorded; it is not inactivity.
            if not math.isfinite(age) or age < 0:
                return None
            if age < 1e8:
                latest_user_age = age if latest_user_age is None else min(latest_user_age, age)
            if cid == character_id:
                emotional = profile_mood
        if emotional is None or latest_user_age is None:
            return None

        memories = self.memory_service.list_items(character_id, now=current)
        history_by_character = settings.get("character_initiative_history")
        if not isinstance(history_by_character, dict):
            history_by_character = {}
        try:
            persisted_records = self.chat_application_service.recent_message_records(
                limit=5000, character_id=character_id
            )
        except Exception:
            _log.exception("Could not inspect persisted Initiative check-in history")
            return None

        recovered_events = persisted_checkin_events(persisted_records, now=current)
        history_state = initiative_history_state(
            history_by_character.get(character_id, []),
            recent_events=[*(emotional.get("recent_events", []) or []), *recovered_events],
            last_memory_id=emotional.get("last_initiative_memory_id", ""),
            last_sent_at=emotional.get("last_initiative", 0.0),
            now=current,
        )
        engine = InitiativeEngine()
        engine.last_initiative = emotional.get("last_initiative", 0.0)
        candidate = engine.select_candidate(
            memories, now=current, exclude_ids=history_state["excluded_ids"]
        )
        decision = engine.evaluate(
            now=current,
            last_interaction=current - latest_user_age,
            enabled=True,
            app_active=True,
            quiet_hours=engine.is_quiet_hour(now=current),
            busy=False,
            has_relevant_memory=bool(candidate),
            sent_today=history_state["sent_today"],
        )
        if not decision.get("eligible") or candidate is None:
            return None

        message = build_checkin_message(candidate, language="auto")
        if not message:
            return None
        outcome = self.chat_application_service.persist_message(
            session.session_id,
            "assistant",
            message,
            request_id=getattr(session, "application_request_id", None),
            conversation_id=getattr(session, "conversation_id", None),
            status="complete",
            character_id=character_id,
            metadata={
                "proactive": "initiative",
                "memory_id": str(candidate.get("id") or "")[:64],
            },
        )
        if not getattr(outcome, "ok", False):
            return None

        with self.mood_service.character_scope(
            character_id, dict(traits_by_character.get(character_id, {}))
        ):
            self.mood_service.mark_initiative_sent(
                memory_id=candidate["id"], now=current
            )
        updated_history = history_state["history"] + [
            {"at": current, "memory_id": str(candidate["id"])[:64]}
        ]
        return InitiativeCheckIn(
            character_id=character_id,
            message=message,
            history=tuple(updated_history[-64:]),
        )
