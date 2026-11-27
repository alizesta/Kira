## Model-read user state: [user:state] reply tag (2026-11-26 08:16 Iran)
- `director.format_hint()` asks the model, ONLY when the user's last message clearly shows a state even through slang/sarcasm, to add ONE extra line `[user:state]` right after the emotion tag (state = the 12 keys of `mood.USER_STATES`). No extra request; ~60 prompt tokens.
- `emotion/parser.extract_user_states` removes it inside `parse_reply` (the single choke point for display, history, TTS, stream flush), including a half-typed `[us` / `[user:do` at the end of a stream; unknown names are dropped; `ReplyMeta.user_states` carries the result.
- `main_window_runtime` (assistant branch) -> `mood_service.on_model_user_states` -> `mood.on_model_user_states` + `EmotionalRuntime.on_model_signals`: skips states the keyword detector already found for that message, applies at 0.6x strength, no energy cost, no memory (no verbatim text). It affects the NEXT turn's prompt/mood (this reply is already written).
- Limits: depends on the model following the hint (weak models will omit it: harmless); not shown in the plain/retry prompt. Tests: `tests/test_model_user_state.py` (9). No new failures vs base (35 pre-existing in the emotion/mood/voice/character test set).

## Game events -> emotion, and negation-aware user-state detection (2026-11-26 08:11 Iran)
- Game events: the vision prompt now asks for `[HIGHLIGHT:kind] sentence` (kind = death|win|danger|funny|rare). `vision_pipeline.extract_highlight_event` maps it to new events in `emotion_library/events.json` (`game_player_died`, `game_victory`, `game_danger`, `game_funny`, `game_rare_find`: avatar face + `runtime_emotions`/`runtime_behaviors`). `_react_to_game_event` fires `director.event` (face) and `mood_service.on_event` (feeling), max once per 20 s per kind, only when Eye/Game Mode + `game_commentary` are on; the feeling changes even if she stays silent (busy/speaking/rate-limit). Plain `[HIGHLIGHT]` without kind still works (speech only).
- FOUND: `mood_service.on_event` / `runtime.trigger` had NO production caller, so the `runtime_emotions` of the existing app/response events in events.json (e.g. response_failed -> sad) never affected the runtime. Not changed here (only the new game events are wired); wiring the old ones would change her mood on every reply, decide first.
- Negation: `mood.detect_user_states` now ignores a keyword negated in the same clause ("استرس ندارم", "بدون استرس", "نمی‌ترسم", "گریه نکن", "i don't feel bad"); clauses split on punctuation / ولی / اما / but. Also fixed: "خسته‌ام." / "خسته‌ام،" / "تنهام؟" were not detected because the pattern required whitespace or end after the word.
- Tests: `tests/test_game_emotion_and_negation.py` (7). Pre-existing failures unchanged (4 in the touched test files). Not verified: a real model emitting the kind tag, Windows.

## Local repetition guard (2026-11-26 08:05 Iran)
- New Qt-free `kira/character/repetition.py`: keeps the last 6 replies per character in memory; `mood.on_reply` records the reply text and `mood.build_block` (chat mode only) appends a short note naming worn openers / phrases repeated across recent replies / near-identical last two replies. No model call, no extra latency (test asserts < 5 ms per request). `HighlightGate` now also drops near-duplicate game comments (Jaccard >= 0.7).
- Limits: the guard only advises (prompt text), a model can still ignore it; word-based, tuned for fa/en; in-memory (resets on restart). 18 tests in the mood/character/vision test files already failed before this change (unchanged).
- Tests: `tests/test_repetition_guard.py` (5).

## Start with Windows + spontaneous game commentary (2026-11-26 01:41 Iran)
- Autostart: new Qt-free `kira/autostart.py` writes `HKCU\...\Run\ProjectKira` = `wscript.exe "<root>\start_kira.vbs" autostart` (no admin). `start_kira.vbs` turns that argument into `KIRA_AUTOSTART=1`; `bootstrap.py` then hides the window to the tray (companion stays) and falls back to showing it if the tray is unavailable. Setting `start_with_windows` (default True, switch on the Characters page); `apply_runtime` keeps the Run entry in sync on every start/save.
- Commentary: the existing Vision analysis prompt now asks for an optional last line `[HIGHLIGHT] <one friendly Persian sentence>` only for remarkable moments, so there is NO extra model request. `_on_game_vision_result` -> `_maybe_comment_on_highlight` shows + speaks it when `game_commentary` is on (default True), Eye/Game Mode is on, Kira is not busy or speaking. `HighlightGate`: min 60 s apart, max 10 per hour, never the same remark twice in a row. Not persisted to chat history. Does not touch the Gemini Live proactive audio path.
- Tests: `tests/test_autostart_and_commentary.py` (4, fake registry). Not verified: real registry write, real login start, hidden-tray start, a real model emitting the HIGHLIGHT line (prompt wording may need tuning), Windows.

## Automatic free-chain setup (2026-11-26 01:37 Iran)
- New menu item "راه‌اندازی خودکار زنجیره‌ی رایگان Gemini" under Benchmark ▾ in the Routes page. `api_manager.prepare_free_chain` creates DISABLED routes for the chain models the Google API really lists (hydrogen last, never probed); the existing serial `router.benchmark` sends ONE tiny request per route; `api_manager.apply_chain_probe` enables only the ones that answered, in chain order, first in priority, and sets the default route. Failed ones (e.g. 429) stay off with the error shown; run it again later.
- Limit: Google exposes no quota numbers, so "measuring the rate limit" is one probe per model, not an RPM test. Cooldown/429 failover already existed.
- Tests: `tests/test_free_chain_setup.py` (2). Not verified: the real UI action, Windows, a real Gemini key.

## Eye Mode auto screenshot + single detail retry (2026-11-26 01:25 Iran)
- Branch `claude/eye-vision-free-models`. With Eye Mode on, `ChatController.submit` now attaches ONE fresh screenshot when the question refers to the screen (`refers_to_screen`, phrase list `SCREEN_HINTS` in `vision_pipeline.py`). Not attached when busy (a queued frame would be stale), when the user attached something, when Eye Mode is off, or when settings key `eye_auto_screenshot` is false (default true, not in the schema/UI yet).
- Small-text questions capture 1280x720 q80. If the reply says it could not read (`UNREADABLE_HINTS`), `on_stream_done` -> `maybe_retry_eye_detail` resends ONCE at 1280x720 (the retry is marked detail, so it never loops). Known limit: the retry re-submits the same question, so the user message appears twice in the chat.
- Not verified: the full MainWindow flow, Windows, a real Gemini call; the hint lists are keyword guesses and need tuning from real use. Whether older turns' screenshots stay in provider history was not checked.
- New `tests/test_eye_auto_screenshot.py` (4 tests, mocked controller). Pre-existing failures unchanged (`test_chat_application_service` event publisher test, OCR test, router tests).

