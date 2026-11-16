# Kira modular architecture

## Goal
Kira is migrating incrementally toward independent UI, application logic, services and infrastructure. A module should be replaceable or optional without forcing unrelated modules to import its implementation details.

## Target boundaries
- **Application Core:** startup composition, lifecycle, dependency registration and event dispatch.
- **Chat:** message UI/controller and chat orchestration.
- **Voice:** local STT/TTS behind a stable service contract; no chat UI imports inside the engine.
- **Memory:** persistence and retrieval behind service interfaces.
- **Characters:** Kira, Mika and Ren profiles and character-specific state.
- **Avatar:** rendering, emotion and animation, independent from chat generation.
- **Settings:** settings pages/controllers and migration.
- **Shared Infrastructure:** storage, providers, tools, logging and device adapters.

## Current migration foundation
- `kira/main.py` remains the compatibility module for existing callers and currently contains the legacy MainWindow implementation.
- `kira/app/bootstrap.py` is the composition root. It creates QApplication, applies application style and constructs MainWindow.
- `kira/app/event_bus.py` provides named in-process notifications. Subscribers can unsubscribe; publishing uses a snapshot so callbacks can safely change subscriptions.
- `kira/app/dependency_container.py` provides explicit instance/factory registration and lazy singleton resolution.
- `kira/core/interfaces/` now defines ApplicationModule lifecycle, Character, ChatHistory, Voice, Memory and Mood consumer contracts; `core.exceptions.ChatHistoryError` keeps SQLite-specific failures out of UI code. The existing voice implementation is not yet wired through its contract.
- `kira/services/` now contains character profile, character-scoped persona-memory, shared mood and SQLite chat-history adapters; these adapters do not import UI code.

## Verified migration status (2026-11-16)

