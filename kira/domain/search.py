"""Pure Chat search requests, result values and query helpers."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timezone
from typing import Any


class ChatSearchError(RuntimeError):
    """Base error for the Chat search use case."""


class ChatSearchValidationError(ChatSearchError, ValueError):
    """Invalid or contradictory search input."""


@dataclass(frozen=True)
class ChatSearchRequest:
    query: str
    conversation_id: str | None = None
    session_id: str | None = None
    character_id: str | None = None
    roles: tuple[str, ...] = ()
    start_at: str | datetime | date | None = None
    end_at: str | datetime | date | None = None
    sort_by: str = "relevance"
    match_mode: str = "phrase"
    page: int = 1
    page_size: int = 20
    conversation_statuses: tuple[str, ...] = ()


@dataclass(frozen=True)
class ChatMessageReference:
    conversation_id: str
    message_id: int

    def as_dict(self) -> dict[str, Any]:
        return {"conversation_id": self.conversation_id, "message_id": self.message_id}


@dataclass(frozen=True)
class ChatSearchHit:
    message_id: int
    conversation_id: str
    character_id: str
    role: str
    content: str
    snippet: str
    created_at: str
    status: str
    metadata: dict[str, Any] = field(default_factory=dict)
    relevance: int = 0
    reference: ChatMessageReference | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "message_id": self.message_id,
            "conversation_id": self.conversation_id,
            "character_id": self.character_id,
            "role": self.role,
            "content": self.content,
            "snippet": self.snippet,
            "created_at": self.created_at,
            "status": self.status,
            "metadata": dict(self.metadata),
            "relevance": self.relevance,
            "reference": self.reference.as_dict() if self.reference else None,
        }


@dataclass(frozen=True)
class ChatSearchPage:
    query: str
    results: tuple[ChatSearchHit, ...]
    total: int
    page: int
    page_size: int
    total_pages: int
    has_previous: bool
    has_next: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "results": [hit.as_dict() for hit in self.results],
            "total": self.total,
            "page": self.page,
            "page_size": self.page_size,
            "total_pages": self.total_pages,
            "has_previous": self.has_previous,
            "has_next": self.has_next,
        }


def parse_search_datetime(
    value: str | datetime | date | None,
    end_of_day: bool = False,
) -> datetime | None:
    """Normalize an inclusive date/time bound to UTC."""
    if value is None or value == "":
        return None
    try:
        if isinstance(value, datetime):
            parsed = value
        elif isinstance(value, date):
            parsed = datetime.combine(value, time.max if end_of_day else time.min)
        else:
            raw = str(value).strip()
            if len(raw) == 10:
                parsed = datetime.combine(
                    date.fromisoformat(raw),
                    time.max if end_of_day else time.min,
                )
            else:
                parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return (
            parsed.replace(tzinfo=timezone.utc)
            if parsed.tzinfo is None
            else parsed.astimezone(timezone.utc)
        )
    except (TypeError, ValueError, OverflowError) as exc:
        raise ChatSearchValidationError(f"Invalid timestamp: {value!r}") from exc


def message_datetime(value: Any) -> datetime | None:
    """Parse a stored timestamp; malformed legacy timestamps are treated as absent."""
    if value is None or not str(value).strip():
        return None
    try:
        parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
        return (
            parsed.replace(tzinfo=timezone.utc)
            if parsed.tzinfo is None
            else parsed.astimezone(timezone.utc)
        )
    except (TypeError, ValueError, OverflowError):
        return None


def search_snippet(content: str, query: str, limit: int = 240) -> str:
    """Return a bounded excerpt centered around the first phrase occurrence."""
    if len(content) <= limit:
        return content
    index = content.casefold().find(query.casefold())
    start = max(0, index - limit // 3) if index >= 0 else 0
    end = min(len(content), start + limit)
    return (
        ("…" if start else "")
        + content[start:end].strip()
        + ("…" if end < len(content) else "")
    )


__all__ = [
    "ChatMessageReference",
    "ChatSearchError",
    "ChatSearchHit",
    "ChatSearchPage",
    "ChatSearchRequest",
    "ChatSearchValidationError",
    "message_datetime",
    "parse_search_datetime",
    "search_snippet",
]
