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
- `kira/core/interfaces/` now defines Voice, Memory and Mood consumer contracts. The existing voice implementation is not yet wired through its contract.
- `kira/services/` now contains character-scoped persona-memory and shared mood adapters; their APIs are explicit about character identity and do not import UI code.

## Verified migration status (2026-11-16)

- The current migration branch is `feat/voice-performance-mcp-discovery`; work remains in PR #28 and is not merged to `main`.
- The application foundation exists in `kira/app`: bootstrap, EventBus, dependency container and a dependency-aware ModuleManager. The manager implements factory registration, dependency-first startup, failure isolation, enable/disable, unregister, reverse-order stop and dispose. It is exposed through the bootstrap runtime and shuts down on QApplication exit.
- Consumer contracts now include ApplicationModule lifecycle, Voice, Memory and Mood Protocols. MemoryDialog calls only the injected MemoryService and MoodService contracts; concrete adapters wrap the existing stores. Chat, character, avatar and provider contracts still need to be defined and wired.
- Reusable UI pieces extracted from the legacy window are now in `kira/ui/components/model_combo.py` and `kira/ui/dialogs/{memory,model_picker}.py`. `kira/main.py` imports these public UI types; the old inline definitions have been removed.
- Qt background adapters (`StreamWorker`, `AttachWorker`, `SearchWorker`, `TaskWorker`, `BenchWorker`, `ProviderTestWorker`, `VisionAnalysisWorker` and `OllamaTaskWorker`) now live in `kira/ui/workers.py`; `main.py` imports them through the UI package rather than defining them.
- After the UI and memory-service extractions, `kira/main.py` is about 5,935 lines. `MainWindow` still owns roughly 300 methods spanning Chat, Voice, Characters, Settings, Providers, Memory, Avatar, Vision, Web Research and tray/application behavior. It is **not yet a UI shell**.
- `kira/ui` contains reusable components, dialogs and background Qt workers. `kira/services` contains the first concrete Memory and Mood adapters. Normal application startup registers and resolves these through DependencyContainer and injects them into MainWindow; direct `MainWindow()` construction retains a compatibility fallback for existing callers/tests. ModuleManager is instantiated in bootstrap and exposed on the window, but no feature module is registered with it yet. Existing packages such as `characters`, `webintel`, `mcp` and `emotion` are capability code, not yet lifecycle-managed modules; no user-facing module enable/disable UI exists yet.
- The extracted widget, dialog and worker import boundaries, Memory/Mood adapter behavior, module dependency ordering, failure isolation, disable/re-enable and shutdown disposal have targeted unit coverage. Full Windows CI and a real Windows app launch are still required; this GitHub-only session cannot certify microphone, audio-device, VRM rendering or desktop behavior on the user's machine.

## Evidence-based migration map

1. **Stabilize UI boundaries:** continue extracting independent dialogs, widgets and page views from `MainWindow`; each extraction keeps a compatibility import only where existing call sites need it.
2. **Split the shell by page:** make the window responsible for navigation, shared theme and page hosting; move Chat, Settings, Voice and Characters page construction into independent view modules. Page actions must be delegated to controllers/services rather than calling other page internals.
3. **Extract application services:** Memory and Mood have the first Protocols, concrete adapters and production bootstrap injection. Continue with explicit Chat, Voice, Character, Provider, Web Research and Coding Agent contracts; wire each implementation once in bootstrap and inject it into controllers.
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
3. **Page extraction:** move Chat, Settings, Characters and Voice views/controllers independently.
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
