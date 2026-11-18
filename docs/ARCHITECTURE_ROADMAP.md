# KIRA ARCHITECTURE ROADMAP

**Snapshot:** 2026-11-18  
**Base branch:** `new-main`  
**Source baseline SHA:** `e398ed518ef446600ef758288f1dca2803845d98`  
**Input:** TASK 015 audit, merged TASK 013+014 integration PR #48, and the TASK 017–020 implementation delta on `new-main`.  
**Execution / verification:** Source implementation and focused tests were committed on `new-main`. GitHub Actions jobs completed with `runner_id=0`, empty step lists and unavailable logs (`BlobNotFound`); tests and runtime acceptance are therefore unverified.

## 1. Roadmap principles

- Stabilize what exists before adding architecture layers.
- Do not create a new module/task where an existing owner can be completed.
- Keep current implementation, confirmed debt and runtime-only uncertainty separate.
- Preserve existing persistence formats and compatibility paths until migration evidence supports removal.
- Do not treat a merged PR or static source presence as runtime acceptance.
- Keep the TASK 015 historical audit intact; record subsequent changes as deltas.

## 2. Current readiness snapshot

TASK 015 recorded **12 DONE / 2 PARTIAL / 0 NOT DONE / 0 BLOCKED / 0 UNVERIFIED** and **NOT READY FOR TESTING** against `new-main` SHA `b5d386fac1423b1b0cd07199426aef4f214e4d97`. Its two PARTIAL items were TASK 013 and TASK 014, which were not yet merged at that point.

PR #48 subsequently merged both modules into `new-main` at `b54d092a330b6383ca4244320ffaeec9267db561`. Static inspection confirms `conversation_lifecycle.py`, `organization.py`, their public exports and shared event contract are present in the current tree. Therefore, the integration blocker identified in the audit has been resolved at source-control level. This does not revise the historical audit counts and does not establish runtime correctness.

PR #55 removed the legacy `oldmain.py` runtime module and moved its 322 MainWindow methods into eight feature-oriented mixins. The subsequent implementation delta added and wired `SessionApplicationService`, `ProviderApplicationService`, `VisionApplicationService`, `CodingAgentApplicationService` and `RuntimeSettingsApplicationService`; Character Profile mutations and per-character voice overrides now pass through their service owners. Web Search, Voice and Game Mode application boundaries were retained and strengthened. ToolAgent request state, external-content taint, one-shot grants, pending confirmations, cancellation and task control are now character-session scoped; WebIntel research storage and cancellation are isolated per character. Closing a Session releases ephemeral ToolAgent/access state while retaining durable task and research files for a later reopen. Task history retention is also per character. MainWindow is now a thin Qt shell; window-scoped feature controllers own UI workflows, widgets, signal/worker adapters, dialogs and result presentation.

## 3. Technical debt register

Severity reflects architectural impact and evidence, not an assertion that a runtime failure has occurred.

