"""Application use case for searching and retrieving Chat history."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from ..core.interfaces.search import (
    ChatSearchRepositoryPort,
    ConversationStatusReaderPort,
)
from ..domain.search import (
    ChatMessageReference,
    ChatSearchError,
    ChatSearchHit,
    ChatSearchPage,
    ChatSearchRequest,
    ChatSearchValidationError,
    message_datetime,
    parse_search_datetime,
    search_snippet,
)


class ChatSearchRepositoryError(ChatSearchError):
    """The injected Persistence read port failed or violated its cursor contract."""


class ChatSearchService:
    """Matching, filtering, ranking and pagination over an injected message reader."""

    def __init__(
        self,
        repository: ChatSearchRepositoryPort,
        *,
        conversation_reader: ConversationStatusReaderPort | None = None,
        batch_size: int = 500,
    ):
        if repository is None or not callable(getattr(repository, "messages_after", None)):
            raise TypeError("repository must implement messages_after(after_id, limit)")
        try:
            self._batch_size = max(1, min(int(batch_size), 5000))
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("batch_size must be a positive integer") from exc
        self._repository = repository
        self._conversation_reader = (
            conversation_reader
            if conversation_reader is not None
            else repository if callable(getattr(repository, "list_conversations", None)) else None
        )

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
            list_conversations = self._conversation_reader
            if list_conversations is None:
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
        start_at, end_at = parse_search_datetime(request.start_at), parse_search_datetime(request.end_at, True)
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
                    message_time = message_datetime(stamp)
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
                        role=role, content=content, snippet=search_snippet(content, query), created_at=stamp,
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
            hits.sort(key=lambda hit: (hit.relevance, message_datetime(hit.created_at) or oldest, hit.message_id), reverse=True)
        elif sort_by == "newest":
            hits.sort(key=lambda hit: (message_datetime(hit.created_at) or oldest, hit.message_id), reverse=True)
        else:
            hits.sort(key=lambda hit: (message_datetime(hit.created_at) or oldest, hit.message_id))
        total = len(hits)
        total_pages = (total + page_size - 1) // page_size
        offset = (page - 1) * page_size
        return ChatSearchPage(
            query=query, results=tuple(hits[offset:offset + page_size]), total=total,
            page=page, page_size=page_size, total_pages=total_pages,
            has_previous=page > 1 and total > 0, has_next=page < total_pages,
        )


__all__ = [
    "ChatSearchRepositoryError",
    "ChatSearchService",
]
