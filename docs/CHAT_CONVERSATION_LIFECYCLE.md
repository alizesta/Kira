# Chat Conversation Lifecycle — TASK 013

## Ownership and boundaries

`kira/chat/conversation_lifecycle.py` owns durable Conversation state transitions and their policy. It is a Qt-free service constructed with the shared `ChatPersistence` façade and the application's existing `ChatEventPublisher`.

- `ChatPersistence` / `SqliteChatRepository` remain the only owners of SQLite, schema, transactions, backups, message rows and durable reads/writes.
- Lifecycle owns legal state transitions, lifecycle timestamps, explicit permanent-delete authorization and operation results.
- `SessionManager` continues to own runtime Session identity and states (`created`, `active`, `idle`, `closing`, `closed`, `failed`). A Conversation is durable history; a Session is a runtime interaction. Neither ID nor lifecycle is substituted for the other.
- `ChatApplicationService` may coordinate calls to this API but does not own transition rules.
- `ChatEventPublisher` sends notifications through the same application EventBus. Notifications do not replace direct calls or their results.
- No Qt, MainWindow, widget, independent database, or second persistence layer is introduced.

## Durable representation

The existing `conversations.status` column is authoritative:

| Status | Meaning |
|---|---|
| `active` | Visible in the normal conversation list |
| `archived` | Hidden from the normal list; messages and metadata remain |
| `trashed` | Soft-deleted and recoverable until permanent deletion |
| `closed` | Legacy persistence status retained for compatibility; not a Session state |

Lifecycle timestamps are stored under the existing conversation metadata key `_conversation_lifecycle`: `archived_at`, `deleted_at`, `restored_at`, `restored_from_trash_at`, `last_operation` and `changed_at`. Other metadata keys are preserved. This uses the existing durable row and requires no parallel store or schema migration.

The atomic repository operation `update_conversation_lifecycle(changes)` validates every ID and expected prior status inside one `BEGIN IMMEDIATE` transaction. It changes only conversation status, metadata and `updated_at`; it never modifies message rows. A stale state or missing ID rejects the entire batch.

## Public API

Import the public contract from `kira.chat`:

- `ConversationLifecycleService(repository, event_publisher, clock=None)`
- `list_conversations(character_id=None, statuses=(ConversationStatus.ACTIVE,))`
- `archive(conversation_id)`, `archive_many(conversation_ids)`
- `restore(conversation_id)`
- `trash(conversation_id)`, `trash_many(conversation_ids)`
- `restore_trashed(conversation_id)`
- `permanent_delete(conversation_id, authorization=...)`

The repository is the shared `ChatPersistence` object. The publisher is the shared `ChatEventPublisher` created by bootstrap. No lifecycle service creates or owns an EventBus.

Every successful operation returns an immutable `ConversationLifecycleResult` with conversation ID, prior/new status, UTC change time, operation, success and whether its event was published. Missing IDs, invalid transitions, repository failures and missing authorization are explicit exceptions; lifecycle exceptions expose stable `error_code` values.

### Transition policy

- Archive: `active -> archived`; group archive is supported.
- Restore: `archived -> active`.
- Soft delete: `active|archived|closed -> trashed`; group soft delete is supported.
- Restore from trash: `trashed -> active`.
- Permanent delete: only one `trashed` conversation per call. The caller must supply an authorization provider whose `authorize_permanent_delete(conversation_id)` returns the literal boolean `True`. No bulk permanent-delete API exists.

Group operations prevalidate all IDs and transitions, then persist through one atomic repository transaction. Permanent deletion delegates to the existing repository deletion operation, which takes its safety snapshot and deletes only messages with the selected `conversation_id` plus that conversation row. It does not delete Session state or messages belonging to other conversations.

No automatic retention or purge runs. Retention policy is intentionally not inferred; any future purge must be an explicit separately authorized operation.

## Events

The shared `ChatEventPublisher` publishes:

- `conversation_archived`
- `conversation_restored`
- `conversation_trashed`
- `conversation_restored_from_trash`
- `conversation_permanently_deleted`

Payloads contain `conversation_id`, `previous_status`, `new_status`, `changed_at` and `operation`. Events are emitted after durable commit. If notification delivery fails, the result reports `event_published=False`; the committed state is not misrepresented as rolled back.

## Search and transfer compatibility

`ChatSearchRequest.conversation_statuses` optionally filters results by `active`, `archived`, `trashed` and/or legacy `closed`. An empty tuple preserves the previous all-status search behavior. Filtering reads conversation rows from the same injected persistence repository.

TASK 012 export already serializes conversation status and metadata; its import validator now accepts `trashed` as well as the prior statuses. The lifecycle timestamps therefore travel with conversation metadata. Import remains owned by `ChatTransfer`; it does not execute lifecycle operations.

## Validation status and limitations

- Static source and contract review only. No tests, compile/import checks, GUI/Windows checks or application execution are permitted during TASK 013 implementation.
- Permanent deletion relies on the existing repository snapshot-and-delete operation. Cross-table foreign-key/dependency inventory beyond the current repository contract is not exposed; new external references must add a repository-level dependency guard before permanent deletion is enabled for those records.
- Retention scheduling and automatic cleanup are intentionally not implemented.
- The API is independent and publicly exported. The composition root injects the lifecycle owner into `ChatApplicationService`, which exposes thin delegation methods for listing, archive, restore, soft delete and authorized permanent delete. It contains no transition rules; MainWindow and commands can call the application contract without duplicating lifecycle policy.