| ID | Severity | Problem / evidence | Location | Owner | Impact | Dependency / proposed resolution |
|---|---|---|---|---|---|---|
| AD-01 | **Medium** | The 5,634-line `oldmain.py` and its 322 MainWindow methods were removed and split into feature-oriented UI modules. Session/conversation binding and character synchronization use `SessionApplicationService`; provider/route/API mutations and router replacement use `ProviderApplicationService`; capture eligibility and cadence use `VisionApplicationService`; Coding Agent dispatch/stop use `CodingAgentApplicationService`; shared settings propagation uses `RuntimeSettingsApplicationService`; Character profile/preferences/personality mutations use `CharacterProfileService`. Web Search, Voice and Game Mode policies also have application-service owners. Chat command dispatch uses `ChatApplicationService` + `CommandRegistry`; attachment validation, storage and preparation use its `AttachmentManager`, and the legacy payload-composition fallback is now behind the Chat service. Remaining controller work is UI sequencing, Qt worker/widget lifecycle, dialogs and rendering. | `kira/app/*_application.py`, `kira/chat/application_service.py`, `kira/chat/attachments.py`, `kira/ui/main_window_*.py` | Application/UI architecture | The main non-UI policy boundaries have explicit owners in source; runtime behavior remains unverified. Qt widget state, signals, workers and rendering intentionally remain in UI adapters. | Reviewed: keep Qt presentation and request-to-UI choreography in the UI adapter; move further logic only when a separately testable, non-Qt policy boundary is identified. |
| AD-02 | **Implemented in source — complete application feature graph** | Bootstrap registers Memory, Mood, Character Profile, Chat History, Web Search, Game Mode, Provider, Coding Agent, Runtime Settings, Vision, and the Chat/Session/Voice composition factories through ServiceModule. Explicit dependencies enforce Chat History → Chat factory → Session factory and Game Mode → Vision. Window-scoped Chat/Session/Voice instances retain graceful worker-aware teardown in MainWindow. Shutdown is two-phase: Chat first cancels work without closing session adapters; the window drains workers and closes Session resources; Chat then releases CommandRegistry/AttachmentManager. Voice exposes worker-aware idempotent dispose, Vision/Game Mode have start/stop/dispose hooks, and Chat History initializes and flushes pending writes at module boundaries. | `kira/app/feature_modules.py`, `kira/ui/bootstrap.py`, `kira/app/module_manager.py`, `kira/app/service_module.py`, `kira/ui/main_window_runtime.py` | Bootstrap / feature owners | Every extracted application service and composition factory has one managed registration; Qt workers/timers remain owned by the window and are drained before window-scoped services are released. | Keep dependency order authoritative. Do not wrap stateless domain helpers or per-session objects as application-wide singletons; they are managed by their owning service/window lifecycle. |
| AD-03 | **Addressed in source** | Organization mutations now execute against the latest conversation record inside a SQLite `BEGIN IMMEDIATE` transaction. The mutation changes only the organization namespace and preserves unrelated metadata keys. | `kira/chat/organization.py`, `kira/chat/persistence.py` | Organization + Persistence | Stale read-modify-write overwrites within Organization are prevented by the repository transaction boundary. | Runtime concurrency acceptance is still pending; tests cover two repository instances writing distinct tags concurrently. |
| AD-04 | **Addressed in source** | Tag/folder bulk cleanup selects the character-scoped rows and mutates them within one repository transaction. | `kira/chat/organization.py`, `kira/chat/persistence.py` | Persistence (transaction) + Organization (policy) | A failure in any callback rolls the complete batch back instead of partially clearing assignments. | Runtime rollback acceptance is still pending; tests cover an injected mid-batch failure. |
| AD-05 | **Implemented in source** | `VoiceApplicationService` implements the Core `VoiceService` contract, owns voice lifecycle/transcript policy, and applies allowlisted per-character voice overrides without mutating shared settings. | `kira/app/voice_application.py`, `voice_composition.py`, `core/interfaces/voice_service.py`, `ui/application_adapters.py`, `kira/ui/main_window_character_settings.py` | Voice capability owner | Device workers and UI callbacks remain injected adapters; the service itself imports no Qt. | Keep device/Qt adapters at the outer boundary; focused tests exist but execution/runtime acceptance remains pending. |
| AD-06 | **Low** | Compatibility imports/defaults remain, including the `kira.main.MainWindow` compatibility export, `kira/attachments.py`, and legacy memory entry points. | `kira/main.py`, `kira/attachments.py`, `kira/memory.py`, `kira/persona_memory.py` | Migration owners | Obsolete paths may persist and confuse future ownership if not clearly marked. | Remove only after repository-wide call-site migration and compatibility requirements are resolved. No deletion in this roadmap task. |
| AD-07 | **Addressed in source** | ToolAgent turn cache, short-term memos, last-result state, cancellation, external-content taint, one-shot grants, pending confirmations and task-control state are keyed by character Session. WebIntel has a session-scoped research store and cancellation event; Web-capable tool turns are serialized because its worker threads use a shared cancellation facade. Session close releases ephemeral ToolAgent/AccessManager/WebIntel cache state while preserving durable task/research records. TaskStore retains five completed plans plus all active plans per character. Brain reply hints, turn counters and Reflection rate limits are stored per character; the legacy Kira state file remains at its original path, and the optional Memory Writer cursor remains shared because it processes the shared history stream. | `kira/tools/agent.py`, `kira/tools/sysaccess.py`, `kira/tools/tasks.py`, `kira/webintel/session.py`, `kira/tools/webtools.py`, `kira/ui/main_window_chat.py`, `kira/ui/main_window_session.py` | Multi-character runtime state | The source has explicit per-character ownership and cleanup; concurrent runtime execution remains to be accepted. | Keep all state access inside the owning ToolAgent/AccessManager session scope. Preserve durable files on ordinary Session close; explicitly clear them only through user-visible deletion/clear actions. |
### 3.1 Runtime-only verification items (not confirmed defects)

