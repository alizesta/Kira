# KIRA ARCHITECTURE ROADMAP

**Snapshot:** 2026-11-19  
**Base branch:** `new-main`  
**Source baseline SHA:** `0a84bbdc3d47afb1728ff314a056b49e6e56848b`  
**Input:** TASK 015 historical audit, merged TASK 013+014 integration PR #48, TASK 017–020 implementation delta, and merged Chat event test/CI correction PR #98.  
**Execution / verification:** Source and static contracts are recorded at the baseline SHA. PR #98 merged corrections to the Chat event test contract and its workflow path filter. The corresponding GitHub Actions jobs still completed without a runner (`runner_id=0`, `steps=[]`) and logs were unavailable (`BlobNotFound`). No Python test or Windows runtime acceptance is claimed.

## 1. Roadmap principles

- Stabilize what exists before adding architecture layers.
- Do not create a new module/task where an existing owner can be completed.
- Keep current implementation, confirmed debt and runtime-only uncertainty separate.
- Preserve existing persistence formats and compatibility paths until migration evidence supports removal.
- Do not treat a merged PR or static source presence as runtime acceptance.
- Keep the TASK 015 historical audit intact; record subsequent changes as deltas.
- Size modules by cohesive responsibility and ownership, not by an arbitrary line-count ceiling; lines of code are an inspection signal, not a success metric.
- Do not split a coherent workflow into tiny files solely to make the tree look modular; extract only when ownership, lifecycle, dependency direction, or a meaningful test seam becomes clearer.

## 2. Current readiness snapshot

TASK 015 recorded **12 DONE / 2 PARTIAL / 0 NOT DONE / 0 BLOCKED / 0 UNVERIFIED** and **NOT READY FOR TESTING** against `new-main` SHA `b5d386fac1423b1b0cd07199426aef4f214e4d97`. Its two PARTIAL items were TASK 013 and TASK 014, which were not yet merged at that point.

PR #48 subsequently merged both modules into `new-main` at `b54d092a330b6383ca4244320ffaeec9267db561`. Static inspection confirms `conversation_lifecycle.py`, `organization.py`, their public exports and shared event contract are present in the current tree. Therefore, the integration blocker identified in the audit has been resolved at source-control level. This does not revise the historical audit counts and does not establish runtime correctness.

PR #55 removed the legacy `oldmain.py` runtime module and moved its 322 MainWindow methods into eight feature-oriented mixins. The subsequent implementation delta added and wired `SessionApplicationService`, `ProviderApplicationService`, `VisionApplicationService`, `CodingAgentApplicationService` and `RuntimeSettingsApplicationService`; Character Profile mutations and per-character voice overrides now pass through their service owners. Web Search, Voice and Game Mode application boundaries were retained and strengthened. ToolAgent request state, external-content taint, one-shot grants, pending confirmations, cancellation and task control are now character-session scoped; WebIntel research storage and cancellation are isolated per character. Closing a Session releases ephemeral ToolAgent/access state while retaining durable task and research files for a later reopen. Task history retention is also per character. MainWindow is now a thin Qt shell; window-scoped feature controllers own UI workflows, widgets, signal/worker adapters, dialogs and result presentation.

## 2.1 Synchronization update — 2026-11-19