- The current migration branch is `feat/voice-performance-mcp-discovery`; work remains in PR #28 and is not merged to `main`.
- The application foundation exists in `kira/app`: bootstrap, EventBus, dependency container and a dependency-aware ModuleManager.
- `kira/modules/ServiceModule` now adapts service factories to the ModuleManager lifecycle: it creates services on start, publishes instances through DI, invokes optional `start`/`stop`/`dispose` (or `close`) hooks, and unregisters services on disposal. Bootstrap registers Memory, Mood, Characters and Chat History as required managed modules and refuses startup if any required module fails. This is the first live use of ModuleManager; feature-level Chat, Voice, Avatar, Web Research, Coding Agent and Provider modules are not yet independently registered. The manager implements factory registration, dependency-first startup, failure isolation, enable/disable, unregister, reverse-order stop and dispose. It is exposed through the bootstrap runtime and shuts down on QApplication exit.
- Consumer contracts now include ApplicationModule lifecycle, Character, ChatHistory, Voice, Memory and Mood Protocols.
- Provider transport is now formalized by `core.interfaces.ChatProvider`; built-in adapters implement the same structural contract. `infrastructure.providers.ProviderRegistry` provides thread-safe register/replace/resolve/unregister operations, and `HybridRouter.provider_class()` resolves built-in adapters through it before its configured OpenAI-compatible fallback. Provider consumers can keep using the router while adapters are replaced through the registry. MemoryDialog calls injected MemoryService and MoodService; MainWindow uses CharacterService for active profile, prompt, display-name and avatar-file operations and ChatHistoryService for SQLite reads/writes, restore and import. Chat orchestration, avatar and provider contracts still need to be defined and wired.
- Reusable UI pieces extracted from the legacy window are now in `kira/ui/components/{model_combo,route_editor,mcp_registry_panel,ollama_provider_panel,api_add_panel}.py`, `kira/ui/dialogs/{memory,model_picker}.py` and `kira/ui/pages/{help_page,voice_page,appearance_page,characters_page,assistant_page,preferences_page}.py`. `kira/main.py` imports these public UI types; inline definitions for the extracted components and page layouts have been removed. HelpPage owns its content, links and translation refresh. VoicePage owns microphone, local STT and TTS controls, debounce timer and translation refresh; MainWindow connects intent signals to existing device/model/persistence handlers. AppearancePage owns the Acrylic/Mica selector, background color preview and visual sliders; the app controller alone applies the global stylesheet and persists theme changes. CharactersPage owns profile selection, character-specific voice/resources, behavior controls and personality sliders; the host supplies profile data and handles session switching, storage and avatar operations through application methods. AssistantPage now owns assistant/persona and Ollama model controls and emits connection/load/unload/benchmark intents. PreferencesPage owns language, Web Research preferences, history/memory actions and About metadata. RouteEditor owns route ordering, failover and selected-route controls and emits selection/edit/benchmark intents. McpRegistryPanel owns MCP Registry search, result selection, status and refresh controls; registry discovery and server installation remain in the application controller. OllamaProviderPanel owns the local-provider enable and URL-edit controls; URL validation and persistence remain in the controller. ApiAddPanel owns API-key entry, account ID and model-filter controls; API discovery, validation and registration remain in the controller. These widgets expose intent signals while MainWindow temporarily retains compatibility aliases for existing settings persistence and controllers.
- Qt background adapters (`StreamWorker`, `AttachWorker`, `SearchWorker`, `TaskWorker`, `BenchWorker`, `ProviderTestWorker`, `VisionAnalysisWorker` and `OllamaTaskWorker`) now live in `kira/ui/workers.py`; `main.py` imports them through the UI package rather than defining them.
- After extracting Help, Voice, Appearance, Characters, Assistant and Preferences page layouts plus the RouteEditor and McpRegistryPanel components, `kira/main.py` is 5,444 lines. `MainWindow` still owns roughly 319 methods spanning Chat orchestration, Voice controllers, Settings, Providers, Memory, Avatar, Vision, Web Research and tray/application behavior; it is **not yet a UI shell**. Assistant and Preferences controls are physically owned by their page widgets, but compatibility aliases and application actions remain in MainWindow. It is **not yet a UI shell**.
- `kira/ui` contains reusable components, dialogs, background Qt workers and independent Help/About, Voice, Appearance, Characters, Assistant and Preferences pages plus reusable RouteEditor, McpRegistryPanel, OllamaProviderPanel and ApiAddPanel components. `kira/services` contains concrete Character, Memory, Mood and SQLite chat-history adapters; all MainWindow persona-memory operations now pass through MemoryService, so it no longer imports `persona_memory` directly. Normal application startup registers and resolves these through DependencyContainer and injects them into MainWindow; direct `MainWindow()` construction retains a compatibility fallback for existing callers/tests. ModuleManager is instantiated in bootstrap and exposed on the window, but no feature module is registered with it yet. Existing packages such as `characters`, `webintel`, `mcp` and `emotion` are capability code, not yet lifecycle-managed modules; no user-facing module enable/disable UI exists yet.
- The extracted widget, dialog, HelpPage, VoicePage, AppearancePage, CharactersPage and worker import boundaries, Character/Memory/Mood/ChatHistory adapter behavior, character-isolated memory prompt assembly and observation routing, module dependency ordering, failure isolation, disable/re-enable and shutdown disposal have targeted unit coverage. Windows offscreen GUI tests now check that extracted page widgets are owned by their page objects and Kira/Ren/Mika profiles load into CharactersPage. Full Windows CI and a real Windows app launch are still required; this GitHub-only session cannot certify microphone, audio-device, VRM rendering or desktop behavior on the user's machine.

## Chat context and prompt ownership (TASK 003)

