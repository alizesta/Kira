"""UI-independent chat message search and retrieval."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timezone
from typing import Any, Protocol


class ChatSearchError(RuntimeError):
    """Base search error."""


class ChatSearchValidationError(ChatSearchError, ValueError):
    """Invalid or contradictory search input."""


class ChatSearchRepositoryError(ChatSearchError):
    """The injected repository failed to retrieve messages."""


class ChatSearchRepository(Protocol):
    def messages_after(self, after_id: int = 0, limit: int = 500) -> list[dict[str, Any]]:
        """Return a page ordered by monotonically increasing message ID."""
        ...
    def list_conversations(self, character_id: str | None = None) -> list[dict[str, Any]]: ...


@dataclass(frozen=True)
class ChatSearchRequest:
    query: str
    conversation_id: str | None = None
    session_id: str | None = None
    character_id: str | None = None
    conversation_statuses: tuple[str, ...] = ()
    roles: tuple[str, ...] = ()
    start_at: str | datetime | date | None = None
    end_at: str | datetime | date | None = None
    sort_by: str = "relevance"
    match_mode: str = "phrase"
    page: int = 1
    page_size: int = 20


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
            "message_id": self.message_id, "conversation_id": self.conversation_id,
            "character_id": self.character_id, "role": self.role, "content": self.content,
            "snippet": self.snippet, "created_at": self.created_at, "status": self.status,
            "metadata": dict(self.metadata), "relevance": self.relevance,
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
            "query": self.query, "results": [hit.as_dict() for hit in self.results],
            "total": self.total, "page": self.page, "page_size": self.page_size,
            "total_pages": self.total_pages, "has_previous": self.has_previous,
            "has_next": self.has_next,
        }


def _parse_datetime(value: str | datetime | date | None, end_of_day: bool = False) -> datetime | None:
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
                parsed = datetime.combine(date.fromisoformat(raw), time.max if end_of_day else time.min)
            else:
                parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ChatSearchValidationError(f"Invalid timestamp: {value!r}") from exc


def _message_datetime(value: Any) -> datetime | None:
    if value is None or not str(value).strip():
        return None
    try:
        parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
    except (TypeError, ValueError, OverflowError):
        return None


def _snippet(content: str, query: str, limit: int = 240) -> str:
    if len(content) <= limit:
        return content
    index = content.casefold().find(query.casefold())
    start = max(0, index - limit // 3) if index >= 0 else 0
    end = min(len(content), start + limit)
    return ("…" if start else "") + content[start:end].strip() + ("…" if end < len(content) else "")


class ChatSearchService:
    """Matching, filtering, ranking and pagination over an injected message reader."""

    def __init__(self, repository: ChatSearchRepository, *, batch_size: int = 500):
        if repository is None or not callable(getattr(repository, "messages_after", None)):
            raise TypeError("repository must implement messages_after(after_id, limit)")
        try:
            self._batch_size = max(1, min(int(batch_size), 5000))
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("batch_size must be a positive integer") from exc
        self._repository = repository

    def search(self, request: ChatSearchRequest | str, **options: Any) -> ChatSearchPage:
        if isinstance(request, str):
            request = ChatSearchRequest(query=request, **options)
        elif options:
            raise ChatSearchValidationError("Do not combine a request object with keyword filters.")
        if not isinstance(request, ChatSearchRequest):
            raise ChatSearchValidationError("request must be ChatSearchRequest or a string query")

        query = " ".join(str(request.query or "").split())
        if not query:
            raise ChatSearchValidationError("query must not be empty")
        mode = str(request.match_mode or "phrase").strip().lower()
        sort_by = str(request.sort_by or "relevance").strip().lower()
        if mode not in {"exact", "phrase", "all_terms", "any_term"}:
            raise ChatSearchValidationError("match_mode must be exact, phrase, all_terms or any_term")
        if sort_by not in {"relevance", "newest", "oldest"}:
            raise ChatSearchValidationError("sort_by must be relevance, newest or oldest")
        try:
            page, page_size = int(request.page), int(request.page_size)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ChatSearchValidationError("page and page_size must be integers") from exc
        if page < 1 or not 1 <= page_size <= 100:
            raise ChatSearchValidationError("page must be >= 1 and page_size must be between 1 and 100")

        conversation_id = str(request.conversation_id or "").strip() or None
        session_id = str(request.session_id or "").strip() or None
        character_id = str(request.character_id or "").strip().lower() or None
        try:
            conversation_statuses = {str(status).strip().lower() for status in (request.conversation_statuses or ())}
        except TypeError as exc:
            raise ChatSearchValidationError("conversation_statuses must be an iterable of status names") from exc
        if conversation_statuses - {"active", "archived", "trashed", "closed"}:
            raise ChatSearchValidationError("conversation_statuses may contain active, archived, trashed or closed")
        allowed_conversation_ids = None
        if conversation_statuses:
            list_conversations = getattr(self._repository, "list_conversations", None)
            if not callable(list_conversations):
                raise ChatSearchRepositoryError("repository does not support conversation status filtering")
            try:
                allowed_conversation_ids = {
                    str(row.get("id") or "") for row in list_conversations(character_id)
                    if str(row.get("status") or "active").lower() in conversation_statuses
                }
            except Exception as exc:
                raise ChatSearchRepositoryError(f"conversation status retrieval failed: {type(exc).__name__}: {exc}") from exc
        try:
            roles = {str(role).strip().lower() for role in (request.roles or ())}
        except TypeError as exc:
            raise ChatSearchValidationError("roles must be an iterable of role names") from exc
        if roles - {"user", "assistant", "system"}:
            raise ChatSearchValidationError("roles may contain only user, assistant and system")
        start_at, end_at = _parse_datetime(request.start_at), _parse_datetime(request.end_at, True)
        if start_at and end_at and start_at > end_at:
            raise ChatSearchValidationError("start_at must not be later than end_at")
        terms = re.findall(r"\w+", query.casefold(), flags=re.UNICODE)
        if mode in {"all_terms", "any_term"} and not terms:
            raise ChatSearchValidationError("query must contain searchable terms")

        hits: list[ChatSearchHit] = []
        cursor = 0
        try:
            while True:
                batch = self._repository.messages_after(cursor, self._batch_size)
                if not batch:
                    break
                for row in batch:
                    try:
                        message_id = int(row.get("id", 0))
                    except (TypeError, ValueError, OverflowError):
                        continue
                    if message_id <= cursor:
                        raise ChatSearchRepositoryError("repository cursor did not advance monotonically")
                    cursor = message_id
                    role = str(row.get("role") or "").strip().lower()
                    content = str(row.get("content") or "")
                    conv_id = str(row.get("conversation_id") or "")
                    char_id = str(row.get("character_id") or "").strip().lower()
                    if role not in {"user", "assistant", "system"} or not content:
                        continue
                    if conversation_id and conv_id != conversation_id:
                        continue
                    if allowed_conversation_ids is not None and conv_id not in allowed_conversation_ids:
                        continue
                    metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
                    if session_id and str(metadata.get("session_id") or "") != session_id:
                        continue
                    if character_id and char_id != character_id:
                        continue
                    if roles and role not in roles:
                        continue
                    stamp = str(row.get("created_at") or "")
                    message_time = _message_datetime(stamp)
                    if (start_at or end_at) and (
                        message_time is None or (start_at and message_time < start_at)
                        or (end_at and message_time > end_at)
                    ):
                        continue
                    folded = content.casefold()
                    if mode == "exact":
                        if folded != query.casefold():
                            continue
                        score = 1000
                    elif mode == "phrase":
                        score = folded.count(query.casefold())
                        if not score:
                            continue
                        score += 100
                    else:
                        found = [term for term in terms if term in folded]
                        if not found or (mode == "all_terms" and len(found) != len(terms)):
                            continue
                        score = sum(folded.count(term) for term in found) + (25 if len(found) == len(terms) else 0)
                    hits.append(ChatSearchHit(
                        message_id=message_id, conversation_id=conv_id, character_id=char_id,
                        role=role, content=content, snippet=_snippet(content, query), created_at=stamp,
                        status=str(row.get("status") or "complete"),
                        metadata=dict(metadata), relevance=score,
                        reference=ChatMessageReference(conv_id, message_id) if conv_id else None,
                    ))
                if len(batch) < self._batch_size:
                    break
        except ChatSearchError:
            raise
        except Exception as exc:
            raise ChatSearchRepositoryError(f"message retrieval failed: {type(exc).__name__}: {exc}") from exc

        oldest = datetime.min.replace(tzinfo=timezone.utc)
        if sort_by == "relevance":
            hits.sort(key=lambda hit: (hit.relevance, _message_datetime(hit.created_at) or oldest, hit.message_id), reverse=True)
        elif sort_by == "newest":
            hits.sort(key=lambda hit: (_message_datetime(hit.created_at) or oldest, hit.message_id), reverse=True)
        else:
            hits.sort(key=lambda hit: (_message_datetime(hit.created_at) or oldest, hit.message_id))
        total = len(hits)
        total_pages = (total + page_size - 1) // page_size
        offset = (page - 1) * page_size
        return ChatSearchPage(
            query=query, results=tuple(hits[offset:offset + page_size]), total=total,
            page=page, page_size=page_size, total_pages=total_pages,
            has_previous=page > 1 and total > 0, has_next=page < total_pages,
        )


__all__ = [
    "ChatMessageReference", "ChatSearchError", "ChatSearchHit", "ChatSearchPage",
    "ChatSearchRepository", "ChatSearchRepositoryError", "ChatSearchRequest",
    "ChatSearchService", "ChatSearchValidationError",
]
