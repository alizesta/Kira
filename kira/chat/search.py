"""Compatibility imports for Chat search and retrieval.

New application code should depend on kira.app.chat_search_application; request
and result values live in kira.domain.search.
"""
from ..app.chat_search_application import (
    ChatSearchRepositoryError,
    ChatSearchService,
)
from ..core.interfaces.search import ChatSearchRepositoryPort as ChatSearchRepository
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

# Private helper aliases retained for older integrations.
_parse_datetime = parse_search_datetime
_message_datetime = message_datetime
_snippet = search_snippet

__all__ = [
    "ChatMessageReference",
    "ChatSearchError",
    "ChatSearchHit",
    "ChatSearchPage",
    "ChatSearchRepository",
    "ChatSearchRepositoryError",
    "ChatSearchRequest",
    "ChatSearchService",
    "ChatSearchValidationError",
    "message_datetime",
    "parse_search_datetime",
    "search_snippet",
]
