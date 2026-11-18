# KIRA MODULE OWNERSHIP

**Snapshot:** 2026-11-18  
**Source baseline:** `new-main` at `e398ed518ef446600ef758288f1dca2803845d98`  
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
9. Application services and lifecycle adapters must depend on structural contracts from Core. `kira/ui/bootstrap.py` is the only outer-layer composition point permitted to connect services to UI/Qt; `kira/app` remains toolkit-independent.
10. `ApplicationModule` receives the `DependencyRegistry` and `ModuleEventBus` ports; concrete `DependencyContainer` and `EventBus` implementations remain in the outer application layer.

## 2. TASK 001–014 module register

| Task | Module / canonical source | Public API / contract | Allowed dependencies | Must not own / forbidden coupling | Persistence ownership | Events |
|---|---|---|---|---|---|---|
| 001 | Architecture Foundation — `kira/main.py`, `kira/ui/bootstrap.py`, `dependency_container.py`, `module_manager.py`, `event_bus.py` | `main()`, `run_application()`, `DependencyContainer`, `ModuleManager`, `EventBus` | Startup infrastructure, factories, service interfaces, UI composition boundary | Domain logic in entry point; feature services constructing global dependencies; EventBus as service locator | None; registers/injects persistence adapters | Owns shared bus infrastructure |
| 002 | Chat Coordinator — `kira/domain/chat.py`, `kira/chat/coordinator.py` | Domain `ChatRequest` and `SubmissionResult`; `ChatCoordinator.submit/take_next/clear/start_provider_request`, `ChatProviderDispatcher` | Immutable Domain request values, injected dispatch/provider-worker adapter | Qt widgets, MainWindow, provider SDK clients, persistence, SessionManager state | None | No domain event ownership; dispatch callbacks injected |
| 003 | Context & Prompt Builder — `kira/chat/context_builder.py` | `ContextRequest`, `ContextResult`, `ContextBuilder.build()` | Standard library, injected system-prompt builder/enrichers, immutable context snapshots | UI objects, storage/database, provider routing, session queues, tools execution | None; caller supplies history/memory/context | None |
| 004 | Response Handler — `kira/domain/chat.py`, `kira/chat/response_handler.py` | Domain `ProviderEvent`, `ChatResponseResult`, `ResponseStreamEvent` and status/error values; `ResponseHandler.begin_request/handle` | Provider-neutral Domain event data and request/session IDs | Qt, provider SDKs, UI, persistence, prompt construction, queue ownership | None; caller persists outcomes | Normalizes response lifecycle; publication is delegated to application layer |
| 005 | Persistence & History — `kira/chat/persistence.py`, Chat History adapter | `ChatRepository`, `SqliteChatRepository`, `ChatPersistence` and repository/facade operations | SQLite/infrastructure, repository contracts, transaction/recovery code | Search ranking, lifecycle policy, organization rules, UI widgets, second database | **Sole Chat durable-storage owner** | No business notification ownership |
| 006 | Chat Application Service — `kira/domain/chat.py`, `kira/chat/application_service.py`, `kira/app/chat_composition.py` | Domain `ChatApplicationRequest`, `ChatApplicationEvent`, `RequestStatus`, `ApplicationEventKind`, `Submission`, `PersistenceOutcome`; `ChatApplicationService` submit/start/handle/complete/cancel/status/dispatch/session-close/dispose/history APIs | Injected Persistence, Coordinator/Context/Response/Attachment/Command contracts, worker factory, callback/scheduler ports, event publisher | Qt widgets, direct provider SDK ownership, SQL/schema, duplicated domain rules from other services | Uses Persistence; does not own schema/transactions | Coordinates application events via injected publisher/callback |
| 007 | Session Lifecycle — `kira/chat/session_manager.py`, `kira/chat_sessions.py` | `SessionManager`, runtime Session records and character/session lookup | Session factory/type, character/session identifiers | Durable Conversation status, message history, SQL, archive/trash rules | None | Session notifications may be published by application event layer |
| 008 | Events & Notifications — `kira/app/event_bus.py`, `kira/chat/events.py`, `kira/core/interfaces/application_module.py` | `EventBus`, Core `PublishedEvent` / `EventPublicationReport` / `ModuleEventBus`, `ChatEvent`, `ChatEventPublisher` | Feature-neutral Core event envelope and in-process notification bus | Business API routing, persistence ownership, request/session state transitions, direct dependency from the shared EventBus to Chat | None | **Sole shared notification transport**; Chat publisher owns typed event construction and terminal de-duplication |
| 009 | Attachments & Content Processing — `kira/chat/attachments.py`, `attachment_content.py` | `AttachmentManager` records, validation, managed storage, bounded extraction and legacy payload composition | Injected storage/path adapters, parser adapters and immutable content data; ChatApplicationService exposes preparation, per-message limits and fallback composition to UI callers | Qt widgets, Chat request queue, prompt policy, durable Conversation lifecycle | Owns attachment records/content processing boundary; not Chat history database | ChatApplicationService is the UI-facing application boundary for attachment composition and preparation |
| 010 | Commands & Actions — `kira/chat/commands.py`, `command_adapters.py` | `CommandRegistry`, `CommandDefinition`, `CommandRequest`, `CommandResult`, adapters | Injected handlers, permission checker, immutable request/session context | Hard-coded Kira persona policy, persistence, UI rendering, unrestricted direct system execution | None | Command results/events are relayed by application layer |
| 011 | Search & Retrieval — `kira/domain/search.py`, `kira/app/chat_search_application.py`, `kira/core/interfaces/search.py` | Domain `ChatSearchRequest`, `ChatSearchHit`, `ChatSearchPage`; Application `ChatSearchService.search()` | Read-only `ChatSearchRepositoryPort`; optional `ConversationStatusReaderPort` | SQL ownership, persistence writes, conversation organization policy, UI widgets | Read-only through Persistence | None |
| 012 | Export & Import — `kira/domain/transfer.py`, `kira/app/chat_transfer_application.py`, `kira/core/interfaces/transfer.py` | Domain transfer schema/value contracts; Application `ChatTransfer.export_data/preview_import/import_data` | `ChatTransferRepositoryPort`, bounded JSON data contracts | Direct SQL, search ranking, lifecycle transition policy, UI widgets | Persistence owns import transactions and durable writes; Domain owns transfer invariants | Outcomes returned to caller; notifications via application layer |
| 013 | Conversation Lifecycle — `kira/chat/conversation_lifecycle.py` | `ConversationLifecycleService`: list/archive/archive_many/restore/trash/trash_many/restore_trashed/permanent_delete | Shared `ChatPersistence`, shared `ChatEventPublisher`, clock/authorization provider | Runtime Session state, message search, organization metadata, direct SQL, automatic purge | Persistence performs atomic status writes and guarded deletion; Lifecycle owns transition policy | Five lifecycle notifications published after durable commit |
| 014 | Metadata & Organization — `kira/domain/organization.py`, `kira/app/organization_application.py`, `kira/core/interfaces/organization.py` | Domain organization values/validation; Application `ChatOrganizationService`: rename/tag/folder/favorite/metadata/filter APIs | `ConversationOrganizationRepositoryPort`, `ConversationMetadataEventPublisherPort` | Session lifecycle, Conversation archive/trash/delete, message search, SQL, UI widgets | Persistence stores namespaced `metadata.organization`; Domain owns metadata rules | `conversation_metadata_updated` through shared publisher |

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



