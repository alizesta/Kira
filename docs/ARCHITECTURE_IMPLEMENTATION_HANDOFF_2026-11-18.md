# Kira Architecture Implementation Handoff — 2026-11-18

**Repository:** `alizesta/Kira`  
**Target branch:** `new-main`  
**Source baseline:** `e398ed518ef446600ef758288f1dca2803845d98`  
**Starting point:** `6aaa9ce3955dc0ebdf8429255819128e01ee5897`  
**Change range:** https://github.com/alizesta/Kira/compare/6aaa9ce3955dc0ebdf8429255819128e01ee5897...e398ed518ef446600ef758288f1dca2803845d98

## 1. Executive status

This change set completes the principal source-level application-policy extractions that were outstanding around TASK 017–020. It does **not** claim runtime acceptance. Python tests, imports, bytecode compilation and desktop startup have not been executed in an environment available to this implementation session.

| Scope | Source status on `new-main` | Verification boundary |
|---|---|---|
| TASK 016 | Historical architecture/static audit and roadmap retained | Documentation/static scope only |
| TASK 017 — Session Application Orchestration | `SessionApplicationService` and composition factory added and wired | Unit/wiring tests added; not executed |
| TASK 018 — Web Search Application Policy | Existing `WebSearchApplicationService` retained and expanded earlier in the branch; UI delegates planning/parsing/diagnostics/evidence | Focused tests exist; not executed |
| TASK 019 — Voice and Game Mode | Existing `VoiceApplicationService` and `GameModeApplicationService` boundaries retained; per-character voice override handling added to Voice service | Focused tests exist; not executed |
| TASK 020 — MainWindow Feature Dependency Boundaries | Nine feature support modules remain scoped; Provider/Vision/Coding Agent/Runtime Settings/Character policies now have service owners | Static import-name audit and wiring tests added; no Python import/compile run |

The original task definitions and their merged PR states are not rewritten by this handoff. This report documents the additional source-level delta on `new-main`.

A follow-up source fix on `new-main` also makes `ServiceModule.dispose()` unregister its DI service even when the service cleanup hook raises, with a dedicated regression test. Chat attachment fallback composition and the per-message attachment limit are exposed by `ChatApplicationService`; Chat UI no longer imports the low-level attachment module for those policies. The remaining MainWindow command/attachment work is UI sequencing and presentation, not an unowned payload-composition rule.

The selective ModuleManager audit found no justified additional registrations: policy-only services are stateless, while Voice/Vision worker lifetimes remain tied to UI adapters. The current resource-owning module registrations are retained.

A subsequent multi-character hardening pass moved ToolAgent turn caches, memos, results, cancellation, AccessManager intent/taint/grants and pending confirmations into per-character state. Tool plans carry their owner through the background execution context. WebIntel uses one persisted research store per character and a session-scoped cancellation facade; Web-capable ToolAgent calls are serialized so executor threads cannot observe another character's cancellation. Closing a drained Session releases ephemeral state and cached stores while retaining resumable task/research files. TaskStore retains the last five completed plans plus active plans independently for each character, and the chat brain only checks the current character's task state. Focused regression tests were added in `tests/test_tool_agent_session_isolation.py`; they are source-level additions and are not described as executed.

## 2. Files and responsibilities added or changed

### Session application

- `kira/app/session_application.py`
- `kira/app/session_composition.py`
- `tests/test_session_application.py`

`SessionApplicationService` coordinates initial activation, conversation-ID binding through `ChatApplicationService`, Session state-event translation, profile-to-session synchronization, history restoration, pending-work checks and disposal. `SessionManager` remains the canonical runtime Session state machine. Qt view/timer/tab construction is supplied as a callback by the UI adapter; the service does not import Qt.

Production wiring was updated in:

- `kira/app/bootstrap.py`
- `kira/ui/main_window.py`
- `kira/ui/main_window_composition.py`
- `kira/ui/main_window_session.py`
- `kira/ui/main_window_runtime.py`
- `tests/test_chat_application_wiring.py`
- `.github/workflows/chat-session-lifecycle.yml`

### Provider and routing application policy

- `kira/app/provider_application.py`
- `tests/test_provider_application.py`

The service owns provider/API registry operations, route mutations, Ollama URL validation and client creation, router creation, and per-session router replacement. The router replacement method constructs all replacement routers before mutating Session references, avoiding a partial set if a factory fails.

Provider settings, lifecycle settings and voice settings UI adapters now call the service rather than directly invoking route/API policy modules or constructing the Ollama client.

### Vision application policy

- `kira/app/vision_application.py`
- `tests/test_vision_application.py`

The service owns capture eligibility, policy/cadence, busy-state admission, frame deduplication, result deduplication and latency statistics. Qt screen capture, timers, worker instances and result presentation remain in the UI adapter.

### Coding Agent application boundary

- `kira/app/coding_agent_application.py`
- `tests/test_coding_agent_application.py`

The service owns attachment-free turn interception, completion of the local Chat request after successful handoff, and stop delegation. The existing Coding Agent runtime is reused; it was not duplicated or replaced.

