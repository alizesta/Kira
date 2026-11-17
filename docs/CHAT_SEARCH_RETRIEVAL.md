# Chat Search & Retrieval (TASK 011)

## Ownership

`kira/chat/search.py` owns message matching, filtering, relevance scoring, ordering,
pagination and result references. It has no Qt, MainWindow, widget, EventBus or
database dependency.

Persistence remains the source of truth. `ChatSearchService` receives a
`ChatSearchRepository` contract with one operation:
`messages_after(after_id, limit)`. The implementation supplied by
`ChatPersistence` delegates to the existing repository; SQLite remains owned by
`kira/chat/persistence.py`. Search does not create tables, indexes, files or a
parallel cache.

The cursor is ordered by monotonically increasing message ID, not timestamp.
This is important for imported legacy messages whose timestamps may predate newer
records: timestamp-based paging could skip records when combined with an ID cursor.

## Public API

The public contracts are exported from `kira.chat`:

- `ChatSearchRequest`: query, conversation/session ID, character ID, roles,
  inclusive start/end timestamps, match mode, sort order and page settings.
- `ChatSearchService(repository).search(request)`: executes a search.
  A string query plus keyword filters is also accepted.
- `ChatSearchPage`: result tuple, total count, page metadata and navigation flags.
- `ChatSearchHit`: message ID, conversation ID, character ID, sender role,
  full content, display snippet, timestamp, status, metadata, relevance score
  and a `ChatMessageReference`.
- `ChatSearchValidationError` and `ChatSearchRepositoryError`: distinguish
  invalid input from repository failures. A valid search with no matches returns
  an empty page and is not an error.

Example:

```python
from kira.chat import ChatPersistence, ChatSearchRequest, ChatSearchService

persistence = ChatPersistence(repository)
search = ChatSearchService(persistence)
page = search.search(ChatSearchRequest(
    query="connection timeout",
    character_id="kira",
    roles=("user", "assistant"),
    start_at="2026-01-01",
    sort_by="relevance",
    match_mode="phrase",
    page=1,
    page_size=20,
))
for hit in page.results:
    # Navigate to the source conversation and message using these stable IDs.
    print(hit.snippet, hit.reference.as_dict())
```

## Matching and filtering

- `exact`: the complete message text must equal the query (case-insensitive).
- `phrase`: case-insensitive contiguous phrase matching (default).
- `all_terms`: every token must occur in the message.
- `any_term`: at least one token must occur.
- Roles are limited to `user`, `assistant` and `system`.
- `conversation_id` and its `session_id` alias scope the same durable
  conversation. Supplying conflicting values is rejected.
- Date-only boundaries include the full selected day; timestamps accept ISO-8601
  values and are compared in UTC. Naive timestamps are treated as UTC, matching
  the persistence layer's current timestamp convention.
- Sort modes are `relevance`, `newest` and `oldest`; page size is capped at 100.

## Integration boundaries

The UI may construct a request, call the service and render the returned hits.
It must not implement matching, sorting or pagination itself. Application Service
may coordinate a search request when an application workflow needs it, but it
does not own the search algorithm. Commands & Actions may expose a future command
that delegates to this service. EventBus is not a search transport.

No MainWindow or Qt integration is required for the service contract. Existing
web/image research workers are separate capabilities and are not reclassified as
chat-history search.

## Compatibility and limitations

- Existing conversation and message rows are read without migration or mutation.
- Search scans the persisted message stream in bounded ID-ordered batches; it
  currently performs matching and ranking in process rather than using a new
  full-text index.
- Relevance is a deterministic occurrence-based score with a phrase/all-terms
  bonus, not semantic or embedding similarity.
- Result pagination is computed after collecting matches, so very large histories
  may require substantial memory and scan time. A database-backed full-text index
  can be considered later without changing the public request/result contracts.
- Messages without a valid role or with empty content are excluded. Date-filtered
  searches also exclude rows whose timestamp cannot be parsed.

## Validation policy for TASK 011

Contract tests are provided in `tests/test_chat_search.py`, but no tests,
Windows checks or GUI checks are run during this implementation task. They are
reserved for the explicitly announced integration-test phase.