- `kira/chat/context_builder.py` owns final per-turn prompt composition and provider-neutral message-context assembly. Its public boundary is `ContextBuilder.build(ContextRequest) -> ContextResult`.
- The builder imports only the Python standard library. It has no dependency on PySide6, MainWindow, ChatSession, storage, a database, provider routing, or a named character. Character identity/profile data, memory text, mood text, tool/capability context, attachment payloads and history snapshots are supplied by the caller.
- `ContextBuilder` receives the existing character-aware system-prompt composer and optional prompt enrichers through dependency injection. The production composition injects `kira.personality.build_system_prompt` and the existing deterministic brain prompt extension; neither implementation is duplicated in the builder.
- The builder snapshots messages, applies the current-turn attachment payload, preserves message order, and can drop the oldest complete non-system conversational turns to meet an optional character-count budget. A zero budget preserves the previous unbounded behavior. The current user message is never dropped or truncated.
- The Chat application layer remains responsible for obtaining history and calling Memory, Mood, Character, Brain and Tool services. The builder does not read or write history, manage memory, choose a provider/model, execute workers, stream responses, or retain session state.
- TASK 003 changes only the legacy chat request-preparation call site in `kira/oldmain.py`; it does not alter `ChatCoordinator` or its queue/worker callback contracts from TASK 002. The coordinator remains the owner of request admission, pending FIFO work and provider-worker dispatch.
- Ownership: `kira/chat/context_builder.py` and `tests/test_chat_context_builder.py` belong to TASK 003. `kira/chat/coordinator.py` and its TASK 002 tests remain owned by TASK 002. The integration call site in `kira/oldmain.py` is shared migration infrastructure and must not absorb new coordinator responsibilities.

## Chat response lifecycle (TASK 004)

- `kira/chat/response_handler.py` owns per-request provider-event processing, ordered stream aggregation, terminal-state classification and bounded cleanup. Its public boundary is `ResponseHandler.begin_request(request_id, session_id)` followed by `ResponseHandler.handle(ProviderEvent) -> ResponseStreamEvent | None`.
- Provider events are request- and session-scoped. Chunk events carry the original chunk and the accumulated content snapshot; final events carry a `ChatResponseResult` with `request_id`, `session_id`, one of `completed` / `failed` / `cancelled`, content, optional normalized error and provider metadata.
- The handler uses a lock to serialize concurrent callbacks, rejects session-mismatched and late events, ignores duplicate terminal callbacks, removes active request state atomically, and retains only a bounded set of terminal IDs to reject duplicates.
- Empty successful responses remain explicitly marked as empty so the Chat application layer can preserve its existing plain-prompt retry policy. Failed/interrupted streams retain partial content and are marked incomplete; explicit or provider-reported cancellation has the `cancelled` status.
- The handler imports only the Python standard library. It does not access UI, Qt, MainWindow, ChatSession, storage, provider clients, queues, Memory, tools or ContextBuilder.
- `ProviderResponseRelay` in the legacy composition layer captures the immutable request/session IDs for each worker. It translates the normalized result into existing application callbacks; display, partial-response policy, persistence, speech, avatar reactions and queue draining remain outside the handler.
- TASK 004 owns `kira/chat/response_handler.py` and `tests/test_chat_response_handler.py`. The request-specific relay and wiring in `kira/oldmain.py` are shared migration integration. TASK 002 coordinator files and TASK 003 context-builder files are not modified.

## Evidence-based migration map

1. **Stabilize UI boundaries:** Help, Voice, Appearance, Characters, Assistant and Preferences page layouts are extracted. Continue with the Chat page and remaining registered-API/detail tables and model catalog settings subpages; each extraction keeps a compatibility import only where existing call sites need it.
2. **Split the shell by page:** make the window responsible for navigation, shared theme and page hosting; the Voice and Characters page widgets are now independent, but their controllers still partly live in MainWindow. Continue extracting Chat and Settings controllers and remove the remaining feature orchestration from the shell. Page actions must be delegated to controllers/services rather than calling other page internals.
3. **Extract application services:** Character, Memory, Mood and SQLite chat history have Protocols, concrete adapters and production bootstrap injection. Continue with chat orchestration, Voice, Provider, Web Research and Coding Agent contracts; wire each implementation once in bootstrap and inject it into controllers.
4. **Move persistence and adapters:** centralize database, settings storage, provider clients, model discovery, audio devices and logging behind infrastructure adapters. Preserve existing user-data formats and migration behavior.
5. **Adopt the lifecycle manager:** the generic register/start/stop/dispose engine and dependency validation are implemented and unit-tested. Next, define manifests for actual feature modules, register them from bootstrap, persist enabled state and add user-facing enable/disable controls. Optional module failure must not prevent core chat from starting.
6. **Enforce boundaries:** add import-boundary and lifecycle tests to prevent UI imports from services, direct cross-module implementation imports, circular dependencies and unload leaks.
7. **Validate behavior:** run the full CI suite and targeted GUI/offscreen tests at each stage; do not mark a subsystem independent until its behavior is tested through its contract. Hardware-specific audio, avatar and desktop checks remain explicit manual acceptance items.