## Eye Vision detail capture plumbing — follow-up (2026-11-26 00:48 Iran)
- Branch `claude/eye-vision-free-models`. `capture_desktop_attachment(detail=True)` now captures 1280x720; `_live_vision_attachment(question, detail=)` picks detail via `wants_detail_capture(question)` and encodes at q80. Detail constants moved to Qt-free `vision_pipeline.py` (re-exported by `desktop_capture.py`).
- Still NOT triggered anywhere: since Task 2, ordinary chat does not attach raw frames, so `_game_vision_attachment` has no caller. The automatic single retry (`reply_was_unreadable`) needs a chat-side trigger that is not built yet.
- Tests: affected files show no new failures vs the base; `tests/test_router_routes.py` already fails 20 tests on untouched `new-main` here.

## Eye Vision capture + free Gemini model chain — handoff (2026-11-25 17:26 Iran)
- Branch: `claude/eye-vision-free-models`, based on `new-main` b41de3f. No Pull Request opened, no GitHub Actions run.
- Capture (`desktop_capture.py`): default 768x432 (was 854x480), JPEG quality 78 (was 68), Qt resampling `FastTransformation` -> `SmoothTransformation` (text edges). New `CAPTURE_DETAIL_*` constants: 1280x720 / q80 for small text and OCR.
- Policies (`vision_pipeline.py`): economic 768x432 q75, smart 768x432 q78, fast 960x540 q80. New `wants_detail_capture()` and `reply_was_unreadable()` helpers (keyword lists `DETAIL_HINTS` / `UNREADABLE_HINTS`). NOT yet wired into the chat attachment path: nothing calls them, so the 1280x720 escalation and the single automatic retry are still to be connected.
- Gemini native transport (`hybrid_providers.py`): images now send `generationConfig.mediaResolution` = LOW by default (`payload["media_resolution"]` = low/medium/high overrides). `NATIVE_GEMINI_MODELS` also covers gemini-3.6-flash, gemini-3.5-flash-lite, gemini-3.1-flash-lite, gemini-3-flash-preview. Gemma stays on the OpenAI-compatible layer.
- Models (`settings_schema.py`): start-model preference is now 3.8-flash > 3.6-flash > 3.5-flash-lite > 3.1-flash-lite > flash-latest > 2.5-flash (the first one the account lists). Added `GOOGLE_FREE_VISION_CHAIN` (3.8-flash, 3.6-flash, 3.5-flash-lite, 3.1-flash-lite, gemma-4-31b-it, gemma-4-26b-a4b-it) and `GOOGLE_DEEP_REASONING_MODEL` (gemini-4-hydrogen) as reference constants; the live fallback order is still the Route priority the user sets in the Models panel. `discovery.py` now classifies `gemma-4*` as free.
- Tests: updated size expectations (768x432) in test_desktop_capture/test_game_mode, the native body expectation in test_gemini_native; 2 new tests in test_vision_pipeline. Ran the affected files locally (Linux, PySide6 offscreen): no new failures; `test_optional_ocr_uses_a_timeout_and_rejects_oversized_images` already failed before. Not verified: Windows, a real Gemini call.

## Inline chat progress (replaces the composer checklist) — handoff (2026-11-25 00:35 Iran)
- Branch: `claude/inline-progress`, based on `new-main` 493e39b (which already grants the session controller `views.kode_activity`).
- Verified here (Linux, offscreen): the rendering helpers on a bare QTextBrowser (4 new tests incl. removal with messages before/after, all end states, HTML escaping) and a rendered screenshot. Not verified: the full MainWindow flow, Windows, the real theme. `tests/test_chat_code_gui.py` already fails on untouched `new-main` in this sandbox, so its updated tests were not executed.
- Known limit: once the first answer text is written, later tool phases of the same request do not draw progress lines again (the tracker stays suspended until the next request).

## Progress checklist (replaces thinking line + activity card) — handoff (2026-11-24 22:46 Iran)
- Branch: `claude/progress-checklist`, based on `new-main` 4183cdc. Not merged; no Pull Request opened (a PR would trigger `android-apk.yml`); no GitHub Actions run.
- Verified here (Linux, PySide6 6.12 offscreen): the new panel renders correctly in RTL for running, done and failed states (rendered to PNG and inspected); all edited files compile. Not verified: Windows, the real Kira theme, the full MainWindow flow.
- `tests/test_chat_code_gui.py` already fails on untouched `new-main` in this sandbox (`MainWindow` has no `code_chat`), so the updated/new tests in it were NOT executed here.
- Design note: the progress bar is honest about unknown length: it never reaches 100% until the request completes (value = (done + 0.5) / (rows + 1)).

## Companion bubble and Tray shutdown follow-up — release 1.2.6 (2026-11-24)
- Branch: fix/companion-tray-shutdown-escape, based on the current new-main after PR #267.
- Fixed shutdown ordering in kira/ui/main_window_runtime.py and kira/ui/main_window_lifecycle.py: the first close attempt no longer hides the Tray icon or enables quit-on-last-window before workers and persistence have completed. Only the accepted-close callback _exit_application hides Tray and ends the event loop.
- Added a QShortcut with WidgetWithChildrenShortcut scope to CompanionBubble; Escape closes the composer and returns to the timed preview.
- Added kira/ui/companion_session.py as a Qt-free session marker helper. It prefers session_id, then falls back to (cid, conversation_id). Both lifecycle comparison and history restoration use the same marker.
- Added tests/test_companion_tray_shutdown_contracts.py using only the standard library for structural regression checks plus direct tests of legacy marker fallback.
- Verification performed here: source/diff inspection and marker checks only. The new test file, Python suite, PySide6 offscreen interaction and Windows Tray behaviour have not been executed in this environment. Do not claim runtime acceptance until the target Windows test is done.