- Root `ARCHITECTURE.md` is now a short index; `docs/ARCHITECTURE_MASTER.md`, this roadmap and `docs/MODULE_OWNERSHIP.md` are the canonical architecture records.
- PR #98 is merged to `new-main` (merge commit `0a84bbdc3d47afb1728ff314a056b49e6e56848b`). It corrects stale path/event assertions in `tests/test_chat_events.py` and adds that test file to the Chat Session Lifecycle workflow path filter.
- The PR workflows still produced failed jobs with `steps=[]`; logs could not be retrieved. This is not a test pass and does not establish a source regression. Runner/CI execution remains an open infrastructure blocker.
- The production Qt Composition Root is `kira/ui/bootstrap.py`. Any older snapshot or handoff text that calls `kira/app/bootstrap.py` the production root is historical and superseded.

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
| AD-08 | **Addressed in source — runtime acceptance pending** | The five identified robustness gaps now have source-level protections: the Chat write backlog rejects new messages explicitly when full and preserves accepted pending messages; Ai1 Code enforces the 400 MiB project-copy budget, reports copy/stat failures with the affected path, removes partial files/workspaces after failed copies, drains subprocess output into a bounded tail, bounds project-file reads, rejects replacements above the 512 KiB readable-file limit, and atomically replaces files so failed writes preserve previous content; Evidence Memory serializes first-use schema setup; native Function Calling records usage/telemetry on both success and terminal failure; Desktop clipboard/window/UIA results are marked external and taint the active turn before subsequent state-changing actions. Focused regression tests cover queue overflow, bounded process output, oversized reads/replacements, project-copy limits/failures, atomic-write failure and native-call failure accounting. | `kira/chat/persistence.py`, `kira/auto_agent.py`, `kira/evidence_memory.py`, `kira/hybrid_ai.py`, `kira/tools/desktop.py`, `kira/tools/sysaccess.py` | Persistence / Coding Agent / Evidence Memory / Provider / Desktop owners | The previously identified silent message loss, unbounded process capture, oversized replacement, incomplete project-copy and failed-native-request accounting gaps are addressed in source. | Run focused Python tests and Windows runtime checks when an executable runner is available; preserve bounded queues/capture and fail-safe behavior. |
| AD-09 | **Implemented in source — runtime acceptance pending** | Proactive Initiative orchestration has been extracted from `SessionController` into a Qt-free `InitiativeApplicationService`. The service owns cross-character inactivity evaluation, memory candidate selection, duplicate/rate-limit history recovery, durable assistant-message persistence and the post-persistence mood marker. The controller retains only desktop-specific safety gates, settings persistence and rendering. The service is composed from the existing Memory/Mood owners and the window-scoped Chat application service. | `kira/app/initiative_application.py`, `kira/app/initiative_composition.py`, `kira/character/initiative.py`, `kira/ui/main_window_session.py` | Initiative / Session presentation | Initiative policy is independently callable and testable without Qt; the Session controller no longer imports the legacy Mood or persona-memory modules, or the Initiative policy engine. | Execute `tests/test_initiative_application.py`, `tests/test_initiative_quality.py`, composition/module registration tests and Windows GUI acceptance when an executable runner is available. |

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
3. The shared installable Skills registry/service is present in the current source tree (`kira/skills/*`, `kira/app/shared_skills_application.py`) and is integrated with its UI page; maintain one shared library/runtime rather than per-character code copies.
4. Verify ZIP/folder installation, traversal/symlink/resource limits, global and per-character enablement, prompt-injection boundaries, and no automatic code execution or tool-grant escalation.
5. Verify isolation for Kira, Ren and Mika before treating cross-character reuse as runtime-accepted.

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


### Feature Controller boundary delta — 2026-11-18

The controller compatibility lookup and Qt event dispatch now pass through
`FeatureControllerRegistry`, which centralizes feature ownership and reports
legacy method collisions. Chat's attachment workflow is injected explicitly
from UI composition through the independent `ChatAttachmentController`; Chat
no longer reaches the attachment feature through legacy forwarding methods or
the shared `_tiles` collection.

This advances the residual UI boundary work but does not close it. The
window-backed `WindowFeatureController` proxy and remaining cross-feature
method calls are still migration targets. Focused registry and dependency
contract tests have been added; they are not yet executed. Windows/GUI and
GitHub Actions validation are intentionally outside this workstream.


### Controller registry hardening delta — 2026-11-18

`FeatureControllerRegistry` now owns an immutable snapshot of controller membership. Peer-controller dependencies use the registry's required lookup contract, which raises immediately when a declared feature is absent instead of returning an optional value. Regression tests cover defensive copying of registry membership and missing-peer failure. This is a narrow boundary-hardening step; it does not remove the broad `WindowFeatureController` window-backed attribute proxy or migrate residual shared UI state. Those remain open Flow 1 exit criteria.


### Flow 1 closure delta — explicit presentation context — 2026-11-18

This section supersedes the earlier residual-UI notes above for the current refactor/ui-controller-boundaries branch.