These are not classified as implementation failures because the audit was static and tests were prohibited:
- Kira/Ren/Mika isolation across simultaneous sessions, history, search, transfer, memory and restart.
- Conversation archive/restore/trash/permanent-delete behavior, authorization and transaction guarantees.
- Export/import round trips preserving status and the complete metadata namespace.
- Typed event delivery, ordering and terminal de-duplication under concurrency; the shared EventBus now consumes a feature-neutral Core event contract, with generic-event tests added but not executed.
- Web Search automatic/forced query planning, precedence against tool plans and the UI/service dependency boundary.
- Session creation/reopen/drain/dispose behavior and application event translation.
- Provider registry/route mutation rollback, router replacement and Ollama settings-dialog client creation.
- Vision capture permission, frame cadence, busy-state suppression and duplicate-result handling.
- Coding Agent interception, attachment bypass, request completion and stop delegation.
- Runtime settings propagation, Character profile/preferences/personality mutation and per-character voice overrides.
- Provider stream handling, cancellation and partial-response persistence.
- MainWindow GUI behavior and Windows device integrations.
- Search performance for large histories; current search scans repository pages and ranks in process.

These belong in the later explicitly authorized testing phase, not in TASK 016.

## 4. Development phases

### Phase A — Architecture Stabilization

**Goal:** reduce foundational coupling without destabilizing the application.

1. Keep `kira/main.py` as the thin entry point and `kira/ui/bootstrap.py` as the single production Composition Root.
2. Keep the production Composition Root authoritative: application/runtime dependencies are constructed in Bootstrap and injected; UI composition must reject missing dependencies rather than silently constructing service-layer fallbacks.
3. Principal policy boundaries are extracted, including Chat command dispatch and attachment payload composition behind ChatApplicationService. Remaining UI code is the request-to-view sequence, Qt worker/widget lifecycle, dialogs and presentation; retain those responsibilities in window-scoped feature controllers hosted by the thin MainWindow shell.
4. The complete application service/factory graph is registered through ModuleManager; per-window Qt workers and runtime Chat/Session/Voice instances are drained by the window lifecycle before application-wide module shutdown.
5. AD-03/AD-04 source-level fixes are now present: atomic latest-row mutations and transactional character-scoped bulk metadata updates. Runtime acceptance remains pending.

**Exit condition:** ownership and composition boundaries are explicit; the UI Composition Root is the sole production composition point; `kira/app` remains toolkit-independent; UI adapters do not construct application services; no new feature module duplicates an existing service or storage owner.

### Phase B — Chat Integration

**Current source status:** TASK 001–014 are represented in current `new-main`; TASK 013+014 were integrated by merged PR #48. The historical TASK 015 audit recorded them as PARTIAL before that merge.

1. Preserve the shared event enum/public exports from the combined merge.
2. Keep Session, Conversation Lifecycle, Persistence, Search, Transfer and Organization responsibilities separate.
3. Resolve AD-03/AD-04 through one persistence-level improvement rather than parallel storage or ad hoc retries.
4. In the later authorized test phase, verify the exact cross-module scenarios listed in section 3.1.

**Exit condition:** static contracts remain coherent and subsequent runtime acceptance passes when explicitly authorized. No claim of test completion is made here.

### Phase C — Shared Capabilities

**Goal:** make reusable capabilities independent of the active character.

