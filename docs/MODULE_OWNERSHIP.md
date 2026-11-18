# KIRA MODULE OWNERSHIP

**Snapshot:** 2026-11-18  
**Source baseline:** `new-main` at `6c89820ce56be19654ddb08db6b719d041dc61d9`  
**Scope:** TASK 001–020 and adjacent application capabilities. This register describes observed ownership, not desired ownership where implementation is absent.

## 1. Ownership rules

1. A module owns its domain rules and public contract; callers coordinate through that contract.
2. Dependency Injection is the primary mechanism for supplying implementations and adapters.
3. EventBus/ChatEventPublisher is for notifications. It does not replace a direct API that returns a result.
4. Persistence owns durable storage, schema, transactions and recovery. Feature modules do not create parallel stores.
5. SessionManager owns runtime Session identity/state; SessionApplicationService coordinates application lifecycle, Conversation binding, profile synchronization and lifecycle notifications. Conversation Lifecycle owns durable Conversation state transitions.
6. Search owns message matching/ranking/pagination; Organization owns conversation metadata/filtering; Transfer owns serialization/import/export.
7. UI may adapt inputs, signals and rendering, but must not become a second owner of domain rules.
8. `kira/core` and `kira/domain` are inner layers: they must not import concrete application, UI, service, infrastructure or Qt modules.
9. Application services and lifecycle adapters must depend on structural contracts from Core. `kira/app/bootstrap.py` is the only application-layer composition point permitted to connect services to UI/Qt.
10. `ApplicationModule` receives the `DependencyRegistry` and `ModuleEventBus` ports; concrete `DependencyContainer` and `EventBus` implementations remain in the outer application layer.

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
| 008 | Events & Notifications — `kira/app/event_bus.py`, `kira/chat/events.py`, `kira/core/interfaces/application_module.py` | `EventBus`, Core `PublishedEvent` / `EventPublicationReport` / `ModuleEventBus`, `ChatEvent`, `ChatEventPublisher` | Feature-neutral Core event envelope and in-process notification bus | Business API routing, persistence ownership, request/session state transitions, direct dependency from the shared EventBus to Chat | None | **Sole shared notification transport**; Chat publisher owns typed event construction and terminal de-duplication |
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

### 2.2 TASK 017 — Session application orchestration

| Task | Module / canonical source | Public API / ownership | Allowed dependencies | Must not own / forbidden coupling |
|---|---|---|---|---|
| 017 | Session application — `kira/app/session_application.py`, `kira/app/session_composition.py` | `SessionApplicationService`: create/activate/list/dispose runtime Sessions, bind durable Conversation IDs through ChatApplicationService, translate SessionManager state changes, synchronize Sessions with Character profiles, restore history, check pending work and close removed/failed Sessions | SessionManager, ChatApplicationService, optional ChatEventPublisher, callback ports supplied by UI | PySide6, widgets, timers, worker construction, direct SQLite/persistence access, duplicate ownership of SessionManager's state machine |

Bootstrap injects a factory; MainWindow supplies a Qt-resource callback for views, timers and tab buttons. SessionManager remains the canonical runtime identity/state engine, while ChatApplicationService remains responsible for Chat request and persistence operations. Focused unit and wiring tests are included but runtime execution has not yet been verified.


### 2.3 TASK 018 — Web Search application policy

| Task | Module / canonical source | Public API / ownership | Allowed dependencies | Must not own / forbidden coupling |
|---|---|---|---|---|
| 018 | Web Search application — `kira/app/web_search.py` | `WebSearchApplicationService`: automatic/forced search eligibility and query planning (`plan_request`), Web/Image command parsing, diagnostics, engine labels, evidence/failure formatting, Gemini credential selection, follow-up query rewriting, request options and prepared-content merging | Settings snapshots, active Chat client, `kira.websearch` engine contracts, optional tool-plan summary | Qt, widgets, SearchWorker lifecycle, result presentation, direct provider/device construction, search policy duplicated in MainWindow |