## ToolAgent test regressions — handoff (2026-11-24)
- Corrected `tests/test_tool_agent_denial_buffer.py`: its `_run_once` mock now uses a callable `side_effect` with a call counter, so the first-round and retry handlers are actually invoked with the production callback arguments.
- Updated `tests/test_tool_registry_validation.py` to assert the compact inventory by default, then use `name="report_probe"` to assert full parameter contracts. Pagination now expects the current `تعداد ابزارهای منطبق` label.
- No production code changed in this follow-up. The fixes are committed on a branch and are awaiting repository test execution; this environment has not run Python imports or unittest.

## Eye Vision settings tab — handoff (2026-11-24 07:13 Iran)
- Branch: `feat/eye-vision-settings-tab`, based on `new-main` e339ac8. Overlaps with ChatGPT's planned Eye Mode status panel (`feat/eye-mode-proactive-status`): that panel (enabled/monitor/last successful frame time) can live in this same page; rebase that branch on `new-main` first.
- Verified offscreen with a real composed MainWindow: the tab builds lazily, a profile change is saved without enabling Eye Mode, a budget change reaches the live selector policy, the page switch drives the composer button and follows it back. 10 new page tests pass.
- Pre-existing, not changed: turning Eye Mode on before the Voice settings tab was ever opened logs `AttributeError: views.voice_page has not been initialized` from `toggle_mic -> set_live_listening -> collect_voice_settings`. It reproduces on `new-main` without this change.
- Not verified: Windows, a real multi-monitor setup, RTL visual layout/styling in the real theme.

## Gemini Live frame budget — handoff (2026-11-24 07:05 Iran)
- Branch: `feat/live-video-frame-budget`, based on `new-main` 119a9ba.
- Defaults: 5 s minimum interval, 10 frames/minute. Not a daily cap: a daily or per-session cap would need persistence across restarts and is not implemented.
- Further savings not yet implemented: send frames only around the user's speech turns plus a slow baseline, and suspend streaming while the user is idle.
- Verified locally (Linux, offscreen): 16 selector tests incl. budget behaviour and the 60-ticks-of-constant-change case (10 frames sent), 27 tests across the selector and Live wiring files. Not verified on Windows or against a real Gemini Live quota. No GitHub Actions run by hand.

## Adaptive Live frame selection — handoff (2026-11-24 01:41 Iran)
- Branch: `feat/adaptive-live-video-selector`, based on `new-main` 9e85000. Not merged; no Pull Request opened (a PR would trigger `android-apk.yml`); no GitHub Actions run.
- Root-cause fix: undefined `MAX_VIDEO_FRAME_BYTES` in the vision controller silently disabled all Gemini Live video (visible as `live_video_encode_failed` / `error=NameError` in the vision trace on `new-main`).
- New Qt-free `LiveFrameSelector` replaces the inline 32x18 nearest-neighbour check. Synthetic measurement on 480x270 frames: the old check missed an 80x40 popup (mean 1.23%), a 60x30 popup (0.82%) and a 200x12 text line (1.33%) against its 1.5% threshold; the new selector sends all three and ignores a 2x16 caret and a 12x12 icon.
- Tuning constants live in `SelectorPolicy` (`mean_threshold`, `cell_threshold`, `hotspot_cells`). They were chosen on synthetic images, not real screens; tune from the new trace fields (`reason`, `mean_change`, `changed_cells`) after real use.
- Local verification (Linux, PySide6 offscreen): 11 new selector tests + 2 new wiring tests pass; real `QImage` sampling checked offscreen. Not verified: Windows/DXGI capture, a real Gemini Live session, CPU/latency.
- Known pre-existing failures on untouched `new-main` (identical set before and after this change): 19 in the wiring/registry test files (stale source-string assertions, e.g. Eye Mode rolling-context wording), 5 in `tests/test_vision_routing.py` (`MainWindow.submit` no longer exists) and 1 in `tests/test_gemini_live.py` (provider-key leak test).

## Release 1.2 — Eye Mode integration handoff (2026-11-24)
- Base: new-main; release preparation consolidates the Live Desktop Vision tasks and the subsequent Eye Mode/freshness-context work.
- User-facing behavior: Eye Mode is the unified, manually enabled desktop observation path for the selected monitor; it is not limited to games.
- Capture: monitor-bound capture with foreground identity and privacy-policy rechecks; change-aware samples; no raw-image disk persistence; stop/source-disable/privacy-denial clears queued visual state.
- Perception: PerceptionEngine + RAM-only DesktopContext, optional local replaceable OCR, bounded event/text state and a 2,000-character summary. Game Mode OCR remains off by default.
- Conversation context: latest observation carries freshness (fresh ≤15 s, recent 15–60 s, stale >60 s, unknown); earlier observations are explicitly historical. Ordinary chat receives text context rather than automatic raw-frame attachments.
- Gemini Live: changed full-monitor JPEG samples share the active Live audio session, with a one-frame queue and a maximum send rate of 1 FPS. This is sampled imagery, not continuous 30/60 FPS video.
- Verification boundary: regression test sources were added during implementation, but this release preparation did not execute Python tests, GitHub Actions, Windows/Qt/DXGI capture, OCR quality/performance, or Gemini Live API runtime checks. Those remain required before claiming runtime acceptance.
## Live Desktop Vision — Task 2 handoff (2026-11-23)
- Branch: `feature/live-desktop-perception-task-2`, based on the Task 1 commits already present in `new-main`.
- Added `kira/perception/` primitives: `ActiveWindowProbe`, `ChangeDetector`, `PerceptionEvent` and `PerceptionEngine`.
- Added lifecycle-managed, Qt-free `DesktopContext` with in-memory foreground application/window, foreground duration, bounded OCR text, deduplicated recent events and a 2,000-character provider summary. Sensitive state is purged whenever the foreground identity is unknown or blocked.
- `vision_ocr.py` now defines a replaceable `OcrEngine` contract and structured `OcrResult` (language/confidence). The optional Tesseract implementation uses only already-installed Pillow/pytesseract and existing language data; it never installs anything.
- OCR is triggered only after a changed foreground crop. Game Mode OCR is disabled by default (`vision_ocr_in_game_mode=False`); desktop OCR can be disabled independently. OCR errors are non-fatal.
- Chat now receives the bounded context summary; live raw frames are no longer added to every ordinary chat request. Explicit user image attachments and manual screenshot capture remain available.
- Added `tests/test_desktop_context.py`, `tests/test_perception_engine.py` and `tests/test_vision_ocr.py`; existing Game Mode/FrameGate paths remain in place. Local Python tests have not yet been executed; no GitHub Actions were run. Windows multi-monitor, OCR language-quality, CPU and added-latency measurements remain pending.
- Privacy Trace contains only safe metadata, counts and timings; it never stores OCR text, full window titles or raw image data.