## Dependency rules
1. UI may call application services through interfaces; services must not import UI widgets.
2. Chat must not reach into Voice implementation objects or MainWindow fields. Use a service contract for direct commands and EventBus for notifications.
3. EventBus is for broadcast facts such as transcript received, reply completed or speech started/stopped. Request/response operations use explicit interfaces.
4. Dependencies are composed at startup and passed to consumers; modules should not construct unrelated services internally.
5. Each module owns its settings and persistence schema. Cross-module access goes through a service contract or published event.
6. Optional modules must fail closed and leave unrelated capabilities usable.
7. Keep compatibility imports until callers and tests have migrated; do not delete old entry points during extraction.

## Migration sequence
1. **Foundation:** application package, bootstrap, EventBus, dependency container and stable service contracts.
2. **UI shell:** extract MainWindow shell/navigation and page registration while retaining compatibility imports.
3. **Page extraction:** Help, Appearance, Voice, Characters, Assistant and Preferences views and the RouteEditor/McpRegistryPanel components are extracted; next move Chat and remaining registered-API/detail tables and model catalog settings views and move all page controllers out of MainWindow.
4. **Service extraction:** move chat, memory and local voice orchestration behind contracts; inject implementations from bootstrap.
5. **Module lifecycle:** add manifest-based registration, dependency checks, enable/disable and safe unload only after service boundaries are stable.
6. **Independent modules:** extract Avatar, Web Research/Agent Reach and Coding Agent without coupling them to MainWindow internals.

## Non-goals for the first migration
- Do not rewrite all of MainWindow in one change.
- Do not introduce a plugin/module loader before interfaces and lifecycle behavior are tested.
- Do not route every method call through EventBus.
- Do not change user data formats or existing behavior as part of structural extraction.

## Acceptance criteria
- Existing launch command and imports continue to work.
- EventBus subscription/unsubscription and dependency resolution have isolated tests.
- Extracted services can be tested without constructing MainWindow or QApplication.
- Disabling an optional module does not prevent the application shell or text chat from starting.


## Chat attachment controller extraction

- `kira.ui.controllers.ChatAttachmentController` owns pre-send attachment selection, asynchronous file loading, cancellation, pasted-image encoding, tile lifecycle and the attachment-count limit.
- Its UI controls, worker/tile factories, attachment API and busy-state callback are injected. It does not import or reference `MainWindow`.
- `MainWindow` currently provides thin compatibility delegates while send/upload orchestration is migrated in later steps. The controller is composed after the chat composer is created.
- The upload-progress presentation remains in the chat coordinator for now; it is a separate responsibility and should be extracted behind its own contract rather than coupled into the file-reading controller.


## Chat request coordinator extraction (TASK 002)

