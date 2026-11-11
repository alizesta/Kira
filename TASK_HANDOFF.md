# Task Handoff

## Current release preparation
- Ren and Mika built-in portrait files were removed for this release at the user's request. Their profiles remain available with blank portrait areas; add separate replacement artwork later.
- Kira's original `assets/characters/kira.svg` remains unchanged.

## Current task
Fix regression failures from `ProjectKira_261111_0603.zip`: batch-file CRLF packaging, stale requirements expectation, LeakGuard-aware streaming/persistence tests, and current GUI menu assertions. Linux CI is expected to validate portable tests; GUI offscreen and actual Windows runtime still require platform-specific verification.

## Current task history
Character specialization and generated portraits. The implementation is complete in source; verify the new portraits and role prompts in the Windows 11 UI. The earlier Ai1 Code phase 2 Windows validation remains outstanding.

## Branch
`feature/characters-ren-mika`

## Implemented in phase 2
- Code Agent can propose a complete replacement for the selected file only.
- Proposal parsing requires exact start/end markers, rejects empty output and enforces a 512 KiB model-output ceiling.
- Patch generation is blocked whenever the selected context contains redacted credentials.
- Workspace presents a read-only unified Diff and requires an explicit apply action.
- Apply is rejected if the file on disk or editor content changed after the proposal was created.
- Approved changes preserve a one-time `.ai1code.bak` backup and use a temporary sibling file followed by atomic replacement.
- Added tests for valid marker parsing and malformed/empty proposal rejection.

## What remains for user-side validation
1. Run the latest ZIP on Windows 11 and open Ai1 Code.
2. Select a small text/code file and ask for a simple one-file change.
3. Confirm the Diff is readable and rejecting the dialog leaves the file unchanged.
4. Generate another proposal, approve it, and confirm the file changes and the backup exists.
5. Modify the file externally after opening it; confirm stale Patch application is blocked.
6. Test PowerShell with a harmless read-only command and inspect output/exit code.
7. Capture any traceback or UI freeze. GUI/PySide6/PowerShell are not exercised by portable CI.

## Not implemented yet
- Multi-file coordinated patches and cross-file Diff.
- Automated test runner and test-result UI.
- Debugger and breakpoints.
- Git status/diff/commit controls.
- Windows runtime debugging based on the user's actual machine logs.


## Character specialization update
- Kira has a coding/software-development specialty prompt and directs project-file workflows to Ai1 Code without claiming tests or edits that did not happen.
- Mika specializes in medical information and health education with explicit no-diagnosis/no-prescribing boundaries, emergency escalation and privacy-aware handling. Chat history remains shared; profile-level medical-memory isolation is not implemented.
- Ren specializes in current news and intelligence analysis with date checks, independent-source comparison and fact/claim/opinion separation.
- Character specialties do not alter shared model routes, tools, permissions or safety policy.
- Restored Kira's original profile portrait by selecting the existing `assets/characters/kira.svg` asset, unchanged from the earlier releases. Ren and Mika portrait files were removed for this build; their profiles render without portraits until replacement artwork is added.
- Portable regression tests cover the specialty prompts. Windows GUI image rendering still needs a user-side check.


## Game detector self-identification fix
- Root cause: the generic large-foreground-window heuristic did not exclude Ai1's own process. Its full-size window could therefore trigger the game suggestion.
- Fix: `GameModeMonitor.poll()` now ignores `os.getpid()` before title/process hints and window-size heuristics.
- Regression test covers the `Project Kira 1 stable` title, current process ID and full-screen geometry; it must emit no `game_detected` signal.


