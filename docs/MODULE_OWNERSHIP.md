# KIRA MODULE OWNERSHIP

**Snapshot:** 2026-11-17  
**Base:** `new-main` at `b54d092a330b6383ca4244320ffaeec9267db561`  
**Scope:** TASK 001–014 and adjacent application capabilities. This register describes observed ownership, not desired ownership where implementation is absent.

## 1. Ownership rules

1. A module owns its domain rules and public contract; callers coordinate through that contract.
2. Dependency Injection is the primary mechanism for supplying implementations and adapters.
3. EventBus/ChatEventPublisher is for notifications. It does not replace a direct API that returns a result.
4. Persistence owns durable storage, schema, transactions and recovery. Feature modules do not create parallel stores.
5. SessionManager owns runtime Session identity/state. Conversation Lifecycle owns durable Conversation state transitions.
6. Search owns message matching/ranking/pagination; Organization owns conversation metadata/filtering; Transfer owns serialization/import/export.
7. UI may adapt inputs, signals and rendering, but must not become a second owner of domain rules.

## 2. TASK 001–014 module register

| Task | Module / canonical source | Public API / contract | Allowed dependencies | Must not own / forbidden coupling | Persistence ownership | Events |
|---|---|---|---|---|---|---|
| 001 | Architecture Foundation — `kira/main.py`, `kira/app/bootstrap.py`, `dependency_container.py`, `module_manager.py`, `event_bus.py` | `main()`, `run_application()`, `DependencyContainer`, `ModuleManager`, `EventBus` | Startup infrastructure, factories, service interfaces, UI composition boundary | Domain logic in entry point; feature services constructing global dependencies; EventBus as service locator | None; registers/injects persistence adapters | Owns shared bus infrastructure |
| 002 | Chat Coordinator — `kira/chat/coordinator.py` | `ChatRequest`, `SubmissionResult`, `ChatCoordinator.submit/take_next/clear/start_provider_request`, `ChatProviderDispatcher` | Immutable request data, injected dispatch/provider-worker adapter | Qt widgets, MainWindow, provider SDK clients, persistence, SessionManager state | None | No domain event ownership; dispatch callbacks injected |
| 003 | Context & Prompt Builder — `kira/chat/context_builder.py` | `ContextRequest`, `ContextResult`, `ContextBuilder.build()` | Standard library, injected system-prompt builder/enrichers, immutable context snapshots | UI objects, storage/database, provider routing, session queues, tools execution | None; caller supplies history/memory/context | None |
| 004 | Response Handler — `kira/chat/response_handler.py` | `ProviderEvent`, `ChatResponseResult`, `ResponseStreamEvent`, `ResponseHandler.begin_request/handle` | Provider-neutral event data and request/session IDs | Qt, provider SDKs, UI, persistence, prompt construction, queue ownership | None; caller persists outcomes | Normalizes response lifecycle; publication is delegated to application layer |
| 005 | Persistence & History — `kira/chat/persistence.py`, Chat History adapter | `ChatRepository`, `SqliteChatRepository`, `ChatPersistence` and repository/facade operations | SQLite/infrastructure, repository contracts, transaction/recovery code | Search ranking, lifecycle policy, organization rules, UI widgets, second database | **Sole Chat durable-storage owner** | No business notification ownership |
| 006 | Chat Application Service — `kira/chat/application_service.py`, `kira/app/chat_composition.py` | `ChatApplicationService`: submit/start/handle/complete/cancel/status/dispatch/session-close/dispose and history facade methods | Injected persistence, coordinator/context/response/attachment/command contracts, worker factory, callback/scheduler ports, event publisher | Qt widgets, direct provider SDK ownership, SQL/schema, duplicated domain rules from other services | Uses Persistence; does not own schema/transactions | Coordinates application events via injected publisher/callback |
| 007 | Session Lifecycle — `kira/chat/session_manager.py`, `kira/chat_sessions.py` | `SessionManager`, runtime Session records and character/session lookup | Session factory/type, character/session identifiers | Durable Conversation status, message history, SQL, archive/trash rules | None | Session notifications may be published by application event layer |
| 008 | Events & Notifications — `kira/app/event_bus.py`, `kira/chat/events.py` | `EventBus`, `ChatEvent`, `ChatEventPublisher`, typed event enums | Shared in-process bus, immutable event payloads | Business API routing, persistence ownership, request/session state transitions | None | **Sole shared notification transport**; terminal event de-duplication is publisher-local |
| 009 | Attachments & Content Processing — `kira/chat/attachments.py`, `attachment_content.py` | Attachment records/manager and bounded content extraction contracts | Injected storage/path adapters, parser adapters and immutable content data | Qt widgets, chat queue ownership, prompt policy, durable Conversation lifecycle | Owns attachment records/content processing boundary; not Chat history database | Reports attachment outcomes through caller/application callbacks |
| 010 | Commands & Actions — `kira/chat/commands.py`, `command_adapters.py` | `CommandRegistry`, `CommandDefinition`, `CommandRequest`, `CommandResult`, adapters | Injected handlers, permission checker, immutable request/session context | Hard-coded Kira persona policy, persistence, UI rendering, unrestricted direct system execution | None | Command results/events are relayed by application layer |
| 011 | Search & Retrieval — `kira/chat/search.py` | `ChatSearchRequest`, `ChatSearchHit`, `ChatSearchPage`, `ChatSearchService.search()` | Injected `messages_after` repository reader; optional conversation listing for status filter | SQL ownership, writing/deleting records, conversation organization policy, UI widgets | Read-only through Persistence | None |
| 012 | Export & Import — `kira/chat/transfer.py` | Versioned transfer service, preview/validation/import/export contracts | Injected persistence transaction boundary, JSON data contracts | Direct SQL, search ranking, lifecycle transition policy, UI widgets | Persistence owns import transactions and durable writes; Transfer owns transfer format/validation | Outcomes returned to caller; notifications via application layer |
| 013 | Conversation Lifecycle — `kira/chat/conversation_lifecycle.py` | `ConversationLifecycleService`: list/archive/archive_many/restore/trash/trash_many/restore_trashed/permanent_delete | Shared `ChatPersistence`, shared `ChatEventPublisher`, clock/authorization provider | Runtime Session state, message search, organization metadata, direct SQL, automatic purge | Persistence performs atomic status writes and guarded deletion; Lifecycle owns transition policy | Five lifecycle notifications published after durable commit |
| 014 | Metadata & Organization — `kira/chat/organization.py` | `ChatOrganizationService`: rename/tag/folder/favorite/metadata/filter APIs | Injected organization repository (ChatPersistence facade), optional shared event publisher | Session lifecycle, Conversation archive/trash/delete, message search, SQL, UI widgets | Persistence stores namespaced `metadata.organization`; Organization owns metadata rules | `conversation_metadata_updated` through shared publisher |