### Runtime settings application policy

- `kira/app/runtime_settings_application.py`
- `tests/test_runtime_settings_application.py`

The service owns propagation of settings to shared runtime consumers (ToolAgent, evidence memory and usage). Settings widgets and collection remain in the UI.

### Character profile and voice preferences

- `kira/services/character_service.py`
- `kira/services/mood_service.py`
- `kira/app/voice_application.py`
- `tests/test_character_profile_service.py`
- `tests/test_voice_application.py`

Character profile create/update/delete, character-scoped preference/resource normalization and personality trait/note updates are delegated to `CharacterProfileService`. `MoodStateService` exposes active-character trait updates. `VoiceApplicationService.apply_character_settings` applies only the allowed per-character voice overrides to a copy of shared settings, without mutating the base settings dictionary.

### UI dependency and CI audit

- `tests/test_application_policy_wiring.py` — source-level ownership assertions for Session, Provider, Vision, Coding Agent, Runtime Settings and Character/Voice policy.
- `tests/test_provider_application.py` — includes Ollama dialog client construction.
- `kira/ui/main_window_*_support.py` — nine scoped feature dependency modules remain in use.
- `kira/ui/main_window_composition.py`, `main_window_session.py`, `main_window_lifecycle.py`, `main_window_voice_settings.py` — stale imports of moved policy dependencies were removed.
- `.github/workflows/chat-session-lifecycle.yml` and `.github/workflows/kira-release.yml` — focused Qt-free tests and compile-file lists were updated.

## 3. Responsibilities intentionally retained in UI

The following remain UI/adapter responsibilities and were not moved into Qt-free services:

- QWidget construction and widget state.
- Qt signal connections and event-loop/timer integration.
- Worker and device object construction/lifetime.
- Dialog presentation and user confirmation.
- Screen capture and image transport to a Vision worker.
- Rendering chat messages, status and tool/agent progress.
- Adapting UI input values into service requests.

This is intentional separation, not evidence that those behaviors were ignored. Remaining non-UI command/attachment orchestration should only be extracted where a stable policy boundary exists.

## 4. Static checks performed

The GitHub source was inspected after changes. A static audit parsed the support-import clauses for all nine MainWindow mixins and the composition module and compared referenced imported symbol names against the corresponding support module source. At the last check, no imported symbol was missing from its paired support module.

The following checks were added to repository automation:

- Session service unit tests and Chat wiring assertions.
- Provider service tests (including route mutation, rollback, router replacement and Ollama client construction).
- Vision policy tests.
- Coding Agent handoff/stop tests.
- Runtime settings propagation tests.
- Character profile/preferences/personality tests.
- Voice override tests.
- Application policy wiring checks.
- Python `py_compile` file list includes the new services and wiring tests.

These are **checks configured**, not checks executed. The static source audit does not substitute for the Python interpreter's import resolution or execution.

## 5. CI execution blocker

GitHub Actions runs were created by the pushes to `new-main`, but the inspected jobs terminated before an actual runner was assigned. For example, the inspected Chat Session Lifecycle job reported:

- `runner_id = 0`
- `steps = []`
- no runner name
- job marked failed within seconds of creation

The job log endpoint returned `BlobNotFound`. This is not evidence that a test failed; it is evidence that the job did not begin executing steps. No test or compile pass can be inferred from these runs.

The reviewer should first obtain a working Actions runner or run the workflow commands in a Python 3.12 environment with the project's declared dependencies. Then inspect actual assertion, import, integration and GUI failures.

## 6. Reviewer checklist

Please review the change range above and specifically verify:

1. Python import and syntax correctness for all changed `kira/app`, `kira/services` and `kira/ui/main_window_*.py` modules.
2. Session factory construction in Bootstrap and the exact SessionManager/SessionApplicationService/ChatApplicationService lifecycle, including close/reopen, failed Session replacement, history restoration and shutdown disposal.
3. Session state event names/payloads and the absence of duplicate subscriptions or duplicate event publication.
4. Provider API wrapper signatures against the underlying `api_manager` functions, provider registry cleanup, route mutation rollback and router replacement behavior with live sessions.
5. Vision capture policy behavior for disabled Game Mode, disallowed profiles, busy Chat/provider, duplicate frames/results and worker errors.
6. Coding Agent behavior with and without attachments, with empty/no-op agents, request IDs and stop calls.
7. Runtime settings propagation ordering and failure behavior; confirm that shared settings are not partially applied unexpectedly.
8. Character profile behavior for built-in/custom profiles, deletion while a Session is active, unknown settings keys, resource normalization, voice overrides and personality notes.
9. Whether tests exercise production wiring rather than only checking source text; expand integration tests where the existing fakes do not represent actual contracts.
10. Full test discovery, compile checks, Windows/offscreen GUI behavior and a real application startup/shutdown cycle.

## 7. Known verification limit

This handoff is a source-level implementation report. It intentionally does not label TASK 017–020 runtime-verified or claim that the test suite passes. Any bug found in review should be corrected on `new-main` with a focused regression test and a fresh executable verification run.