### 2.5 Extended application policy boundaries

| Capability | Module / canonical source | Public API / ownership | Allowed dependencies | Must not own / forbidden coupling |
|---|---|---|---|---|
| Provider / routes | `kira/app/provider_application.py` | `ProviderApplicationService`: provider and API registry operations, route mutation/selection, Ollama settings validation/client creation, router creation and per-session router replacement | Existing route/API registry contracts, provider/router factories | Qt widgets, UI dialogs, direct MainWindow references |
| Vision | `kira/app/vision_application.py` | `VisionApplicationService`: capture permission, policy/cadence, busy-state admission, frame deduplication, result deduplication and latency statistics | Vision pipeline and GameModeApplicationService | Qt screen capture, timers, worker threads, UI presentation |
| Coding Agent | `kira/app/coding_agent_application.py` | `CodingAgentApplicationService`: attachment-free turn handoff, local request completion and session stop delegation | Existing CodeChat execution adapter and completion callback | Agent runtime implementation, widgets, persistence |
| Runtime settings | `kira/app/runtime_settings_application.py` | `RuntimeSettingsApplicationService`: initial configuration and propagation of shared settings to evidence memory, usage and optional ToolAgent | Existing shared capability contracts | Settings widgets/dialogs, UI rendering |
| Shared Skills | `kira/skills/registry.py`, `kira/skills/service.py`, `kira/app/shared_skills_application.py` | `SharedSkillsApplicationService`: install/list/uninstall, global and per-character enablement, settings persistence, lifecycle and bounded prompt contribution | Skill domain service, settings mapping, injected persistence callback | Qt, MainWindow, direct settings mutation from UI, bundled code execution, tool permission grants |
| Character profile | `kira/services/character_service.py` | `CharacterProfileService`: create/update/delete, profile validation, per-character preferences/resources, personality traits/notes and active profile resolution | `kira.characters` data contracts, settings mapping | Qt page construction, SessionManager runtime lifecycle, UI presentation |