1. Keep generic Chat, command, tool and capability contracts character-neutral.
2. Store character identity, persona, voice preferences and enablement policy in character/profile/session data, not in generic command handlers.
3. Verify whether a shared installable Skills implementation exists on the target branch before planning further work. TASK 015's audited Chat scope and the inspected `kira/` tree did not establish one; do not mark it delivered based on a separate branch or PR.
4. If shared Skills are brought into this architecture, one library/runtime should support global and per-character enablement without duplicating skill code per character.
5. Verify isolation for Kira, Ren and Mika before treating cross-character reuse as accepted.

**Exit condition:** adding a character does not require rewriting Chat, persistence, command dispatch or generic capability modules.

### Phase D — Platform Expansion

**Goal:** extend Voice, Memory, Avatar/Emotion, Vision, Web Research and Coding Agent behind explicit application contracts.

1. Voice contract wiring and per-character voice settings are present; retain the `VoiceService`/`VoiceApplicationPorts` boundary.
2. Session, Provider, Vision, Coding Agent and Runtime Settings have injected application-service owners; keep Qt/device adapters outside those services.
3. Keep Memory and Character services injected through bootstrap; retire legacy adapters only after call-site migration.
4. Avatar/Emotion remains a separate capability area; introduce an application contract only when a concrete consumer and lifecycle need are established.
5. ModuleManager owns application service/factory registration and dependency order; window-scoped Chat, Session and Voice instances retain explicit graceful teardown because they require live Qt callback/worker ownership.

**Exit condition:** each expanded capability has one owner, injected dependencies, explicit lifecycle where required, and no reverse dependency on MainWindow.

## 5. Recommended execution order

1. **Runtime acceptance** of the newly extracted Session, Provider, Vision, Coding Agent, Runtime Settings and Character Profile services, plus Chat persistence/event flows.
2. **Residual UI boundary review** for command/attachment orchestration, Qt worker lifetime, dialogs and response presentation.
3. **Lifecycle acceptance** for the complete application feature graph, window-owned workers/timers, and Chat History pending-write flush.
4. **Shared capability/Skills integration** only after confirming the actual implementation and target branch.

This is a prioritized sequence, not a mandate to create six separate tasks. Related changes should be grouped into a small number of coherent implementation units.

## 6. Legacy migration strategy

- Keep `kira/ui/main_window.py` as the Qt shell only; `kira/ui/main_window_composition.py` and the window-scoped feature controllers own UI composition and presentation, not domain policy.
- Move one coherent controller/service boundary at a time.
- Bootstrap creates concrete services and injects them; page widgets emit intents and render results.
- Preserve public imports until callers have moved.
- Preserve existing Chat history, metadata and settings formats; migrations must be additive/backward-compatible.
- Do not delete old files solely because a new module exists. Confirm all production and compatibility call sites before removal.
- Update this roadmap when a migration is merged; record the new base SHA and evidence.

## 7. Testing boundary and acceptance handoff

TASK 016 itself was documentation/static inspection only. The subsequent implementation delta added focused Qt-free tests for architecture boundaries, Session orchestration, Provider/Vision/Coding Agent/Runtime Settings policies, Character Profile mutations and Voice overrides, in addition to existing Chat and Organization concurrency/rollback suites. GitHub Actions jobs were triggered, but inspected jobs completed with `runner_id=0`, empty step lists and unavailable logs; no test or compile pass is claimed.

When testing is explicitly authorized after TASK 016:
- Test Chat contracts and production DI wiring.
- Test lifecycle and organization with persistence/event integration.
- Execute the added metadata concurrency/rollback tests and the architecture-boundary suite; source-level fixes exist, but acceptance requires an actual test run.
- Test character isolation across Kira/Ren/Mika, including restart and transfer.
- Test event delivery and provider terminal/cancellation behavior.
- Run the approved full regression and Windows/offscreen GUI checks.

A successful static review is not a substitute for these runtime checks.

## 8. Decision log