### 2.1 Status on current `new-main`

| Task | TASK 015 audit status | Current static integration status |
|---|---|---|
| 001–012 | DONE (TASK 010 was corrected to DONE in the final audit update) | Present on the audited base; public contracts remain documented |
| 013 | PARTIAL at audit time | Integrated by merged PR #48; source and docs are present on current `new-main` |
| 014 | PARTIAL at audit time | Integrated by merged PR #48; source and docs are present on current `new-main` |

The historical audit counts remain 12 DONE / 2 PARTIAL. The post-audit merge is recorded separately; no runtime status is inferred.

### 2.2 TASK 018 — Web Search application policy

| Task | Module / canonical source | Public API / ownership | Allowed dependencies | Must not own / forbidden coupling |
|---|---|---|---|---|
| 018 | Web Search application — `kira/app/web_search.py` | `WebSearchApplicationService`: Gemini credential selection, follow-up query rewriting, web/image request options, search evidence formatting and prepared-content merging | Settings snapshots, active Chat client, `kira.websearch` engine contracts | Qt, widgets, SearchWorker lifecycle, result presentation, direct provider/device construction |

The service is injected by Bootstrap into MainWindow. SearchWorker creation, signals and rendering remain UI responsibilities. Focused Qt-free tests are included; execution/runtime acceptance is pending until CI can allocate a runner.

## 3. Cross-module API and dependency policy

### 3.1 Allowed high-level calls

- Bootstrap constructs the graph and injects the shared services.
- MainWindow calls ChatApplicationService for Chat submission, request lifecycle and history operations, and delegates Web Search policy to the injected WebSearchApplicationService.
- ChatApplicationService calls its injected Coordinator, ContextBuilder, ResponseHandler, AttachmentManager, command port and persistence/history contract.
- Search receives a read-only persistence reader and returns immutable result/page contracts.
- Transfer validates and maps the transfer format, then delegates durable import to Persistence.
- ConversationLifecycleService delegates atomic durable writes to Persistence and publishes lifecycle notifications after commit.
- ChatOrganizationService delegates metadata reads/writes to Persistence and publishes metadata notifications.
- Observers subscribe to EventBus/ChatEventPublisher; they do not use events to synchronously request domain operations.

### 3.2 Forbidden ownership overlap