These services are directly injected by Bootstrap/Composition; they are not automatically registered as ModuleManager lifecycle modules. UI-owned widget, signal and worker lifecycle remains at the outer adapter boundary.

### 2.6 TASK 020 — MainWindow feature dependency boundaries

| Task | Module / canonical source | Public API / ownership | Allowed dependencies | Must not own / forbidden coupling |
|---|---|---|---|---|
| 020 | MainWindow feature dependencies — `kira/ui/main_window_*_support.py` | One scoped dependency module for each of the nine feature controllers (root, attachments/vision, character settings, chat, lifecycle, provider settings, runtime, session and voice settings) | Feature-owned application/domain modules, Qt adapters, workers and the shared support helpers | Imports from another feature controller; a global wildcard dependency barrel |

`main_window_support.py` is limited to SessionRelay, the front-only decorator, reaction loading and shared Qt signal/helper code. Feature support modules may import only this shared helper module, never another feature controller or feature support module.

## 3. Cross-module API and dependency policy

### 3.1 Allowed high-level calls

- Bootstrap constructs the graph and injects the shared services and Session/Provider/Vision/Coding Agent/Runtime Settings application services.
- MainWindow calls ChatApplicationService for Chat submission, SessionApplicationService for Session lifecycle, ProviderApplicationService for provider/route/API policy, VisionApplicationService for capture policy, CodingAgentApplicationService for Coding Agent handoff, RuntimeSettingsApplicationService for shared settings propagation, SharedSkillsApplicationService for Skill use cases, CharacterProfileService for profile mutations, WebSearchApplicationService for search planning, VoiceApplicationService for voice lifecycle and GameModeApplicationService for permission/audio policy.
- ChatApplicationService calls its injected Coordinator, ContextBuilder, ResponseHandler, AttachmentManager, command port and persistence/history contract.
- ChatSearchService (now `kira/app/chat_search_application.py`) receives a read-only Persistence reader and returns Domain request/result/page contracts.
- Transfer validates and maps the transfer format, then delegates durable import to Persistence.
- ConversationLifecycleService delegates atomic durable writes to Persistence and publishes lifecycle notifications after commit.
- ChatOrganizationService (now `kira/app/organization_application.py`) delegates metadata reads/writes through Core ports to Persistence and publishes metadata notifications after committed mutations.
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
- Organization Domain owns the `organization` metadata namespace and its pure validation rules; the Application use case coordinates updates but does not own metadata document storage.
- Organization writes use `ChatPersistence.mutate_conversations` and `mutate_all_conversations`: callbacks receive the latest row under a SQLite write transaction; bulk character-scoped updates commit or roll back as one unit.
- These transaction APIs preserve the complete metadata document and only persist the returned title/metadata fields; lifecycle status remains owned by the lifecycle transaction API.
- Search reads message pages and, when needed, conversation status through the injected Core repository ports. The DTOs live in Domain and the query/ranking/pagination use case lives in Application.
- Transfer Domain owns schema/value invariants and secret filtering; the Transfer Application use case owns parsing/export orchestration, Persistence owns durable import transactions, and Core defines `ChatTransferFilePort`. Flow 3 supplies the file adapter; a stdlib fallback remains temporarily for compatibility.
- AttachmentManager owns attachment processing/storage contracts and must not become a second Chat history store.

## 5. Application and non-Chat capability ownership