The service is injected by Bootstrap into MainWindow. `plan_request` owns the automatic/forced one-shot search decision and suppresses duplicate web search when a local/tool plan takes precedence. Chat UI uses only the application service for command parsing, diagnostics and evidence formatting; it does not import `kira.websearch`. SearchWorker creation, signals and rendering remain UI responsibilities. Focused Qt-free tests cover normal, disabled, slash-command, forced and tool-plan precedence cases; execution/runtime acceptance is pending.


### 2.4 TASK 019 — Voice application lifecycle

| Task | Module / canonical source | Public API / ownership | Allowed dependencies | Must not own / forbidden coupling |
|---|---|---|---|---|
| 019 | Voice application — `kira/app/voice_application.py`, `voice_composition.py`, `kira/core/interfaces/voice_service.py` | `VoiceApplicationService`: microphone lifecycle, speech/stream/file playback delegation, wake/sleep/stop transcript decisions and speaking/mute coordination | Injected Speaker, Listener factory, callback ports and GUI signal relay | Qt imports, widgets, direct device construction, direct provider/device SDK ownership |

Bootstrap injects the Voice factory into MainWindow. Speaker and Listener remain device/Qt adapters; MainWindow relays Qt signals and renders state. Local STT settings-page test listeners remain a separate, explicitly scoped UI test workflow.

| 019 | Game Mode application — `kira/app/game_mode_application.py`, `kira/game_audio_policy.py` | `GameModeApplicationService`: profile permission decisions, input automation restrictions, game-audio importance/category/cooldown policy | Pure `game_mode_policy` and `game_audio_policy` functions | Qt, capture/device APIs, UI presentation |



### 2.6 TASK 020 — MainWindow feature dependency boundaries

| Task | Module / canonical source | Public API / ownership | Allowed dependencies | Must not own / forbidden coupling |
|---|---|---|---|---|
| 020 | MainWindow feature dependencies — `kira/ui/main_window_*_support.py` | One scoped dependency module for each of the nine feature mixins (root, attachments/vision, character settings, chat, lifecycle, provider settings, runtime, session and voice settings) | Feature-owned application/domain modules, Qt adapters, workers and the shared support helpers | Imports from another feature mixin; a global wildcard dependency barrel |

`main_window_support.py` is limited to SessionRelay, the front-only decorator, reaction loading and shared Qt signal/helper code. Feature support modules may import only this shared helper module, never another feature mixin or feature support module.

## 3. Cross-module API and dependency policy

### 3.1 Allowed high-level calls

- Bootstrap constructs the graph and injects the shared services and Session/Provider/Vision/Coding Agent/Runtime Settings application services.
- MainWindow calls ChatApplicationService for Chat submission, SessionApplicationService for Session lifecycle, ProviderApplicationService for provider/route/API policy, VisionApplicationService for capture policy, CodingAgentApplicationService for Coding Agent handoff, RuntimeSettingsApplicationService for shared settings propagation, CharacterProfileService for profile mutations, WebSearchApplicationService for search planning, VoiceApplicationService for voice lifecycle and GameModeApplicationService for permission/audio policy.
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
| Runtime Session identity/state | SessionManager + SessionApplicationService | SessionManager owns the state machine; SessionApplicationService coordinates profile lifecycle, Conversation binding and notifications |
| Durable Conversation status transitions | ConversationLifecycleService | Request transitions and consume results |
| Message text matching and result ranking | Search | Supply filters and display results |
| Conversation tags/folders/favorites/category/order | Organization | Request updates and display metadata |
| Transfer schema/preview/validation | Transfer | Supply export/import requests |
| Chat request orchestration | ChatApplicationService | Submit intents and consume events |
| Request FIFO admission | Coordinator | Submit immutable ChatRequest |
| Prompt assembly | ContextBuilder | Supply snapshots/enrichers |
| Provider stream normalization | ResponseHandler | Send provider-neutral events |
| Broadcast notification transport | EventBus / ChatEventPublisher | Publish/subscribe through injected instance |
| Provider/route/API settings | ProviderApplicationService | UI form input, confirmation and status display |
| Vision capture/cadence/result dedupe | VisionApplicationService | Capture images, start workers and render results |
| Coding Agent handoff policy | CodingAgentApplicationService | Render progress and own the existing agent adapter |
| Shared runtime settings propagation | RuntimeSettingsApplicationService | Collect and validate settings form values |
| Character profile/preferences/personality mutation | CharacterProfileService | Render profile forms and request mutations |