- Added WindowPresentationContext as the sole controller-to-host boundary. Its state, services, adapters, and views buckets enforce explicit allowlists; reads or writes outside those contracts raise AttributeError.
- Per-conversation request/stream state is read and written through the active ChatSession. Vision worker/session state and the pending voice-input flag are now session-scoped instead of window-global.
- All eight feature controllers have migrated their shared reads/writes to the named context buckets. Controller-local transient state remains on its owning controller; cross-controller workflow calls resolve a required peer by feature name through FeatureControllerRegistry.require().
- Chat and Voice Qt callback ports now receive the presentation context and obtain callbacks from their owning feature controllers. Shared Skills prompt enrichment reads the active ChatSession and injected application service.
- Removed WindowFeatureController generic __getattr__/__setattr__ forwarding, removed MainWindow.__getattr__ feature-method lookup and the shell's session/front-only compatibility descriptors, and removed the registry's legacy method-resolution operation. MainWindow now owns the Qt host, controller registry, presentation context, and explicit Qt virtual-event forwarding only.
- Kept the Qt host reference explicit as controller.window for QObject parenting and native window APIs; this is a host port, not a general attribute proxy.
- Added static contract checks that compare every direct context-bucket reference in all eight controllers and the UI composition module against the declared field allowlists, and validate every shutdown-resource owner mapping against its owning state/session/controller contract.

Flow 1's source-architecture exit criteria are complete. Focused regression coverage was updated for strict namespace contracts, front-session isolation, peer-controller lookup, and the absence of the legacy proxy. Python tests were not executed in this environment. Windows/GUI and GitHub Actions validation remain excluded from this workstream, so runtime acceptance is still pending.


## 9. Responsibility-aligned module sizing

**TASK ARCH-QUALITY-01 — right-size modules by responsibility, not line count**

Acceptance criteria:

1. Audit high-line-count production modules using their callers, dependency graph, data ownership, lifecycle and change patterns.
2. Keep a larger module intact when it represents one cohesive capability or workflow and extraction would create pass-through files or scatter invariants.
3. Extract a component only when it has a distinct reason to change, a separate lifecycle/owner, a meaningful independent contract, or a test seam that reduces coupling.
4. Do not impose a universal maximum LOC and do not split files solely to improve line-count metrics.
5. Record a keep/split/defer decision for each major candidate and revisit it after runtime/test evidence.

Initial candidates for evidence-based decisions (not automatic split instructions):

| Module | Current lines (approx.) | Decision | Responsibility-based rationale |
|---|---:|---|---|
| `kira/chat/persistence.py` | 1,611 | **KEEP** | SQLite repository, recovery, migration, pending-write queue and its application-facing facade share transaction and durability invariants. Keep this capability together; the public facade is already a distinct class. |
| `kira/auto_agent.py` | 1,435 | **KEEP** | Safe workspace access, action execution, bounded observations, checkpoints and delivery make one autonomous execution lifecycle. Splitting safety invariants across files would increase risk. |
| `kira/hybrid_ai.py` | 1,310 | **DEFER** | Provider adapters and route/failover orchestration are distinct concepts, but provider contracts, shared error classification, token accounting and telemetry are intertwined. Map the stable adapter contract and test each provider before extraction. |
| `kira/ui/main_window_provider_settings.py` | 1,148 | **KEEP** | Catalog refresh, provider credentials, model selection, route editing and benchmarks are one Provider Settings page/controller workflow. |
| `kira/tools/audio.py` | 1,161 | **KEEP** | Device discovery, volume/session control and default-device changes use one fixed native Windows Audio bridge and common verification/safety policy. Do not split by individual command. |
| `kira/chat/application_service.py` | 1,090 | **KEEP** | Request/session lifecycle, command dispatch, attachment ownership and history delegation form the public Chat application façade. Its helpers and collaborators already express the major boundaries. |
| `kira/evidence_memory.py` | 945 | **KEEP** | Fact provenance, backfill, retrieval and optional vector indexing belong to one evidence-memory store lifecycle. |
| `kira/ui/main_window_runtime.py` | 907 | **DEFER** | Chat response lifecycle, voice runtime and shutdown/resource drainage overlap through active-session state and Qt workers. Revisit only after runtime lifecycle tests identify an independently owned controller. |
| `kira/webintel/engine.py` | 719 | **KEEP** | Search, safe page reading, research rounds, evidence analysis and report generation are one provider-neutral research pipeline. |
| `kira/ui/main_window_composition.py` | 345 | **KEEP** | One production UI composition boundary; extracting smaller builders without independent lifecycle would add indirection. |
| `kira/main.py` | 27 | **KEEP** | Correctly minimal entry point; no further reduction is useful. |

**Current outcome:** no large file is split merely to satisfy a LOC threshold. The immediate decisions are KEEP for cohesive owners and DEFER for the two areas where extraction would cross shared contracts/lifecycle. A future SPLIT requires a concrete ownership boundary and focused regression coverage first.

