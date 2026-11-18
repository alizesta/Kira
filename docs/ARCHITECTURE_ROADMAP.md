# KIRA ARCHITECTURE ROADMAP

**Snapshot:** 2026-11-18  
**Base branch:** `new-main`  
**Base SHA:** `101361f60bb19a45484cbcdb7b52584eb3da0111`  
**Input:** TASK 015 audit plus post-audit merged TASK 013+014 integration PR #48.  
**Execution policy:** Documentation only. No tests, compile/import checks or application execution were run.

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

PR #55 removed the legacy `oldmain.py` runtime module and moved its 322 MainWindow methods into eight feature-oriented mixins. The remaining explicit architecture debt is application policy and cross-feature orchestration still held by those mixins. Runtime acceptance remains unverified: GitHub Actions jobs for the merge failed before runner assignment (runner ID 0, no steps), so they did not execute tests.

## 3. Technical debt register

Severity reflects architectural impact and evidence, not an assertion that a runtime failure has occurred.

| ID | Severity | Problem / evidence | Location | Owner | Impact | Dependency / proposed resolution |
|---|---|---|---|---|---|---|
| AD-01 | **High** | The former 5,634-line `oldmain.py` and its 322 MainWindow methods have been removed from the runtime path and split into eight feature-oriented UI mixins. Web Search query/provider/request/evidence policy is now extracted to `WebSearchApplicationService`; MainWindow still coordinates other application policy across capabilities. | `kira/ui/main_window.py`, `kira/ui/main_window_*.py` | Application/UI architecture | The file-level monolith is removed and Web Search policy now has an injected application-service owner, but feature policy is not yet fully owned by independent application services/controllers. | Continue moving policy from the mixins into existing domain/application services and inject narrow contracts through bootstrap. Keep MainWindow as UI composition and intent translation only. |
| AD-02 | **Medium** | ModuleManager lifecycle engine exists, but bootstrap currently registers only Memory, Mood, Character Profile and Chat History service modules. WebSearchApplicationService is injected directly but is not independently lifecycle-managed; Chat/Voice/Avatar/Coding Agent/Provider are also not independently registered. | `kira/app/bootstrap.py`, `module_manager.py`, `service_module.py` | Bootstrap / capability owners | The lifecycle manager does not yet govern the wider capability set; enable/disable and shutdown ownership are uneven. | Register a feature only when it has a stable lifecycle contract and real need for optional lifecycle control. Do not add empty wrapper modules merely to populate the manager. |
| AD-03 | **Medium** | Organization uses whole-document metadata updates. Independent writers can race and overwrite another writer's changes. | `kira/chat/organization.py`, `kira/chat/persistence.py` | Organization + Persistence | Concurrent metadata mutations can lose updates. No occurrence is claimed; this is a documented design limitation. | Add an atomic metadata patch/update contract at the Persistence boundary, then make Organization use it. Preserve unknown metadata keys and existing data format. |
| AD-04 | **Medium** | Deleting tags/folders updates conversations individually; it is not one cross-conversation transaction. | `kira/chat/organization.py`, `kira/chat/persistence.py` | Persistence (transaction) + Organization (policy) | Partial completion is possible if a multi-conversation operation fails midway. | Add a narrowly scoped bulk metadata operation in Persistence and delegate the multi-record transaction to it. Combine with AD-03 where practical. |
| AD-05 | **Medium** | Voice implementation is present but the documented Voice interface is not wired through the implementation; MainWindow's voice mixins remain involved in voice controllers. | `kira/voice.py`, `kira/listener.py`, `kira/local_voice.py`, `kira/ui/main_window_runtime.py`, core interfaces | Voice capability owner | Voice implementation is harder to replace or use independently; UI and device policy remain coupled. | Define/complete the narrow Voice service adapter and inject it at bootstrap. Keep device/Qt adapters at the outer boundary. |
| AD-06 | **Low** | Compatibility imports/defaults remain, including the `kira.main.MainWindow` compatibility export, `kira/attachments.py`, and legacy memory entry points. | `kira/main.py`, `kira/attachments.py`, `kira/memory.py`, `kira/persona_memory.py` | Migration owners | Obsolete paths may persist and confuse future ownership if not clearly marked. | Remove only after repository-wide call-site migration and compatibility requirements are resolved. No deletion in this roadmap task. |