| Concern | Sole policy owner | Other modules may |
|---|---|---|
| Durable Chat records, schema and transactions | Persistence | Call facade/repository contracts |
| Runtime Session identity/state | SessionManager | Carry session IDs and request lifecycle callbacks |
| Durable Conversation status transitions | ConversationLifecycleService | Request transitions and consume results |
| Message text matching and result ranking | Search | Supply filters and display results |
| Conversation tags/folders/favorites/category/order | Organization | Request updates and display metadata |
| Transfer schema/preview/validation | Transfer | Supply export/import requests |
| Chat request orchestration | ChatApplicationService | Submit intents and consume events |
| Request FIFO admission | Coordinator | Submit immutable ChatRequest |
| Prompt assembly | ContextBuilder | Supply snapshots/enrichers |
| Provider stream normalization | ResponseHandler | Send provider-neutral events |
| Broadcast notification transport | EventBus / ChatEventPublisher | Publish/subscribe through injected instance |

### 3.3 Dependency direction

The Chat core modules should depend on Python data contracts and narrow Protocol/callback ports, not on `MainWindow`, PySide6, provider SDKs or one another's private implementation. Where a module needs another module's capability, the application composition layer supplies the public contract. EventBus is not a workaround for an otherwise missing API.

## 4. Persistence boundaries in detail

- ChatPersistence/SqliteChatRepository owns Chat storage and transactions.
- SessionManager owns no durable rows and must remain independent of SQLite.
- Lifecycle policy is separate from repository transaction mechanics: Lifecycle validates transitions; Persistence atomically commits them.
- Organization owns the `organization` metadata namespace but not the metadata document storage mechanism.
- Search reads message pages and, when needed, conversation status through the injected repository.
- Transfer owns serialization and import validation; Persistence owns durable import transactions.
- AttachmentManager owns attachment processing/storage contracts and must not become a second Chat history store.

## 5. Application and non-Chat capability ownership

| Capability | Current source candidates / owners | Current integration boundary |
|---|---|---|
| Bootstrap & DI | `kira/app/bootstrap.py`, `dependency_container.py`, `module_manager.py` | Composition is centralized; only four required service modules are registered. |
| Character profiles | `kira/services`, `kira/character`, `kira/characters`, CharactersPage | Profile service and UI page exist; MainWindow still handles session/UI policy. |
| Memory | `kira/services`, `persona_memory.py`, `evidence_memory.py`, `memory.py` | Memory service is registered/injected; legacy sources/adapters remain. |
| Voice | `voice.py`, `listener.py`, `local_voice.py`, VAD/speech modules, VoicePage | Implementation exists; Voice interface is not yet wired through the implementation. |
| Avatar/emotion | `face.py`, `vrm_avatar.py`, `companion.py`, `emotion/*`, `body.py`, `rig.py` | Capability code exists; no independent lifecycle-managed feature module confirmed. |
| Tools/coding agent | `tools/*`, `actions.py`, `auto_agent.py`, `code_agent.py`, `chat_code.py` | Existing tools/agent integration remains application/legacy-bound; Chat command contracts are separate. |
| Web Research | `kira/app/web_search.py`, `webintel/*`, `websearch.py`, discovery adapters | WebSearchApplicationService owns credential/query/request/evidence policy; SearchWorker and result presentation remain UI adapters. |
| Vision | `vision_pipeline.py`, `vision_ocr.py`, game detection/mode/audio | Capability code exists; dedicated application-service ownership not established by this audit. |
| UI | `ui/main_window.py`, `ui/main_window_*.py`, `ui/pages`, `ui/components`, `ui/dialogs`, `ui/workers.py` | MainWindow is composed from eight feature-oriented mixins; cross-feature policy still remains in the window adapter. |

## 6. Character scope

Character-specific identity/profile data is input to otherwise generic Chat contracts. Request/session identity must be captured at submission and preserved through provider callbacks and persistence. Durable history must be filtered by character/conversation scope. Shared capabilities must not encode a Kira-only default as business policy; legacy `DEFAULT_CHARACTER = "kira"` is a compatibility fallback, not a general capability owner.

Static code supports this design. Runtime isolation across concurrent sessions, restart, search, transfer and memory remains unverified.

## 7. Legacy and compatibility owners

- `kira.main.MainWindow` is a lazy compatibility export to `kira.ui.main_window.MainWindow`.
- `kira.ui.main_window.MainWindow` is the production UI adapter; its feature behavior is split across `kira/ui/main_window_*.py` mixins.
- `kira/oldmain.py` has been removed; new production code must not reintroduce imports from that path.
- `kira/services/chat_history_service.py` is an adapter over the persistence facade; it is not a second database owner.
- `kira/attachments.py` is a compatibility facade; canonical Chat attachment/content processing is under `kira/chat/`.
- `kira/memory.py` and `kira/persona_memory.py` remain legacy/compatibility memory paths while service boundaries are adopted.

These compatibility paths should be removed only after static call-site review and an approved migration; TASK 016 does not remove them.