## Fast Path Stage 4 — Real registry boundary integration tests (2026-11-22)

- Branch: `test/fastpath-real-boundary-integration`; based on `claude/task-understanding-review` after stage 3 PR #225 was merged.
- `FastPathRealRegistryBoundaryTests` exercises the production `ToolRegistry` and `AccessManager`; only the model router is stubbed to fail if called.
- Covers successful Fast Path dispatch and one success Journal entry; post-plan `tools_mode=off` denial and Journal record; Competitive Safe transition cancellation before dispatch; runtime execution-guard denial and Journal record; duplicate-call cache behavior without a second handler or Journal entry.
- Added assertions that Journal contains exactly one record for successful execution and no duplicate record for cached replay.
- Added turn-boundary coverage: the same call is deduplicated within one turn, allowed again after `begin_turn()`, and pre-dispatch cancellation creates no Journal record.
- Validation: updated test and documentation sources fetched back from GitHub and statically inspected. Python unittest and Windows runtime have not been executed; GitHub Actions were not run.
- Local command when a checkout is available: `python -m unittest discover -s tests -p "test_fast_commands.py" -v`.

## Stage 3 — Planned execution safety guards (2026-11-22)

- Branch: `fix/planned-execution-safety-guards`; PR #225 targets `claude/task-understanding-review`.
- `ToolRegistry.clean_args` rejects undeclared arguments rather than silently dropping typos/extra fields.
- `AutonomyMixin._run_calls_planned` requires each planned call to supply an explicit positive integer step ID and object arguments; malformed calls are rejected before binding or dispatch.
- Planned calls reject unknown/ambiguous step IDs, tool/step mismatches, and replay attempts for DONE, SKIPPED, RUNNING, AWAITING, or REVIEW steps.
- `planner.parse_plan` rejects duplicate, boolean, non-positive, and malformed step IDs rather than silently renumbering duplicate IDs; falsey non-list dependency containers are rejected instead of treated as no dependencies.
- Persisted task loading rejects malformed step records and duplicate IDs. Malformed dependency values are converted to an invalid sentinel, never dropped.
- `TaskPlan.deps_unmet` fails closed for missing, malformed, non-positive, ambiguous, self, and forward dependencies, even when a later referenced step is marked complete.
- Added 22 unittest methods covering argument validation, planned dispatch guards, planner structure, persisted state, and dependency ordering.
- Validation: updated source/tests/docs fetched back from GitHub and statically inspected. Python unittest and Windows runtime have not been executed; GitHub Actions were not run.
- Local validation when a checkout is available: `python -m unittest tests.test_execution_safety tests.test_fast_commands tests.test_task_triage tests.test_task_cost`.

## Fast Path stage 2 — Planner / ToolRegistry boundary review (2026-11-22)

- Branch: `fix/fastpath-web-lock-scope`; PR #224: https://github.com/alizesta/Kira/pull/224 (open, draft; not merged).
- Found and fixed unnecessary WebIntel lock acquisition for deterministic local Fast Path calls. The fast route returns after its single allow-listed registry execution and does not enter a web/model round, so it no longer serializes unrelated web research.
- Hardened `planner.parse_plan`: malformed, unknown, and forward dependencies are rejected rather than silently dropped. Valid backward dependencies remain intact.
- Added regression coverage for the web-lock boundary and four planner dependency cases.
- Reviewed execution boundary: Fast Path still reaches `ToolRegistry.execute`; app execution guard, `tools_mode=off`, argument validation, AccessManager permissions/intent, and sensitive-action confirmation remain enforced.
- Validation: files fetched back from GitHub and branch diff verified. Python unittest and Windows runtime were not run; GitHub Actions were not triggered.
- Next: when a local checkout is available, run `python -m unittest tests.test_fast_commands`, then the related task-triage/planner tests. Do not treat PR #224 as runtime-validated until then.

## Latest task: 20 adversarial multi-step cases (2026-11-22)

- Added 20 hard cases to `tests/test_task_understanding_benchmark.py`: conditional operations, sequence constraints, read-only boundaries, explicit approval/no-delete constraints, web evidence, status polling, and combinations of local tools with web/MCP/agents.
- Added a unittest asserting all required categories are detected and each hard case routes beyond index-only triage. Independent detector-pattern harness: 20/20 required-category coverage, zero regex compile errors. Extra category matches were observed in some prompts; this benchmark currently asserts required-family recall, not exact category precision.
- Python unittest suite, live model, and Windows execution have not been run. GitHub Actions were not triggered.

## Latest task: 200-case task-understanding benchmark (2026-11-22)

- Added `tests/test_task_understanding_benchmark.py`: 200 actionable prompts split evenly across 10 tool families, plus 20 chat-only negative controls. The test checks required category recall and that actionable prompts bypass index-only triage while ordinary chat remains on it.
- Dataset integrity checked through the GitHub source: 20 cases per each of the 10 protocol categories; 200/200 actionable entries unique and 20/20 chat controls unique. An independent JavaScript harness reconstructed from the Python regex patterns measured 200/200 required-category hits and 0/20 chat false positives; it exposed and prompted fixes for Persian local-time, paired-device/Pair, menu-genitive, counted-source, and delegated-job wording. The unittest fixture now mirrors the existing triage-test fixture and reuses one ToolAgent across the dataset. This is not an execution of Python's unittest module. The Python tests, live model, and Windows runtime remain unverified. No GitHub Actions run.
- Next: execute `python -m unittest tests.test_task_understanding_benchmark tests.test_task_triage` in a local checkout, fix every failing case against the actual detector, then run the broader relevant suite. After that, add a separate live-model benchmark for triage escalation, plan decomposition, approval compliance, recovery and verified postconditions.

# Task Handoff

## Latest task: review of model-driven task understanding (2026-11-22, 08:03 Iran)