| Capability | Current source candidates / owners | Current integration boundary |
|---|---|---|
| Bootstrap & DI | `kira/ui/bootstrap.py`, `dependency_container.py`, `module_manager.py` | `bootstrap.py` registers the complete feature graph and owns construction of application-level/runtime dependencies; the Qt window composition accepts injected dependencies and creates only UI/device adapters. |
| Character profiles | `kira/services/character_service.py`, `kira/characters`, CharactersPage | CharacterProfileService owns profile create/update/delete, preference/resource normalization and personality mutation; UI owns forms and Qt page coordination. |
| Memory | `kira/services`, `persona_memory.py`, `evidence_memory.py`, `memory.py` | Memory service is registered/injected; legacy sources/adapters remain. |
| Voice | `kira/core/interfaces/voice_service.py`, `kira/app/voice_application.py`, `voice_composition.py`, `voice.py`, `listener.py`, `local_voice.py` | VoiceApplicationService implements VoiceService and owns microphone lifecycle, speech/stream/file delegation and wake/sleep/stop transcript policy; Speaker/Listener remain injected adapters. |
| Avatar/emotion | `face.py`, `vrm_avatar.py`, `companion.py`, `emotion/*`, `body.py`, `rig.py` | Capability code exists; no independent lifecycle-managed feature module confirmed. |
| Tools/coding agent | `kira/app/coding_agent_application.py`, `tools/*`, `auto_agent.py`, `code_agent.py`, `chat_code.py` | CodingAgentApplicationService owns eligible handoff, attachment bypass and stop delegation; the current execution engine and UI worker adapters remain separate. |
| Web Research | `kira/app/web_search.py`, `webintel/*`, `websearch.py`, discovery adapters | WebSearchApplicationService owns credential/query/request/evidence policy; SearchWorker and result presentation remain UI adapters. |
| Vision | `kira/app/vision_application.py`, `vision_pipeline.py`, `vision_ocr.py` | VisionApplicationService owns capture eligibility, cadence/frame gating and duplicate-result suppression; Qt capture/timers/workers remain UI adapters. |
| UI | `ui/main_window.py`, `ui/main_window_composition.py`, feature controllers/support modules, pages/components/dialogs/workers | MainWindow is a compact Qt shell with no feature-mixin inheritance. Eight window-scoped feature controllers own UI workflows; Session, Provider, Vision, Coding Agent, Runtime Settings and Character profile policies are delegated to application services. Qt widget state, worker/timer lifetime, dialog flows and result rendering remain UI adapter responsibilities. |

Implementation and reviewer checklist for the current source delta: [ARCHITECTURE_IMPLEMENTATION_HANDOFF_2026-11-18.md](ARCHITECTURE_IMPLEMENTATION_HANDOFF_2026-11-18.md).

## 6. Character scope

Character-specific identity/profile data is input to otherwise generic Chat contracts. Request/session identity must be captured at submission and preserved through provider callbacks and persistence. Durable history must be filtered by character/conversation scope. Shared capabilities must not encode a Kira-only default as business policy; legacy `DEFAULT_CHARACTER = "kira"` is a compatibility fallback, not a general capability owner.

Static code supports this design. Runtime isolation across concurrent sessions, restart, search, transfer and memory remains unverified.

## 7. Legacy and compatibility owners

- `kira.main.MainWindow` is a lazy compatibility export to `kira.ui.main_window.MainWindow`.
- `kira.ui.main_window.MainWindow` is the production Qt shell; its feature behavior is composed from window-scoped controllers in `kira/ui/main_window_*.py` and initialized by the outer UI Composition Root.
- `kira/oldmain.py` has been removed; new production code must not reintroduce imports from that path.
- `kira/services/chat_history_service.py` is an adapter over the persistence facade; it is not a second database owner.
- `kira/attachments.py` is a compatibility facade; canonical Chat attachment/content processing is under `kira/chat/`.
- `kira/memory.py` and `kira/persona_memory.py` remain legacy/compatibility memory paths while service boundaries are adopted.

The legacy imports `kira/chat/organization.py`, `kira/chat/search.py` and `kira/chat/transfer.py` are compatibility facades over the new Application/Domain modules. Remove them only after static call-site review, integration wiring and an approved migration; TASK 016 does not remove them.


## 8. Application feature lifecycle