### 3.1 Runtime-only verification items (not confirmed defects)

These are not classified as implementation failures because the audit was static and tests were prohibited:
- Kira/Ren/Mika isolation across simultaneous sessions, history, search, transfer, memory and restart.
- Conversation archive/restore/trash/permanent-delete behavior, authorization and transaction guarantees.
- Export/import round trips preserving status and the complete metadata namespace.
- Typed event delivery, ordering and terminal de-duplication under concurrency.
- Provider stream handling, cancellation and partial-response persistence.
- MainWindow GUI behavior and Windows device integrations.
- Search performance for large histories; current search scans repository pages and ranks in process.

These belong in the later explicitly authorized testing phase, not in TASK 016.

## 4. Development phases

### Phase A — Architecture Stabilization

**Goal:** reduce foundational coupling without destabilizing the application.

1. Keep `kira/main.py` as the thin entry point and `kira/app/bootstrap.py` as the single production Composition Root.
2. Continue replacing direct construction/compatibility fallback paths with injected services where a real call site needs it.
3. Continue moving MainWindow policy/controller responsibilities into existing application and capability owners; keep the window as an adapter.
4. Register additional ModuleManager-managed features only when their lifecycle and shutdown contracts are concrete.
5. Address Organization metadata lost-update and non-atomic bulk-operation limitations at the Persistence boundary (AD-03/AD-04).

**Exit condition:** ownership and composition boundaries are explicit; no new feature module duplicates an existing service or storage owner.

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

1. Complete the Voice contract wiring (AD-05).
2. Keep Memory and Character services injected through bootstrap; retire legacy adapters only after call-site migration.
3. Define independent Avatar/Emotion and Vision application boundaries only when there is a concrete consumer and lifecycle need.
4. Keep Web Research and Coding Agent policy outside MainWindow as they are extracted; do not create speculative service wrappers.
5. Add feature lifecycle registration only for components with actual start/stop/dispose needs.

**Exit condition:** each expanded capability has one owner, injected dependencies, explicit lifecycle where required, and no reverse dependency on MainWindow.

## 5. Recommended execution order

1. **MainWindow policy extraction** (AD-01), selected from a feature with a clear existing contract.
2. **One Persistence improvement covering AD-03 and AD-04**, retaining metadata compatibility.
3. **Voice contract wiring** (AD-05), using the existing interface rather than inventing a parallel one.
4. **ModuleManager adoption selectively** (AD-02), only after the chosen capability has a real lifecycle.
5. **Runtime acceptance** for the Chat and multi-character cases, only after the user authorizes the testing phase.
6. **Shared capability/Skills integration** only after confirming the actual implementation and target branch.

This is a prioritized sequence, not a mandate to create six separate tasks. Related changes should be grouped into a small number of coherent implementation units.

## 6. Legacy migration strategy

- Keep `kira/ui/main_window.py` as the UI composition point; its feature mixins are transitional adapters, not new domain owners.
- Move one coherent controller/service boundary at a time.
- Bootstrap creates concrete services and injects them; page widgets emit intents and render results.
- Preserve public imports until callers have moved.
- Preserve existing Chat history, metadata and settings formats; migrations must be additive/backward-compatible.
- Do not delete old files solely because a new module exists. Confirm all production and compatibility call sites before removal.
- Update this roadmap when a migration is merged; record the new base SHA and evidence.

## 7. Testing boundary and acceptance handoff

TASK 016 performed documentation/static repository inspection only. It did not run Unit, Integration, Regression, Windows, GUI, Compile, Import Check or the application.

When testing is explicitly authorized after TASK 016:
- Test Chat contracts and production DI wiring.
- Test lifecycle and organization with persistence/event integration.
- Test metadata concurrent writes and multi-record operations after AD-03/AD-04 are addressed.
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