- Branch `claude/task-understanding-review` (from `new-main` @ `42d34b6`). Reviewed `20aa301` (model-driven planning/verification) and `42d34b6` (model classifies intent in auto mode); fixed one regression (Competitive Safe gave every message a web plan, see CHANGELOG 08:03).
- 08:32 Iran: planner review calls (step review + final goal review) use `planner.REVIEW_SYSTEM` instead of the character prompt (CHANGELOG 08:32). A one-tool task is still 5 model calls; real latency per call on the user's routes is unmeasured. Next candidates (need real numbers first): skip the goal review for one-step plans, merge review with the next action, or route review calls to a faster `surface` model.
- 2026-11-22: English task-intent coverage expanded in `protocol.py`; a 20-case regression matrix was added to `tests/test_task_triage.py`. Independent regex check: 20/20 expected category sets covered; 19 actionable prompts bypass triage and the email-draft-only prompt remains in triage. Generic source-code discussion has a negative regression. Not verified: repository unit tests, live models, Windows execution. No Actions run.
- 08:23 Iran: the open cost question was resolved with a model-owned triage (`ToolPlan.index_only`, `use_tools`, see CHANGELOG 08:23): chat = one small call, unknown-wording tasks escalate to the full catalog/planner. Validate on Windows with a real route: «سلام» answers fast; «یه والپیپر زنده‌ی پورشه بذار» escalates and plans; check that weak local models (Qwen 4B) emit the `use_tools` block reliably (if not, they answer in text and the task is missed: then lower triage to keyword hits only for such routes); two characters chatting at once no longer wait on each other.
- Not verified: Windows runtime, real-model behaviour on the Wallpaper Engine / Porsche 911 example, full test suite. Only `tests.test_fast_commands` and `tests.test_task_store` were run (53 OK).

## Latest task: portrait, icon, tray menu (2026-11-21, 17:05 Iran)

- Check on Windows: Kira's card shows the new portrait; taskbar/window/tray show her face icon; right-click tray shows show/hide Kira, show/hide character, model, web, mic, خروج. If items are still missing, the cause is in `refresh_tray_menu` (`kira/ui/main_window_lifecycle.py`). The `.exe`/shortcut icon (`assets/kira_icon.ico`) is not wired into any installer or `.bat`.

## Latest task: Character tab merged into one page with per-character tabs (2026-11-21, 16:45 Iran)

- `CharactersPage` has no sub-tabs now: top `character_tabbar` (one tab per character) + `character_add_btn` (＋), then one scroll page. Edit/Delete stay in the card; `character_combo` is hidden but still drives selection. Check on Windows: tab switching changes chat colours/avatar, ＋ opens the creation dialog, layout in RTL.

## Latest task: Assistant tab merged into Character + Connections (2026-11-21, 16:26 Iran)

- No more Assistant tab. `AssistantPage` (kira/ui/pages/assistant_page.py) stays as the hidden owner of the widgets; `identity_box` goes to the Character tab personality sub-tab (`CharactersPage.attach_identity_box`), `model_box` (Ollama) goes to the Connections & Models tab (`ProviderSettingsController.build_ai_tab`, under the models list). Aliases (`views.persona`, `views.model`, ...) and lifecycle handlers are unchanged.
- Tab order is now chat, voice, character, appearance, general, connections (+ logs); nav icons derive from `tab_keys`.
- Not run: full GUI tests (no Qt Multimedia in the sandbox). On Windows run `python -m unittest tests.test_gui_offscreen` and check both groups by eye; press Save and restart to confirm name/persona/Ollama values persist. Known unrelated failures: two `test_ui_facade_regressions` tests (`widget_parent` argument).

## Latest task: desktop-pet behaviour (2026-11-21)

- New: `kira/pet.py` (PetController owned by `CompanionWindow.pet`), `kira/perch.py`, `kira/music_dance.py`, JS `kiraHang` / `kiraMusic` in `assets/vrm/viewer.html`; the music watcher starts in `main_window_composition.py` (Windows only).
- Ideas not done yet from Mate Engine: touch regions per body part with sounds, chibi mode, FPS limit, sleep/alarm, multi-avatar sync dance, screensaver, MMD/VMD import. Dance library (VRMA/Mixamo FBX in `assets/vrm/animations/`) is done but unverified with real files.
- Needs a visual check on Windows: sit height, dance poses, hang swing.

## Latest task: AI tab redesign (2026-11-20)

- `ProviderSettingsController` now builds `ApiPanel` (`self.api_panel`) and `ModelsPanel` (`self.models_panel`); data comes from `api_manager.api_rows` and `model_catalog.model_rows`. Handlers: `on_model_toggle`, `on_model_archive`, `on_model_restore`, `test_catalog_model`.
- Not run here: full GUI tests (Qt Multimedia crashes in the sandbox). Run `python -m unittest discover -s tests -t .` on Windows and look at the AI tab by eye.
- Known unrelated failures remain (window-factory based tests, `test_api_manager` x3, voice_settings root-context bypass).

## Previous task: Route hygiene (2026-11-20)

- Logic lives in `kira/routes.py` (`disable_route`, `disable_non_free_routes`, `reconcile_provider_models(free=, prefer=)`, `catalog_*` helpers) and `HybridRouter._mark_failure` (auto-disable after repeated "model" errors). UI wiring: `ProviderSettingsController._on_model_catalog_refresh` / `auto_refresh_model_catalogs`; startup hook in `main_window_composition.py`.
- Not verified on Windows: the full GUI suite could not finish in the Linux sandbox (Qt Multimedia has no audio server). Run `python -m unittest discover -s tests -t .` on Windows.
- Known failing before this task (also on the remote head): `test_api_manager` (unprefixed key, cooldown reset), `test_feature_controller_registry` (`voice_settings:112 root-context-bypass`), tests that still look for `kira/app/bootstrap.py` (real file: `kira/ui/bootstrap.py`).
- Not done on purpose: new free models are not auto-added as routes (would clutter the list); free detection is exact only for OpenRouter, heuristic for Google.

## Current architecture/documentation handoff — 2026-11-19

- PR #98 was merged into `new-main` as `0a84bbdc3d47afb1728ff314a056b49e6e56848b`. It corrected the stale Chat event test path and event-publication assertion, and added `tests/test_chat_events.py` to the Chat Session Lifecycle workflow path filter.
- The root `ARCHITECTURE.md` is now only an index. Canonical architecture status lives in `docs/ARCHITECTURE_MASTER.md`, `docs/MODULE_OWNERSHIP.md` and `docs/ARCHITECTURE_ROADMAP.md`.
- Production Qt Composition Root: `kira/ui/bootstrap.py`. References to `kira/app/bootstrap.py` in older snapshots are historical and superseded.
- CI is still **not verified**: the PR workflow jobs failed before executing steps (`steps=[]`), and logs were unavailable (`BlobNotFound`). Do not report the tests as passing or failing at test assertion level until a runner actually executes them.
- PR #99 merged the documentation synchronization into `new-main` as `65da5eae1b19ed57d3d4f7cba95a5c250f323d68`. The canonical documents and their snapshot metadata are now the source of truth.