### 3.3 Dependency direction

The Chat core modules should depend on Python data contracts and narrow Protocol/callback ports, not on `MainWindow`, PySide6, provider SDKs or one another's private implementation. Where a module needs another module's capability, the application composition layer supplies the public contract. EventBus is not a workaround for an otherwise missing API.

## 4. Persistence boundaries in detail

- ChatPersistence/SqliteChatRepository owns Chat storage and transactions.
- SessionManager owns no durable rows and must remain independent of SQLite.
- Lifecycle policy is separate from repository transaction mechanics: Lifecycle validates transitions; Persistence atomically commits them.
- Organization owns the `organization` metadata namespace but not the metadata document storage mechanism.
- Organization writes use `ChatPersistence.mutate_conversations` and `mutate_all_conversations`: callbacks receive the latest row under a SQLite write transaction; bulk character-scoped updates commit or roll back as one unit.
- These transaction APIs preserve the complete metadata document and only persist the returned title/metadata fields; lifecycle status remains owned by the lifecycle transaction API.
- Search reads message pages and, when needed, conversation status through the injected repository.
- Transfer owns serialization and import validation; Persistence owns durable import transactions.
- AttachmentManager owns attachment processing/storage contracts and must not become a second Chat history store.

## 5. Application and non-Chat capability ownership

| Capability | Current source candidates / owners | Current integration boundary |
|---|---|---|
| Bootstrap & DI | `kira/app/bootstrap.py`, `dependency_container.py`, `module_manager.py` | Composition is centralized; only four required service modules are registered. |
| Character profiles | `kira/services/character_service.py`, `kira/characters`, CharactersPage | CharacterProfileService owns profile create/update/delete, preference/resource normalization and personality mutation; UI owns forms and Qt page coordination. |
| Memory | `kira/services`, `persona_memory.py`, `evidence_memory.py`, `memory.py` | Memory service is registered/injected; legacy sources/adapters remain. |
| Voice | `kira/core/interfaces/voice_service.py`, `kira/app/voice_application.py`, `voice_composition.py`, `voice.py`, `listener.py`, `local_voice.py` | VoiceApplicationService implements VoiceService and owns microphone lifecycle, speech/stream/file delegation and wake/sleep/stop transcript policy; Speaker/Listener remain injected adapters. |
| Avatar/emotion | `face.py`, `vrm_avatar.py`, `companion.py`, `emotion/*`, `body.py`, `rig.py` | Capability code exists; no independent lifecycle-managed feature module confirmed. |
| Tools/coding agent | `kira/app/coding_agent_application.py`, `tools/*`, `auto_agent.py`, `code_agent.py`, `chat_code.py` | CodingAgentApplicationService owns eligible handoff, attachment bypass and stop delegation; the current execution engine and UI worker adapters remain separate. |
| Web Research | `kira/app/web_search.py`, `webintel/*`, `websearch.py`, discovery adapters | WebSearchApplicationService owns credential/query/request/evidence policy; SearchWorker and result presentation remain UI adapters. |
| Vision | `kira/app/vision_application.py`, `vision_pipeline.py`, `vision_ocr.py` | VisionApplicationService owns capture eligibility, cadence/frame gating and duplicate-result suppression; Qt capture/timers/workers remain UI adapters. |
| UI | `ui/main_window.py`, `ui/main_window_composition.py`, feature mixins/support modules, pages/components/dialogs/workers | MainWindow is a compact Qt host; Session, Provider, Vision, Coding Agent, Runtime Settings and Character profile policies are delegated to services. Qt widget state, worker/timer lifetime, dialog flows and result rendering remain UI adapter responsibilities. |

Implementation and reviewer checklist for the current source delta: [ARCHITECTURE_IMPLEMENTATION_HANDOFF_2026-11-18.md](ARCHITECTURE_IMPLEMENTATION_HANDOFF_2026-11-18.md).

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
