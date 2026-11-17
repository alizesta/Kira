# Chat Events & Notification System (TASK 008)

## Ownership and composition

**kira/app/event_bus.py** remains the only in-process EventBus. TASK 008 extends that shared implementation; it does not create a second bus.

- **EventBus** owns subscriber registration, FIFO publication, callback fan-out, thread synchronization, delivery reports and shutdown.
- **ChatEvent** and **ChatEventType** in **kira/chat/events.py** define the immutable Chat notification contract and supported event names.
- **ChatEventPublisher** creates typed events and suppresses duplicate terminal notifications. It delegates delivery to the shared EventBus and does not own Chat state.
- Bootstrap constructs one EventBus and injects the same object into ModuleManager and ChatEventPublisher. ChatApplicationService owns request, stream and message-persistence publication because it owns those transitions. MainWindow publishes only session lifecycle and visible-history notifications until the separate Session Lifecycle extraction is merged.
- Coordinator, ResponseHandler and Persistence continue to own their existing responsibilities. Notifications report facts; they do not replace direct calls where a caller needs a return value or a guaranteed result.

## Event contract

Each ChatEvent is a frozen dataclass with:

| Field | Type | Meaning |
|---|---|---|
| event_id | string | Unique UUID-based event identity |
| event_type | ChatEventType | Validated event name |
| timestamp | timezone-aware datetime | Normalized to UTC |
| session_id | optional string | Owning character/session |
| request_id | optional string | Logical Chat request; omitted for session-wide facts |
| payload | immutable mapping | Event-specific data |
| metadata | immutable mapping | Correlation and producer annotations |

Nested mappings are read-only, sequences become tuples and sets become frozensets. Payload values are restricted to JSON-like immutable-compatible data; unsupported arbitrary objects are rejected instead of being shared between modules.

### Supported events and producer payloads

| Event | Producer meaning | Common payload fields |
|---|---|---|
| request_submitted | Request accepted into the Chat pipeline | attachment_count, voice, queued |
| request_started | The owning session begins processing the request | character_id |
| request_completed | The request reached a successful terminal result | content_length, response_status, persistence_ok |
| request_failed | Request ended unsuccessfully | error or reason |
| request_cancelled | User, session or application shutdown cancelled it | reason, persistence_ok |
| stream_started | A provider attempt began | provider_request_id, plain_retry |
| stream_chunk_received | A provider chunk was accepted by the response path | chunk, accumulated_length |
| stream_completed | Provider stream completed normally | content_length |
| stream_interrupted | Stream stopped or was interrupted | partial_length, reason |
| session_created | A character chat session was initialized | character_id, initial |
| session_activated | Session became the visible/active session | previous_session_id |
| session_deactivated | Session stopped being the visible/active session | next_session_id |
| session_closed | Session was removed or application shutdown closed it | reason |
| session_failed | Session setup failed while the legacy adapter was creating a character session | character_id, error; a future Session Lifecycle service may extend this to runtime failures |
| conversation_archived | Durable Conversation moved out of the active list | conversation_id, previous_status, new_status, changed_at, operation |
| conversation_restored | Archived Conversation returned to active | conversation_id, previous_status, new_status, changed_at, operation |
| conversation_trashed | Conversation soft-deleted and made recoverable | conversation_id, previous_status, new_status, changed_at, operation |
| conversation_restored_from_trash | Trashed Conversation returned to active | conversation_id, previous_status, new_status, changed_at, operation |
| conversation_permanently_deleted | Explicitly authorized trashed Conversation permanently removed | conversation_id, previous_status, new_status, changed_at, operation |
| message_saved | Message write succeeded | role, content, status, conversation_id |
| history_loaded | History read completed | message_count, conversation_id, limit |
| persistence_failed | History/message persistence operation failed | operation, role, status, error |

The request ID is stable across a queued request's admission and dispatch. The adapter preserves the original immutable ChatRequest through FIFO scheduling; it does not reconstruct a new request and accidentally change correlation identity. Provider-attempt IDs are included as payload data while the event's request ID remains the logical request identity.

## Subscription and publication

Subscribe to typed notifications through the publisher:

    from kira.chat import ChatEventType
    unsubscribe = chat_events.subscribe(ChatEventType.REQUEST_COMPLETED, on_request_completed)
    result = chat_events.publish(
        ChatEventType.REQUEST_COMPLETED,
        session_id="kira",
        request_id="request-uuid",
        payload={"content_length": 42, "persistence_ok": True},
    )
    if result.duplicate:
        ...  # a terminal notification for this lifecycle was already published
    unsubscribe()

Existing modules using EventBus.subscribe(name, callback) and publish(name, **payload) remain compatible. Typed consumers use subscribe_event() via ChatEventPublisher; legacy consumers on the same event name receive the typed envelope as keyword data.

## Delivery, ordering and failure policy

1. Subscriptions are recorded in registration order. Re-registering the same callback in the same delivery mode is a no-op; the returned unsubscriber is idempotent.
2. A publication takes a subscriber snapshot. Removing or adding subscriptions during a callback affects later publications, not the current snapshot.
3. All publications receive a monotonically increasing bus sequence and are processed FIFO. A publisher that becomes the dispatcher drains the queue synchronously. Concurrent and nested publishers enqueue without blocking and receive a queued=True report; the active dispatcher completes their fan-out in sequence.
4. A callback may publish recursively. Nested publications are queued until the current event has been delivered to its complete subscriber snapshot; this avoids recursive interleaving and deadlocks.
5. A failing subscriber is logged and included in EventPublishReport.failures. Other subscribers still run. The report records sequence, successful delivery count and subscriber errors.
6. Terminal notifications are de-duplicated by ChatEventPublisher: request terminal types share one request family; stream terminal types share one stream family per provider attempt (using payload.provider_request_id where available); and session close/failure share one session family. The bounded terminal ledger retains the most recent 8,192 lifecycle keys. A new session_created clears any stale terminal key for that session ID.
7. EventBus.close() releases all subscriptions and rejects later subscriptions/publications. Bootstrap closes it after ModuleManager shutdown so modules can unsubscribe during disposal.

The bus is thread-safe and callbacks run outside the subscription lock. Callbacks execute on the dispatcher thread (the thread that began draining); the bus does not marshal callbacks to Qt or any other event loop. A consumer that needs a specific thread must provide its own adapter. Delivery is synchronous for the thread that drains the queue. Recursive and concurrent publications never wait for the active callback; they return queued=True and are delivered after the current fan-out, avoiding callback-induced cross-thread deadlocks. Their eventual subscriber failures are logged by the dispatcher.

## Privacy and API boundary

message_saved carries message text because in-process consumers may need to index, display or classify the saved message. Subscribers are trusted in-process components and must not forward conversation content externally unless that module's own explicit feature contract authorizes it. The EventBus is not a persistence log, network transport, RPC layer or universal method router.

Use a direct service/API call whenever the caller needs a value, success/failure guarantee, mutation result or cancellation result. Publish a ChatEvent only after the owning component has made the corresponding state transition.

## Validation

Run the isolated non-GUI suite with:

    python -m unittest tests.test_chat_events -v

The tests cover immutable payloads, event catalog validation, fan-out, legacy API compatibility, duplicate subscriber prevention, unsubscription, subscriber failure isolation, snapshot semantics, nested and concurrent FIFO publication, session/request isolation, terminal de-duplication, bus cleanup, bootstrap wiring and request identity through queued dispatch. They do not import Qt or construct MainWindow.