## Architecture implementation update (2026-11-18) — TASK 017–020 source work

- The principal outstanding application-policy boundaries have now been implemented on `new-main`: Session orchestration (`SessionApplicationService`), Provider/routes (`ProviderApplicationService`), Vision (`VisionApplicationService`), Coding Agent handoff (`CodingAgentApplicationService`), shared Runtime Settings (`RuntimeSettingsApplicationService`), and Character profile/preferences/personality ownership (`CharacterProfileService`).
- Existing Web Search, Voice and Game Mode application-service boundaries remain integrated. Per-character voice overrides are applied through `VoiceApplicationService`.
- Nine feature-specific MainWindow support modules remain scoped; Qt widgets, timers/workers, device adapters, dialogs and rendering remain UI responsibilities.
- ToolAgent request caches, memos, cancellation, taint, confirmation grants, pending confirmations and task control are scoped to the character Session. WebIntel research files/cancellation and TaskStore history are also per-character; Session teardown releases ephemeral state while preserving resumable data.
- Task history retention now keeps the five most recent completed plans plus all active plans per character, rather than applying one global history cap. The chat brain's active-task signal is likewise scoped to the current character.
- Brain reply hints, turn counters and Reflection rate limits are now stored per character; clearing one character's chat resets only that character's Brain context. Kira's original state-file path is preserved and the optional Memory Writer cursor stays shared with the common history stream.
- Focused unit/wiring test modules and CI command/compile lists were added or extended. A static source audit found no missing names in the nine feature-support import sets or composition-to-root-support imports. Runtime route inspection/manual selection was also moved behind ProviderApplicationService; RuntimeMixin no longer imports the route policy module.
- **Not runtime-verified:** GitHub Actions jobs inspected on this branch completed with `runner_id=0`, `steps=[]` and no retrievable logs (`BlobNotFound`). No test, Python import, compile or Windows GUI run is claimed.
- Reviewer handoff and checklist: [docs/ARCHITECTURE_IMPLEMENTATION_HANDOFF_2026-11-18.md](docs/ARCHITECTURE_IMPLEMENTATION_HANDOFF_2026-11-18.md).
- Architecture records: [docs/ARCHITECTURE_MASTER.md](docs/ARCHITECTURE_MASTER.md), [docs/ARCHITECTURE_ROADMAP.md](docs/ARCHITECTURE_ROADMAP.md), [docs/MODULE_OWNERSHIP.md](docs/MODULE_OWNERSHIP.md).

Historical Windows/GUI and release validation items below remain historical and are not marked as completed by this architecture work.

## Latest task: no button, Kira understands + better coding (2026-11-13)
- `</>` removed; routing is automatic (see CHANGELOG 2026-11-13). Validate on Windows 11 with a real route: ordinary chat stays ordinary (greetings, 'what is a decorator?'); 'مدل دوبعدی رو حذف کن' starts a mission after the folder question and start confirmation; 'چرا آواتار دوبعدی قبل از VRM لود میشه؟' answers read-only with file names; an ambiguous 'این تابع رو درست کن' shows 'کیرا در حال فهمیدن…' then picks; speak a coding request by voice; check that code blocks look right in normal chat replies.
- Watch for false positives (normal talk routed to the agent) and false negatives (a real request answered as chat): the word lists are in `kira/chat_code.py`.

## Previous task: Ai1 Code autonomous agent (2026-11-12)
- Agent mode is built (see CHANGELOG 'Ai1 Code became an autonomous agent', ARCHITECTURE 'Ai1 Code mode'). Validate on Windows 11 with a real route: turn `</>` on, write a mission in plain words (no @), watch plan / steps / test logs, approve a `shell` command once and deny one, press Stop mid-run, open the delivered zip (name + report + no secrets), ask a plain question (read-only). Quality of weak local models (Qwen 4B) on multi-file missions is untested; an API route is recommended.
- Earlier same-day work follows.

## Earlier task: Ai1 Code inside Kira's chat (2026-11-12)
- Ai1 Code is now code mode of Kira's chat (`</>` button in her composer), not a menu item. See CHANGELOG 2026-11-12 (Ai1 Code moved into Kira's chat), ARCHITECTURE 'Ai1 Code mode', `kira/chat_code.py`, `kira/chat_code_ui.py`.
- Validation still needed on Windows 11: turn `</>` on in Kira's tab and pick a small project; ask with `@file`; request a change and check the Diff bubble + approve / reject links; approve and look for the `.ai1code.bak`; edit the file by hand before approving to see the stale refusal; try `/run Get-ChildItem` (confirmation dialog, output bubble, exit code) and the Stop button during a run; switch to Ren / Mika (button hidden, normal chat) and back while an answer is being written.
- Watch for: link clicks in the chat view (`setOpenLinks(False)` + `on_chat_link`), RTL look of the Diff bubble, the old `code_workspace_path` setting is reused as the project folder (`code_chat_on` is new).
- Not done: multi-file patches, test runner, Debugger, Git controls.