- `kira.chat.ChatCoordinator` is a Qt-free, per-chat request boundary. It owns the bounded FIFO queue (three pending requests), preserves attachment and voice metadata, dispatches idle requests through an injected callback, and delegates provider-worker construction/stream-signal wiring through `ChatProviderDispatcher`.
- Each `ChatSession` owns an optional coordinator slot; `MainWindow` composes one coordinator per session and adapts queued requests to the existing chat request pipeline. Vision cancellation, coding-agent interception, message preparation, persistence, web/image search and response presentation remain in the application adapter. Worker creation and provider signal dispatch are routed through `ChatProviderDispatcher`; TASK 004 owns provider-event processing and normalized response lifecycle.
- The application adapter pins each drain operation to its originating `ChatSession`. A `dispatch_scheduled` reservation remains part of FIFO ordering: new submissions must queue behind it, and a dequeued request is dispatched directly rather than re-entering admission. Removed sessions remain alive while a worker, search, Vision operation, queued item or scheduled dispatch is pending; disposal clears the queue and releases the session's coordinator/adapter closure, worker references, router, timer, relay and view. Shutdown clears all pending queues and reservations. The per-request `ProviderResponseRelay` releases itself and its Session reference after a terminal event; completed Vision workers are also deleted when their owning session drains.
- The coordinator imports no MainWindow, Qt, storage, Session Manager, Memory, Voice, Tools, Web Research or provider implementation. Those capabilities are not reimplemented or duplicated inside it.
- Unit tests cover immediate dispatch, FIFO ordering, queue bounds, forced deferral, callback failure isolation, per-coordinator queue isolation and the legacy-window delegation boundary. Offscreen GUI regression tests cover two background sessions completing across tab switches, FIFO dispatch after completion, deferred disposal while a worker/request remains active, coordinator/worker/resource release after session removal, and queue clearing on application shutdown.
- This is an incremental extraction, not completion of the full Chat feature migration: request preparation, search/tool policy, persistence and presentation still remain in the application adapter. Do not describe Chat as fully independent yet.
## Independent model-delegation contract

A feature is ready to be assigned to a separate implementation model only when its boundary is explicit:

1. **Single ownership:** one package owns the feature's state, behavior and tests. Other modules do not reach into its private fields.
2. **Public surface:** expose a small API from the package `__init__.py`; keep implementation details private to the feature package.
3. **Explicit dependencies:** constructor/function inputs or Protocol interfaces define every external dependency. Feature code must not import `MainWindow`, read its attributes, or create unrelated services globally.
4. **Direction of control:** the application shell/bootstrap wires modules together. Feature modules communicate through their public contracts; use EventBus for notifications, not as a universal method-call router.
5. **Replaceability:** tests can exercise the feature with fakes or adapters without constructing the whole application. Optional features have defined startup/shutdown behavior and fail without taking down unrelated features.
6. **Change isolation:** a delegated task names the owned package, public contract, permitted dependencies and test target. A model must not modify neighboring feature packages unless the task explicitly requires a contract change.

The long-term shell is intentionally boring: bootstrap creates and wires feature modules; `MainWindow` hosts the UI and forwards user intent. Neither should own feature algorithms or persistence rules.


## Legacy entry-point migration

The monolithic application window is being retired through a controlled, reversible migration:

1. `kira/main.py` is the stable executable entry point. `python -m kira.main` remains the supported launch command.
2. `kira/app/bootstrap.py` is the single composition root: it creates shared infrastructure and wires application modules. Startup wiring must not be duplicated in the entry-point file.
3. The former monolith is temporarily preserved as `kira/oldmain.py`. During this transition, bootstrap may construct its legacy `MainWindow`; this is an explicit migration dependency, not a target architecture.
4. `kira.main.MainWindow` is only a lazy compatibility export for existing imports. New production code must not import it. New feature code must not import `kira.oldmain` or depend on legacy window state.
5. Migrate one feature boundary at a time: move its state and behavior into an owned package, define its public contract and injected dependencies, then adapt the legacy window to call that contract. Add isolated tests before removing the corresponding legacy implementation.
6. Keep the launch command, settings, user data, and user-visible behavior stable throughout the migration. Do not delete `oldmain.py` until all required features have moved and the full regression suite plus Windows launch acceptance have passed.

The migration reference is temporary. Its purpose is to preserve working behavior while the new application structure takes ownership; it must not become a permanent service layer or an import target for new modules.
