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
- `kira/core/interfaces/voice_service.py` defines the consumer-facing voice contract. The legacy voice implementation is not yet wired through it.
- `kira/ui/` and `kira/services/` are destinations for staged extraction.

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