## Latest task: chat -> 3D body control (2026-11-12)
- Implemented `kira/body.py` + `window.kiraBody` in `assets/vrm/viewer.html` + wiring (`FaceAnimator.body` signal, `VrmView._body`, `ReplyMeta.body`, `MainWindow.body_active/run_body`, per-session `_body_done`). See CHANGELOG 2026-11-12 (chat controls Kira's 3D body).
- Validation still needed on Windows 11 with the real model: say "دستتو بیار بالا", "دست چپتو ببر بالا", "پشتتو کن", "برگرد", "خم شو", "تعظیم کن", "بشین", "پاشو", "دست به کمر", "دستاتو باز کن", "حالت عادی" and look at each pose. Angles are first estimates (arms/legs signs derived from the VRM normalized rig); adjust numbers in the `POSE` table of `viewer.html`. `window.kiraBodyState()` in the page shows active poses.
- Check the model really writes `[body:...]` tags (and the emotion tag first) with the routes you use; the rule-based reader of the user's message works without any model help.
- Watch for: sit/crouch height with this model's leg lengths, turn_back pivot (scene origin), arms through the body on `hands_on_hips`, hair/bust springs while turning.

## Current release preparation
- Ren and Mika portraits and full-body pictures were added (user-supplied). The chat page and floating companion now switch art with the active character (see 'Character art' below).
- Kira's original `assets/characters/kira.svg` remains unchanged.

## Latest task: character chat tabs (2026-11-11)
- Implemented per-character chat tabs/sessions, per-character SQLite history, character-themed chat styling, transparent Ren/Mika pictures. See PROJECT_CONTEXT 'Character chat tabs', ARCHITECTURE 'Character chat sessions'.
- Validation still needed on Windows 11 (the sandbox had no PySide6, so `tests/test_character_chats.py` GUI cases and the whole tab UI were NOT executed): run `python -m unittest tests.test_character_chats tests.test_gui_offscreen tests.test_chat_persistence`; then open all three tabs, send a message in each quickly, switch tabs while they answer, check ⏳/● marks, theme colours, Stop on one tab only, restart (history per tab), and Clear chat memory (only the visible character).
- Watch for: a Qt signal/slot issue in `SessionRelay`, layout of the tab strip in RTL, performance of the glow effects, `Muted` objects hiding a call that should reach a real widget.
- Older tests that assume one shared chat may need `character_id` arguments.

## Current task
Fix regression failures from `ProjectKira_261111_0603.zip`: batch-file CRLF packaging, stale requirements expectation, LeakGuard-aware streaming/persistence tests, and current GUI menu assertions. Linux CI is expected to validate portable tests; GUI offscreen and actual Windows runtime still require platform-specific verification.

## Current task history
Character specialization and generated portraits. The implementation is complete in source; verify the new portraits and role prompts in the Windows 11 UI. The earlier Ai1 Code phase 2 Windows validation remains outstanding.

## Branch
`new-main` (canonical architecture integration branch)

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
- Regression test covers the `Project Kira 1 stable` window title, current process ID and full-screen geometry; it must emit no `game_detected` signal.


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

- Added the workflow YAML itself to the path filter so workflow permission/gate edits trigger CI. Added coverage for legacy folders containing only persona or evidence memory.

- The permission fix initially duplicated the existing `permissions` YAML key, causing GitHub to reject the workflow before jobs were created. The workflow now retains exactly one `permissions: contents: write` block; the next push must prove Windows tests, storage tests and release publishing all run.


## Stage 5: Character-specific long-term memory
- Implemented context-local memory scoping in `persona_memory.py`. Kira keeps the legacy JSON filename; Ren and Mika receive separate files.
- MainWindow now scopes prompt memory, observation, summary maintenance, Memory dialog operations and clear-chat memory handling to the active character.
- Kira's evidence-backed SQLite index is not queried or mutated while Ren/Mika are active. They use only their own JSON persona memory.
- Short-term chat history in `kira_memory.sqlite3` remains shared across profiles; the character prompts and Memory dialog must not claim otherwise.
- Added regression tests for memory isolation and voice/joke state isolation. Run the full Windows-gated release workflow before publishing.

- Stage 5 also extends Stage 4 storage handling to every character memory file. Kira's legacy path remains unchanged; Ren/Mika/custom profile files are included in migration and backups, with existing destination files preserved.
- Character memory scope is context-local and restored after nested calls. Memory dialog text and prompt labels use the selected profile. Short-term chat history is still shared.

- Follow-up hardening: Ren/Mika no longer receive a digest of Kira's shared historical chat and do not summarize the global chat database. Clearing shared chat resets voice/digest samples for all characters but leaves their facts/moments/habits intact. Kira alone resets the shared mood state.
- The existing Kira evidence DB may contain unattributed facts backfilled from pre-isolation shared chat; this cannot be safely split because legacy chat rows lack character IDs. New Ren/Mika messages are not written to that index.


## Character art on the chat page (2026-11-11)
- `characters.py`: every profile has `image` (portrait for the Character tab) and `avatar` (full-body picture for the chat page / floating companion). Kira's `avatar` is empty = her own animated PNG. `avatar_file()` resolves it safely (missing or escaping paths -> None -> Kira's art).
- `face.py`: `FaceAnimator.set_character_art(path|None)` fits the picture into the 832x1248 reference canvas (`avatar_art.layout`), rebuilds the warp tiles, bumps `art_serial` (views rebuild their tile cache), turns the Kira-only face overlays off and lowers the rig gain to 0.55 for other characters. `AvatarView(view="card"|"full")` follows `card_rect`/`full_rect`; non-Kira art is clipped to a rounded frame inset by a 24 px bleed so sway never shows an edge.
- `main.py`: `apply_character_art()` runs at start-up and on select / add / delete character. The portrait is cover-cropped instead of stretched (Kira's SVG already fits and is untouched).
- `companion.py`: the floating window adopts the new picture's proportions and keeps its height.
- Not done: blinking / lip-sync for Ren and Mika (needs per-character eye and mouth landmarks or separate layers). Qt parts were NOT run in the build sandbox (PySide6 missing); `tests.test_gui_offscreen.test_19b_...` must be run on Windows/CI and the result checked by eye on the real desktop.


## Kira coding-agent upgrades (2026-11-13)
- Added static AST module/import/symbol map, automatic Ruff/Pyflakes after Python edits, snapshot-based Diff and Git-style status/diff, independent review gate, and `.ai1/PROJECT_MEMORY.md` carried in project ZIPs.
- Planner / executor / reviewer use configured `deep` / `surface` / `reflection` Route roles with normal fallback.
- The prompt asks Kira to add focused tests for changed behavior where practical; arbitrary PowerShell still needs per-command approval, and project files are still edited on a copy.
- Automated tests and the interactive Windows UI were not run for this update.
- Voice silent on Windows: added winsound path for wav (`voice._NativeWavPlayer`, setting `voice_native_wav`). Needs a real-device check; if still silent, ask for the error text Kira shows and check the Windows volume mixer for the app.

- 2026-11-21 23:49 Iran: UI icons live in `assets/icons/*.svg` (Lucide, ISC) rendered with glow by `kira/ui_icons.py`; `stop` and mood faces remain code-drawn.

- 2026-11-22 03:03 Iran: UNSLOP leftovers done (self-sizing tables via fit_height, collapsed advanced switches in Character tab, scoped notes labels).

- 2026-11-22 03:20 Iran: audio playback = `_PcmPlayer` (QAudioSink, PCM wav only) in kira/voice.py; QMediaPlayer / QSoundEffect / winsound removed. Needs a listening test on Windows.

- 2026-11-22 03:26 Iran: speech engine is switchable (settings `tts_engine`: piper | kitten; Kitten English-only, Persian sentences always Piper). See kira/voice.py `_use_kitten` / `_synth_kitten`.

- 2026-11-22 03:37 Iran: Voice tab = mode card (realtime/local) + mic/output cards + collapsed advanced; setting `gemini_voice`.

## Latest task: Gemini Live visual companion (Task 3, 2026-11-23)

- Extend the existing Gemini Live audio WebSocket with video frames from the selected full monitor. The active output is selected explicitly, or follows the monitor containing the foreground window in automatic mode.
- `AttachmentsVisionController` checks manual Live Desktop Vision/Game Mode enablement and revalidates foreground identity/privacy before every send. It samples meaningful visual changes only; the Gemini worker accepts no more than one JPEG/second into a one-frame RAM queue.
- `RuntimeVoiceMixin` provides the readiness/send/clear bridge. Audio and video sends are serialized on the same asyncio lock/session. Screen video is not written to disk or attached to ordinary chat.
- Stop, source disable and privacy rejection clear queued frames. The voice prompt instructs the companion to make useful, restrained observations and never claim unseen visibility.
- Added tests: `tests/test_gemini_live.py` (JPEG/rate gate), `tests/test_desktop_capture.py` (full-monitor capture tied to current HWND/PID), and `tests/test_gemini_live_video_wiring.py` (cross-controller contract).
- Validation: source changes are inspected through GitHub. No Python test, import, Qt/Windows capture, live Google API call, audio/video sync test or GitHub Actions run is claimed. Full monitor is visible only while the user explicitly enables a visual source; blocked/unidentified foreground windows fail closed. The uploaded task PDF contains detailed Tasks 1–2, not a separate Task 3 specification; implementation follows the previously agreed Gemini Live + visual companion scope.

## ToolAgent desktop safety and discovery — handoff (2026-11-24)
- Keyboard shortcuts now use explicit allowlists: Ctrl+Shift permits navigation/selection only; Alt permits navigation/switching only. Alt+letter and Ctrl+Shift+letter combinations (including Q/W) are denied. Existing Win shortcuts and plain keys are unchanged.
- ToolAgent holds the opening sentence while checking for an unsupported access-denial claim, then streams normally. When an opening denial is detected, the remaining text stays buffered until the retry decision; a full-local-catalog retry discards it. If the call fails or no retry is eligible, buffered partial text is preserved.
- windows_control_info now returns a compact paginated index by default. Use its exact `name` argument for full purpose, parameters, permission, backend and confirmation gate. Invalid offset/limit/recent values fall back safely instead of raising.
- Added regression tests for the narrowed shortcut policy, denial-output buffering and inventory parsing/details.
- Validation in this source-only environment: changes and diffs inspected; Python imports and unittest execution have not been run.

## DeepSeek Reverse API hardening — handoff (2026-11-24)
- Fixes the two session-store test failures by replacing the fake `encrypted:` prefix with a reversible base64 test cipher; the assertions now verify that cookie/session values are not visible in the persisted test file.
- Transport streaming keeps a 512-character mutable tail uncommitted and emits only text confirmed by the common prefix of successive DOM snapshots. This prevents replaying the full cumulative answer after trailing Markdown/code-block re-renders; edits to already committed text cannot be represented by the current append-only transport contract.
- If a response has started before the Route deadline, the transport flushes the available partial answer and returns normally rather than raising a timeout after already yielding content (which could trigger router failover and duplicate output).
- Completion checks accessible English/Persian Stop controls and composer disabled state; when the site exposes no detectable Stop control, it waits for a 5-second idle interval rather than treating a 750 ms pause as completion.
- After a response, refreshed Playwright cookies and local storage plus current-origin sessionStorage are re-encrypted and persisted. Other origins' sessionStorage entries are retained.
- `_cancel` is not cleared at stream entry. A cancellation set immediately before stream startup remains observable; the flag is cleared only during final cleanup.
- Files changed: `kira/reverse_api/deepseek_transport.py`, `tests/test_deepseek_session.py`, `tests/test_deepseek_transport.py`, and repository-level changelog/architecture/context handoffs.
- Validation: source and test changes were inspected through GitHub. Python tests, browser automation against the live DeepSeek site, token-rotation behavior, and Windows runtime remain unverified; no GitHub Actions were run.

- Release metadata: `VERSION=1.2.1`; `kira/build_info.py` stamped for 2026-11-24 12:03 Asia/Tehran with the detected developer `ChatGPT`; the matching `1.2.1` Changelog entry is present.


## ToolAgent import crash — handoff (2026-11-24)
- Fixed the missing closing parenthesis in `_ACCESS_DENIAL_RX` in `kira/tools/agent.py`. The outer non-capturing regex group now closes correctly, preventing `re.PatternError` during module import.
- Added `tests/test_tool_agent_import.py`, which imports `kira.tools.agent` inside the test body and asserts the `ToolAgent` class is exported. Because the import happens during test execution (not module collection), a regression becomes a normal focused test failure.
- The critical import-crash fix was followed by the 1.2.3 ToolAgent safety/discovery update below, which completes the shortcut policy, streamed denial buffering and info_text validation/compact catalog items.
- Version metadata: `1.2.2`, build stamp `2026-11-24 12:07` Asia/Tehran, developer `ChatGPT`.
- Validation: corrected regex compilation was checked with Python's `re` module. Full package import, repository test and Windows/PySide6 runtime have not been executed in this environment.

## Emotion expansion (2026-11-27 04:50 Iran time)
- New user states: bored, achievement, hurt, gaming (mood.py regexes, runtime USER_EFFECTS, parser tags, director hint).
- 14 formerly trigger-less emotions now reachable locally: side effects of praise/flirt/thanks, FEEDBACK_EMOTIONS, absence ladder (45m bored, 6h lonely/affectionate, 24h nostalgic). `disgusted` stays model-tag only.
- Up to 3 blended emotions in on_reply (runtime + legacy); avatar still shows 2.
- New event vision_unclear fired when the detail retry fails.
- Fix: model-read signals no longer double-count familiarity.
- Tests: tests/test_emotion_expansion.py. Known pre-existing failures: test_emotion_director streamed tag, test_emotional_runtime topic query, test_vision_pipeline OCR.
