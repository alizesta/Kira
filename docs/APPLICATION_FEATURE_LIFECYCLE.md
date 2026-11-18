# Flow 4 — Application Feature Lifecycle and Composition Wiring

**Parent:** Flow 2 — `architecture/domain-application-contracts` (PR #74)  
**Work branch:** `codex/flow4-application-lifecycle-wiring`  
**Target after parent integration:** `new-main`  
**Coordination:** Flow 1 owns controller consumption; Flow 3 owns the concrete Transfer file Infrastructure adapter.

## Implemented service registrations

The application feature registry now manages four shared Chat use cases through
`ServiceModule` and `ModuleManager`:

| Module ID | DI service key | Implementation |
|---|---|---|
| `conversation_lifecycle` | `conversation_lifecycle_service` | `kira.chat.conversation_lifecycle.ConversationLifecycleService` |
| `conversation_organization` | `conversation_organization_application_service` | `kira.app.organization_application.ChatOrganizationService` |
| `chat_search` | `chat_search_application_service` | `kira.app.chat_search_application.ChatSearchService` |
| `chat_transfer` | `chat_transfer_application_service` | `kira.app.chat_transfer_application.ChatTransfer` |

The Conversation Lifecycle, Organization, Search and Transfer modules all
depend on `chat_history`. The dependency graph therefore starts and registers
Persistence before any of these use cases. `chat_application` depends on both
`chat_history` and `conversation_lifecycle`, so its factory can close over the
single lifecycle service instance. ModuleManager
stops/disposes them in reverse creation order, before Chat History is flushed
and released.

The services are application-scoped and character-neutral. Character/conversation
scope is supplied by each use-case request; no Kira-only policy is hard-coded
into the registration factory.

## Persistence adapter capabilities

`ChatHistoryService` and `SqliteChatHistoryService` now expose the additional
capabilities required by the new use cases:

- Atomic `mutate_conversations` and `mutate_all_conversations` delegation for
  Organization metadata updates.
- Monotonically ordered `messages_after` pages for Search.
- Bounded `get_transfer_messages` reads and `import_transfer_records`
  delegation for Transfer.

These methods remain adapters over the existing `ChatPersistence`/
`SqliteChatRepository`. No SQL or transaction implementation was moved into
Application or Core.

## Dependency injection

- Conversation Lifecycle receives the shared Chat History adapter and the
  `ChatEventPublisher` for post-commit lifecycle notifications.
- Organization receives the shared Chat History adapter and the shared
  `ChatEventPublisher` for post-commit metadata notifications.
- Search receives the shared Chat History adapter as its message reader and
  explicitly as its Conversation status reader.
- Transfer receives the shared Chat History adapter and the optional
  `ChatTransferFilePort`.
- The `register_application_modules` factory override mechanism remains
  available for tests and alternate persistence/file adapters.
- Bootstrap resolves the Organization/Search/Transfer service keys and passes
  them through `initialize_main_window`. It resolves the Conversation Lifecycle
  dependency when constructing the Chat factory. MainWindow stores the three
  feature-service references; controllers may
  consume them through their explicit Flow 1 boundaries.
- Bootstrap exposes `run_application(transfer_file_port=...)` so Flow 3's
  concrete file adapter can be supplied without coupling Application to a
  filesystem implementation.

The current default is `transfer_file_port=None`, which preserves the
compatibility file-I/O fallback in ChatTransfer until Flow 3 implements and
injects the adapter. Flow 4 defines and wires the injection point, not the
concrete filesystem adapter.

## Lifecycle and failure semantics

The existing required-module policy is preserved. If Chat History fails to
start, its dependent Lifecycle/Organization/Search/Transfer module cannot start; the
desktop Composition Root sees the failed module state and shuts down the graph.
The new services have no independent worker/device lifecycle. ServiceModule
still owns their registration/unregistration, while Chat History remains
responsible for DB initialization and flushing.

## Verification added and wired

- `tests/test_feature_module_registration.py`: module registration, shared
  repository injection, real use-case calls, Transfer file-port injection,
  dependency ordering and reverse shutdown.
- `tests/test_chat_history_service_capabilities.py`: verifies that the
  `SqliteChatHistoryService` adapter delegates atomic Organization operations,
  Search paging and Transfer read/import calls to Persistence.
- `tests/test_composition_root_contract.py`: checks that Bootstrap resolves
  and injects all three services and exposes the Transfer file-port parameter.
- Chat Session Lifecycle and portable release workflows include the new tests.
- The Chat Session Lifecycle workflow also targets the Flow 2 parent branch so
  this nested Flow 4 PR receives the focused checks.

## Explicit remaining work

- Flow 3 must implement a concrete `ChatTransferFilePort` Infrastructure
  adapter and supply it to `run_application(transfer_file_port=...)`.
- Flow 1 must migrate the relevant feature controllers to consume the injected
  Organization/Search/Transfer application services rather than reaching into
  implementation modules.
- Flow 4 does not replace the existing Chat/Session/Voice window-scoped
  factories, move UI worker lifecycle into Application, or change Persistence
  ownership.

## Verification boundary

The changes and test wiring have been reviewed through GitHub source inspection.
Python tests, `py_compile`, GitHub Actions execution and Windows GUI/runtime
acceptance are not yet claimed. Results will be reported only from actual
execution evidence.