## 2026-11-11 native function calling and Game Mode follow-up
- Native Function Calling is implemented for OpenAI-compatible providers through OpenAICompatibleProvider.chat_with_tools() and HybridRouter.chat_with_tools().
- ToolAgent prefers native structured calls when a selected route supports them; unsupported routes retain the text-protocol fallback. Tool execution still passes through the existing registry and permission boundaries.
- Current native coverage: Groq, Mistral, OpenRouter and configured OpenAI-compatible endpoints. Current Ollama and Cloudflare adapters remain text-protocol only.
- Native tool-call requests are non-streaming; final responses remain streamed. Verify provider-specific schema compatibility and real tool calls on Windows/API accounts.
- Game detector now ignores the Ai1 process ID and known Ai1/Kira product window titles. Tests cover same-process title, mismatched-PID product title, and a positive large game window. Actual Windows 11 foreground-window/PID behavior still needs user-side validation.
- CI must run tests.test_native_function_calling and Python compile checks before release packaging.

- The Ai1/Kira window-identity predicate is isolated in kira/game_detection.py so its PID/title rules are exercised in portable CI independently of the Windows/PySide6 monitor integration.


## Stage 1: Game Mode self-detection validation
- Current source rejects Ai1's own PID and known Ai1/Kira window titles before game-name and large-window heuristics.
- Portable tests cover the current PID, the `Project Kira 1 stable` title with a mismatched PID, the `Ai1` title, and a positive unrelated game-window case.
- Added a required Windows CI job running `tests.test_game_detection` and `tests.test_game_mode` with PySide6/Qt offscreen. Release packaging is gated on that job.
- CI does not emulate the user's actual desktop session. A final interactive smoke test on the user's Windows 11 machine remains necessary to confirm its live title/PID behavior.

- First Windows CI attempt exposed a test-fixture issue: the positive large-window test called QApplication.primaryScreen() without an application instance. The fixture now initializes QApplication; the Windows job must be rerun before this stage is considered complete.


## Stage 2: Native Function Calling provider coverage
- OpenAI-compatible native tools already cover Google AI Studio/Gemini, Groq, Mistral, OpenRouter and custom compatible providers. Gemini uses Google's official OpenAI-compatible base URL.
- Added native Ollama `/api/chat` tool calling, including structured arguments and multi-round assistant/tool result messages.
- Ollama models that explicitly reject tool support return an unsupported signal; HybridRouter does not count that route as native-capable and can fall back to another native route or the existing text protocol.
- New offline tests cover Google/Gemini request shape, Ollama request/response parsing, tool-message round trips and unsupported-model fallback.
- The existing ToolAgent registry/permission/confirmation/Game Mode guard remains the only execution path.

- First Stage 2 CI run stopped at import time because the new Ollama round-trip test had invalid string escaping. The fixture now uses `json.dumps`; rerun the complete Windows-gated workflow before publishing this stage.


## Stage 3: Model Discovery and Route Manager
- Provider discovery and model registry were already implemented in the current branch for Gemini, Groq, Mistral, OpenRouter, Cloudflare and custom OpenAI-compatible endpoints; Ollama model discovery uses its own local scan.
- Verified Gemini's direct official model-list path and its pagination. Added tests that ensure non-chat models are filtered and the key is sent only in the header.
- Registration keeps every discovered model in API Details while activating only the provider default; additional models require explicit selection. Refresh marks vanished models unavailable but preserves their existing Routes.
- UI refresh is asynchronous and routes are created/disabled through the API Manager. Added source regression assertions for refresh and model toggle wiring.
- Gemini capability fields not exposed by the model-list API stay Unknown rather than being guessed.


## Stage 4: Persistent user-memory durability
- The app already stores settings and chat history outside the install folder. This stage closes a migration/backup gap: persona-memory JSON was not included in legacy migration or rolling backups, and evidence DB was backed up but not included in legacy migration detection/copy.
- `kira/storage.py` now detects, migrates and backs up persona memory and evidence-backed SQLite memory, preserving existing destination files and never deleting old source data.
- Added `tests/test_storage.py` for Windows data-directory resolution, explicit override, non-destructive legacy migration and rolling backup content.

- The first Stage 4 workflow run passed Windows and portable tests but the GitHub Release action returned 403 because the workflow did not explicitly declare `contents: write`. The workflow now grants that minimum release permission; rerun and verify the published asset before treating Stage 4 as delivered.
