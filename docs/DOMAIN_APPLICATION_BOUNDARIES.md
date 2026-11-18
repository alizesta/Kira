# Domain and Application Boundary — Flow 2

**Target:** `new-main`  
**Work branch:** `architecture/domain-application-contracts`  
**Scope:** Domain rules, Application use cases and Core-owned cross-layer ports.  
**Coordination:** UI/controller internals remain owned by Flow 1.

## Current architectural correction

The architecture boundary test and module ownership register already described
`kira/domain` as an inner layer, but the package did not exist on the current
base. The Conversation lifecycle rules were still declared inside
`kira/chat/conversation_lifecycle.py`.

This flow introduces the pure `kira/domain` package and moves the durable
Conversation status vocabulary, operation vocabulary, lifecycle errors, result
contract and allowed-source-state rules into `kira/domain/conversations.py`.
The Chat lifecycle service remains the application coordinator: it validates
repository records against Domain rules, commits through the existing atomic
Persistence API, then publishes notifications.

Existing imports from `kira.chat.conversation_lifecycle` remain compatible
through re-exports. No persistence schema, table, metadata format or public
lifecycle operation was intentionally changed.

## Core-owned ports

The following structural contracts now live under `kira/core/interfaces`:

- `SessionManagerPort` and `RuntimeSessionPort`: runtime Session lifecycle
  and data needed by application orchestration.
- `ChatApplicationPort`: conversation binding and pending-work queries
  required by Session orchestration.
- `ApplicationEventPublisherPort`: notification-only application event
  publication.
- `ConversationLifecycleRepositoryPort`: durable lifecycle reads and atomic
  writes.
- `ConversationEventPublisherPort`: post-commit lifecycle notifications.
- `PermanentDeleteAuthorizationPort`: explicit authorization for deletion
  of one exact Conversation.

`SessionApplicationService` now depends on the Core-owned structural ports
instead of accepting untyped `Any` collaborators. The Conversation lifecycle
service also consumes the Core-owned repository, publisher and authorization
ports. Compatibility aliases preserve existing imports from its former module.

## Dependency rules

- Domain imports only the standard library and other Domain modules.
- Core contracts do not import Application, Chat implementation, UI, Qt or
  Infrastructure implementations.
- Application services orchestrate Domain rules through narrow ports.
- Persistence remains the sole owner of durable records and transactions.
- Event publication is a notification side effect after successful durable
  commits; it is not used as a synchronous service locator.
- Flow 1 may change controllers and UI adapters, but must consume these public
  contracts rather than reaching into Domain or Persistence internals.

## Verification added

- `tests/test_domain_conversation_rules.py` covers the allowed source states
  for archive, restore, trash, restore-from-trash and permanent deletion.
- `tests/test_application_service_ports.py` verifies the concrete Session
  manager/session and representative Chat/Event publisher adapters satisfy the
  Core structural contracts.
- `tests/test_architecture_boundaries.py` now fails if the Domain package is
  absent or Core/Domain contain no explicit source contracts.
- Both the Chat Session Lifecycle and portable release workflows include the
  new focused tests; the lifecycle workflow also compiles the new source files.

## Remaining Flow 2 work

This is a first bounded extraction, not a claim that all Domain/Application
work is complete. Remaining candidates require incremental migration with
compatibility tests:

1. Extract the pure Conversation organization rules and metadata value
   contracts from `kira/chat/organization.py` into Domain.
2. Separate Search query/filter/result value contracts from repository paging
   orchestration.
3. Review Chat request/response DTO ownership and replace remaining broad
   `Any` collaborator types with Core ports where a stable boundary exists.
4. Review each existing Application service's use cases and failure semantics;
   do not create duplicate services or move Qt worker/device lifecycle into
   Application.
5. Keep compatibility facades until call sites and tests prove they can be
   removed safely.

No claim of test execution, CI success, Windows GUI acceptance or runtime
acceptance is made by this document.