The desktop Composition Root registers the application service/factory graph
through `kira/app/feature_modules.py` and `ServiceModule`. Managed registrations
cover Memory, Mood, Character Profile, Chat History, Conversation Organization,
Chat Search, Chat Transfer, Web Search, Shared Skills, Game Mode, Provider,
Coding Agent, Runtime Settings, Vision, and the Chat/Session/Voice composition
factories.

The graph declares the dependencies that affect startup and shutdown ordering:
Conversation Organization, Chat Search, Chat Transfer and Chat Application
depend on Chat History; Session Application depends on Chat Application; Vision
depends on Game Mode. Chat Transfer additionally accepts the optional
Core-owned `ChatTransferFilePort` supplied by the outer composition root. The manager starts dependencies first
and disposes created modules in reverse creation order. A service that is stopped
can be restarted using the same instance; disable/re-enable creates a fresh one.
Partial start failures receive stop/dispose cleanup and do not leave a DI key
registered. Disabling a dependency is rejected while a dependent remains enabled.

Chat History initializes storage at module start and flushes pending writes at
module stop. Vision and Game Mode clear transient policy state when stopped.
The concrete ChatApplicationService, SessionApplicationService and
VoiceApplicationService instances are constructed with window-scoped callback
ports implemented by UI adapters and are therefore window-scoped, not
application singletons. Organization, Search and Transfer are now application-wide, lifecycle-managed
services registered by `feature_modules.py` and resolved by Bootstrap. Each
shares the Chat History persistence adapter; Organization also receives the
shared Chat event publisher, and Search receives the explicit Conversation
status reader. Transfer receives the optional file adapter through the
`transfer_file_port` registration argument. The original Chat modules remain
compatibility facades. The concrete Chat/Session/Voice instances still use
window-scoped callback ports. Their contracts (`ProviderWorkerPort`,
`SpeakerPort`, and `VoiceListenerPort`) live in Core and contain no Qt types.
The window owns their two-phase graceful shutdown. It first rejects new Chat work
and cancels pending/running requests without closing the command registry or
AttachmentManager. It then drains provider/search/attachment/vision/game-audio
workers, stops wake/game/mood/session timers, and disposes the Voice instance
only after the listener thread exits. SessionManager next closes each Session
and runs its resource-release callback while the Chat attachment/command
adapters are still alive. Only after every Session is closed does Chat
ApplicationService dispose the command registry and AttachmentManager; the
QApplication shutdown signal then releases the global module graph.


## 9. Composition Root boundary

`kira/ui/bootstrap.py` is the desktop Composition Root and the only outer layer that binds Application to Qt. It loads settings,
creates the shared container/EventBus/ModuleManager, registers and starts the
application feature graph, constructs the SessionManager and ToolAgent, resolves
the registered services/factories, and injects them into MainWindow.

`kira/ui/main_window_composition.py` is an outer Qt adapter assembler, not a
fallback service locator. It rejects missing Bootstrap dependencies before
building the window, does not import or instantiate application/service-layer
implementations, and creates presentation/device objects plus typed, toolkit-neutral Chat/Voice callback ports. Qt signal and worker translation stays in `kira/ui/application_adapters.py`.
It invokes only the Chat/Session/Voice factories supplied by Bootstrap to create
window-scoped application services that require those live Qt callback ports;
it does not import or directly construct their implementations.

The architecture regression suite `tests/test_composition_root_contract.py`
guards the injection contract and prevents direct application-service construction
from returning to the UI composition module.


### MainWindow UI Shell delta — 2026-11-18

`MainWindow` now inherits only `QMainWindow`; it no longer inherits the
eight feature mixins or accepts application-service dependencies in its
constructor. The outer UI Composition Root creates the shell and then invokes
`initialize_main_window` to assemble widgets and injected adapters.

The former mixins are now window-scoped feature controllers. They are composed
in an explicit registry and receive the owning window as their host. The shell
forwards feature lookup through that registry and forwards Qt virtual events
(`showEvent`, `hideEvent`, `changeEvent`, `resizeEvent`, `closeEvent`,
`dragEnterEvent`, `dropEvent`) to the owning controller. Qt base-event
handling remains explicit. Compatibility aliases preserve older imports while
call sites migrate.

Static regression coverage now asserts the shell inheritance boundary, service-
free constructor, controller registry, and event forwarding. Runtime GUI
acceptance remains pending.