| Date | Decision | Evidence |
|---|---|---|
| 2026-11-17 | TASK 015 audit is retained as 12 DONE / 2 PARTIAL and NOT READY FOR TESTING at its audited base. | Draft PR #47: https://github.com/alizesta/Kira/pull/47. |
| 2026-11-17 | TASK 013 and TASK 014 subsequently integrated into `new-main`. | Merged PR #48; merge commit `b54d092a330b6383ca4244320ffaeec9267db561`. |
| 2026-11-17 | No runtime/test status is changed by TASK 016. | TASK 016 policy: static documentation only. |
| 2026-11-18 | TASK 017–020 application-policy boundaries were implemented on `new-main`; Task 017 is integrated as a Session service, and Provider/Vision/Coding Agent/Runtime Settings/Character profile boundaries were moved behind services. | Source baseline `e398ed518ef446600ef758288f1dca2803845d98`; see implementation handoff. |
| 2026-11-18 | Runtime acceptance remains open because Actions jobs did not obtain a runner. | Latest inspected job reported `runner_id=0`, `steps=[]`; log endpoint returned `BlobNotFound`. |


### Decision log — application lifecycle completion

| Date | Decision | Evidence |
|---|---|---|
| 2026-11-18 | Registered the application-wide service/factory graph in ModuleManager with explicit dependency ordering. | `kira/app/feature_modules.py`; 13 managed modules. |
| 2026-11-18 | Kept concrete Chat/Session/Voice instances window-scoped because they retain Qt worker and callback ports; added graceful idempotent teardown instead of global singleton disposal. | `kira/ui/main_window_runtime.py`, `kira/app/voice_application.py`. |
| 2026-11-18 | Added Chat History startup initialization and pending-write flush at stop. | `kira/services/chat_history_service.py`, `kira/chat/persistence.py`. |


### Composition Root completion delta — 2026-11-18

The remaining MainWindow composition fallback paths have been removed. The UI
composition now validates its complete dependency set up front and rejects
partial construction, rather than silently creating Memory, Mood, Character,
Chat History, Web Search, Game Mode, Provider, Coding Agent, Runtime Settings,
Vision, Chat, Session or Voice services. Bootstrap now also constructs and
injects the runtime ToolAgent and owns SessionManager creation. UI composition
retains only Qt/presentation/device adapters and builds typed callback ports for
the window-scoped Chat and Voice factories.

Added `tests/test_composition_root_contract.py` and included it in the
chat/session lifecycle CI workflow. Source-level verification is covered by the
new regression test; runtime execution remains dependent on the CI runner.


### Application / Qt separation delta — 2026-11-18

The desktop Composition Root now lives in `kira/ui/bootstrap.py`; the thin
entry point delegates to it. Qt startup, MainWindow construction and desktop
styling are therefore outside `kira/app`. Chat provider execution now consumes
the toolkit-neutral `ProviderWorkerPort`, with Qt signal translation isolated
in `kira/ui/application_adapters.py`. Voice orchestration now consumes
`SpeakerPort` and `VoiceListenerPort`; QThread lifecycle, Qt signal mapping
and Speaker implementation details are wrapped by UI-side adapters.

The application services no longer call Qt signal `.connect()`, QThread
`.isRunning()`, or Qt-specific listener methods directly. Regression tests
guard these boundaries. Runtime test execution is still required before
claiming runtime acceptance.


### MainWindow UI Shell completion delta — 2026-11-18

`MainWindow` now derives only from `QMainWindow`. The eight former mixins are
window-scoped controllers composed in an explicit registry; feature methods
are no longer part of the MainWindow inheritance surface. The shell exposes
only session/front-window descriptors, controller lookup, and Qt virtual-event
forwarding. The constructor accepts only the optional Qt parent and no longer
constructs application services or widgets.

The UI Composition Root now creates the shell first and performs the
service/widget assembly separately. Qt event overrides are explicitly routed
to lifecycle, session, runtime, and attachment controllers, which call the
appropriate QMainWindow base event implementation where required. Compatibility
aliases remain for existing imports.

Regression tests cover the shell's base class, controller registration,
constructor boundary, composition-root wiring and event-forwarding contract.
Static source validation is in place; runtime GUI behavior and full application
tests still require a functioning CI runner.
