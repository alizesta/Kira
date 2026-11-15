# Ai1 Architecture

## Product identity
Ai1 is the application. Kira, Mika and Ren are character profiles within Ai1.

## Character specialties and portraits
- `kira/characters.py` defines Kira (coding/software), Mika (medical information) and Ren (news/intelligence) as prompt/presentation profiles.
- All characters use the same model routes, tools, computer access and safety permissions. Specialty prompts do not grant capabilities.
- Medical guidance is informational, not diagnosis or prescribing. Each profile has its own saved conversation and long-term memory (see 'Character chat sessions'); Mika's prompt requests careful handling.
- Current-events analysis should use available research tools, validate dates and independent sources, and disclose uncertainty.
- Kira's original profile portrait is `assets/characters/kira.svg`; keep this original SVG as her active portrait. Ren and Mika use separate generated JPEG text assets in `assets/characters/*.jpg.b64`, decoded by `MainWindow.refresh_character_card()`.

## VRM avatar
- `kira/vrm_avatar.py` `KiraAvatar` (stack of the PNG `AvatarView` and a Qt WebEngine `VrmView`) replaces `AvatarView` in the chat card and companion. The VRM page (`assets/vrm/viewer.html`) only renders; all state (blink, mouth level, emotion members, look) comes from `EmotionFaceAnimator`. Fallback to the PNG avatar is automatic. See CHANGELOG 2026-11-12.

## Release packaging
- `.gitattributes` enforces CRLF working-tree line endings for Windows `.bat` scripts.
- The ZIP builder independently normalizes batch-file line endings to CRLF, regardless of source checkout line endings.
- `tests/test_release.py` validates optional `psutil` and the batch-line-ending normalization helper.
- `scripts/build_metadata.py` stamps `kira/build_info.py` (build date `YYYY-MM-DD`, time `HH:MM`, auto-detected developer) and validates version/date/time/developer plus the `CHANGELOG.md` entry; `scripts/build_release.py` calls it before packaging and CI runs it with `--check`, so incomplete metadata blocks the release. The About rows are rendered from `kira/about.py`; rule: `PROJECT_CONTEXT.md` → "Version metadata and developer attribution".

## Game Mode profiles

- `story`: manual opt-in for offline/story games. Enables the existing game-window Vision sampling and local WASAPI loopback speech analysis. Existing desktop tools, including explicitly requested keyboard/mouse/UI control, remain available for offline play.
- `competitive_safe`: manual opt-in and fail-closed default for online/PvP or unknown games. Disables game-window capture, Vision attachment creation, system/game audio loopback, foreground-process polling, and local desktop/app/file/MCP/agent tools. Ordinary chat, web tools, the user's own microphone and local wake-word interaction remain available.
- Profile permissions are centralized in `kira/game_mode_policy.py`; unknown profile values resolve to the restrictive capability set.
- The Game Mode toolbar menu exposes Story Mode, Competitive Safe and Off. Detection only recommends a profile; it never chooses or enables one.
- A central `ToolRegistry.execution_guard` enforces Competitive Safe restrictions for direct tool calls, confirmation flows and planned Agent tasks. The foreground-game polling timer is also stopped while this profile is active.
- Competitive Safe blocks gameplay input and local desktop-control tools. Both profiles prohibit overlays, game-process memory access, code injection, graphics API hooks, game-file modification and game-driver installation. Competitive Safe reduces interaction but cannot guarantee that every anti-cheat permits Ai1 to run.

## Game Mode and Vision

### Components
- `kira/game_mode.py` owns foreground-window/process inspection and game-window capture.
- `GameModeMonitor.poll()` emits a detection signal once per process ID during the current application session. Detection never changes the manual enabled state.
- `MainWindow` owns the visible Game Mode toggle and the suggestion message.
- The manual toggle starts off on every launch; no persisted preference can silently enable capture. Capture interval and JPEG quality are centralized as `CAPTURE_INTERVAL_MS` and `CAPTURE_JPEG_QUALITY` constants in `kira/game_mode.py`.
- `capture_last_game()` returns a window pixmap only while the monitor's enabled flag is true.
- While Game Mode is enabled, a 1,000 ms Qt timer samples the detected game window. `GameModeMonitor` downsizes each captured frame to fit within 854×480 while preserving aspect ratio. MainWindow retains only the newest frame in memory and encodes it as JPEG (quality 68) when a user sends a message. The existing attachment composer and HybridRouter image payload path carry only that latest frame; no continuous background upload occurs.
- Turning Game Mode off stops the capture timer immediately, clears the cached frame, and ensures the next message is sent without a game frame.

### Game audio and quiet companion behavior
- `kira/game_audio.py` captures the default Windows WASAPI output device using `PyAudioWPatch` WASAPI loopback devices. It listens to the combined game/system output, segments speech with the existing VAD, and transcribes speech locally through `faster-whisper`.
- Game audio is not written to disk and is not sent to cloud STT. If local faster-whisper is unavailable or WASAPI loopback cannot open, Game Mode remains active for Vision and shows a clear audio error.
- A local keyword filter suppresses ordinary game dialogue. Only selected urgent, mission-completion and combat phrases can trigger a short spoken alert; per-category cooldowns suppress repetition.
- Enabling Game Mode temporarily enables the microphone and existing wake-word mode. The microphone is used for the user's wake phrase and commands; while Kira is asleep, unrelated speech is ignored. The previous mic/wake toggle states are restored when Game Mode is disabled.
- The loopback listener stops on Game Mode shutdown and application exit.

### Detection limits
- Detection is based on the foreground process executable, window title and window dimensions. Known desktop apps and launchers are excluded.
- A game is suggested when its process/title resembles a game or its foreground window is sufficiently large.
- This is a heuristic, not a complete game catalogue. Some games may be missed and some immersive non-game applications may be suggested.
- A suggestion is informational; the user must click the Game Mode toggle manually.
- Only the last detected game window is captured. If the window closes, capture returns no frame.

### Vision model compatibility
The existing provider-neutral image pipeline sends image attachments to the selected Route. Ai1 does not yet automatically classify every provider/model as vision-capable or reroute around text-only models. Users should select a vision-capable model in Route Manager for Game Mode image questions. A text-only model may reject the image request.

## Cloud Voice
Cloud Voice is independent of chat model routing. It maintains its own provider order, API keys, enabled flags, selected models, voice IDs and cooldown state.

### Request flow
1. `Speaker` receives text and splits the response into complete sentences.
2. `CloudVoice` checks the configured TTS provider order and available keys.
3. A provider synthesizes audio for the current sentence.
4. The audio is passed back to the existing playback pipeline.
5. On quota/rate/auth failures, the affected key is cooled down and the next eligible key/provider is tried.
6. If cloud synthesis fails, the existing Edge TTS and Windows voice fallbacks remain available.

### MiniMax Global
- Base URL: `https://api.minimax.io/v1`
- HTTP endpoint: `POST /t2a_v2`
- Authentication: `Authorization: Bearer <API_KEY>`
- Models: `speech-2.8-turbo`, `speech-2.8-hd`
- Output: MP3, hex-encoded in the JSON response
- MiniMax is TTS-only. It does not register an STT model.
- API key validation performs a short real synthesis request and consumes a small amount of TTS quota.
- API key persistence reuses CloudVoiceStore and Windows DPAPI protection.

## Shared storage
Cloud Voice settings are written atomically outside the application installation directory.


## Ai1 Code mode (inside Kira's chat)

- **Agent** (`kira/auto_agent.py::AutoAgent`): decision loop. Context includes project brief, tree, static Python AST map and `.ai1/PROJECT_MEMORY.md` when present. A separate planner call uses the `deep` role route; execution uses `surface`; review uses `reflection`. Routes fall back through the normal Route Manager if a role route is not configured or unavailable. Edits run Ruff (or Pyflakes if installed) immediately; Python syntax and JSON are also parsed. A changed task must pass a check and receive a clean independent review before `finish` is accepted.
- **Tools** (methods `tool_*`; paths remain inside the working copy): `plan`, `list`, `map` (AST imports / classes / functions), `read`, `search`, `write`, `replace`, `delete`, `run`, `shell`, `diff`, `git status|diff` (snapshot-based, no Git metadata or writes), `lint`, `review`, and `memory` (updates `.ai1/PROJECT_MEMORY.md`). File writes still preserve CRLF. `run` permits only Python tests / syntax commands and Ruff/Pyflakes; arbitrary PowerShell still requires approval for every command, and deleting a folder requires approval.
- **Runner** (`_exec`, `_zip`, `copy_project`, `snapshot`): processes run with `Popen`, merged output, 120 s limit, killed immediately on Stop, environment stripped of key/token/secret/password variables, logs shown in the chat. Delivery: zip of the working copy (runtime folders, caches, secrets excluded) + `AI1CODE_REPORT.md`, `testzip()` integrity check, name `<Project>_YYYY-MM-DD_HH-MM_IRST.zip` (fixed UTC+03:30; Iran has no DST), stored in `DATA_DIR/ai1code_output`.

Safety model: the agent edits a COPY (`tempfile`, removed afterwards); the selected project is the restore point and is never written. Changes are tracked by SHA-1 snapshots before / after (modified, created, deleted). If the original changes on disk while the agent runs, the report lists those files. Read-only mode (questions) runs the discovery tools on the project itself with no write / run / shell tools.

UI side (`kira/chat_code_ui.py::CodeChat`, `kira/chat_code.py`):
- Entry point: none visible. `CodeChat` (created in `MainWindow.build_chat_tab`) has no button, menu entry or window (`kira/code_workspace.py` and the `</>` button were removed); Kira's tab understands coding requests from the wording.
- `MainWindow.submit()` offers each plain-text message of Kira's tab to `CodeChat.handle(text, voice)` after the busy-queue check (typed and spoken text alike; attachments take the normal path). `chat_code.classify_intent` decides `(intent, sure)` from file references, tracebacks, project words, edit verbs, bug / feature words and the project's own vocabulary (`project_vocabulary`: file stems and folder names): `task` -> agent with start confirmation; `question` -> read-only agent; clearly casual or general programming talk -> returns False (normal chat). Ambiguous wording with a project selected goes to one short `_Job` classifier call (TASK / QUESTION / CHAT, temperature 0, 25 s timeout, any failure = CHAT); CHAT re-enters `submit` with a one-shot bypass flag, and messages typed meanwhile are queued in order. Without a project folder an ambiguous message is never guessed at; a clear coding request asks for the folder once (`ensure_project`, saved as `code_workspace_path`). Explicit overrides: `/auto`, `/patch`, `/ask`, `/run`, `/files`, `/project` ("change the project folder" in words works too), `/apply`, `/reject`, `/help`.
- The agent runs in a `_Job` thread; events (plan, steps, test logs) are posted to Kira's session via `MainWindow._as()`. Approval requests travel as a queued signal to the UI thread and the agent thread waits (Stop counts as "no"). Busy / Stop / pending queue reuse the normal session machinery; Stop sets `auto_stop` and kills a running process.
- The chat view is a `QTextBrowser` with `setOpenLinks(False)`; `MainWindow.on_chat_link` opens http(s)/mailto externally and routes `kira-code://apply|reject|open/<id>` to `CodeChat` (`open` only reveals folders of zips created in this session).
- Code answers are stored in Kira's chat history but never spoken. Diff bubbles are not restored after a restart.

### One-file Diff flow (`/patch @file ...`)
- Kept from the first version: `KiraCodeEngine` (no-tools prompt) proposes the full replacement between markers, shown as a coloured Diff with approve / reject links; apply re-confirms, compares disk bytes with the snapshot (stale -> abort), keeps `.ai1code.bak`, writes atomically. Not requested for files above the context budget, non-UTF-8 or containing secrets.

### Known limits
- Git-style status/diff compare against the mission-start snapshot; branch, commit, push and true repository status operations are not implemented. There is no automatic copy-back into the original project (the person takes the zip); a mission does not survive an app restart; `shell` is not sandboxed (that is why it asks every time). Project memory persists in the delivered ZIP and is available to later missions when that ZIP is used as the project.


## Game detector self-exclusion
- `GameModeMonitor.poll()` rejects the current process ID before any game-name/title heuristics or large-window checks. This prevents Ai1's own full-size window (for example, `Project Kira 1 stable`) from being suggested as a game.


## Native function calling
- Tool.json_schema() is the single schema source. HybridRouter.chat_with_tools() selects an eligible route and invokes native calls only when its adapter exposes that capability.
- The OpenAI-compatible adapter sends tools with tool_choice=auto, parses structured tool_calls, and preserves assistant/tool messages in the next request. Google AI Studio uses Google's OpenAI-compatible endpoint, so Gemini routes use this adapter.
- Ollama uses `/api/chat` with native `tools` definitions and maps assistant tool-call/tool-result messages to Ollama's message shape. A model that explicitly rejects tools reports native support as unavailable so the router can use another native route or fall back to the text protocol.
- ToolAgent executes the structured call through the existing registry. Validation, access manager, one-shot confirmation grants, per-turn de-duplication, and Competitive Safe guard are unchanged and remain authoritative.
- Cloudflare and routes without native support return to the existing text protocol. Tool-call rounds are non-streaming; final user-facing text remains streamed.

- Pure foreground identity filtering lives in kira/game_detection.py and is covered by the portable tests.test_game_detection module; GameModeMonitor delegates current-PID and known Ai1/Kira title checks to it.


## Game Mode CI matrix
- Portable title/PID identity tests run in the Linux release job.
- The Windows release gate runs `tests.test_game_detection` and `tests.test_game_mode` on `windows-latest` with `QT_QPA_PLATFORM=offscreen` before ZIP packaging.
- The Windows job exercises the monitor's Qt integration with mocked foreground-window data. It cannot verify the user's real Ai1 window title, DPI/display setup, or foreground process state; those still require an interactive Windows 11 smoke test.

- The Windows test fixture creates a QApplication even in offscreen mode because the generic large-window heuristic queries QApplication.primaryScreen().

- The Ollama native message round-trip test builds the serialized assistant arguments with `json.dumps`, then verifies the adapter restores the structured object in the outgoing Ollama request.


## Model Discovery / Route Manager validation
- Discovery is provider-family based: official Google model listing with pagination, OpenAI-compatible `/models`, Cloudflare model search, and Ollama's local `/api/tags` scan.
- The API Manager registry is metadata-only and never stores API keys. Refresh marks vanished models unavailable while preserving existing Routes; newly listed models are visible but not automatically enabled.
- Gemini's listing endpoint does not report all runtime capabilities. Tool Calling / Vision remain Unknown unless the provider explicitly reports them; actual request success is still the runtime authority.
- UI discovery runs in TaskWorker and updates the API Details table after completion. Tests now cover Gemini pagination and the Route Manager's refresh/model-toggle wiring.


## User-data migration and backup coverage
- `storage.has_user_data` recognizes settings, chat SQLite, evidence SQLite, persona-memory JSON, Cloud Voice settings and the Hugging Face / voice / runtime cache folders.
- `migrate_legacy` copies each missing file independently, preserving destination files and leaving legacy sources untouched. On the standard A: destination it carries forward the previous AppData data and model caches without deleting the originals.
- `backup_user_data` copies persona JSON and Cloud Voice JSON, and uses SQLite's online backup API for both chat and evidence databases.
- Windows stores persistent Kira data and AI caches in `A:\\Project KIRA\\Kira Attachments`. If that location is absent or not writable, it falls back to `%LOCALAPPDATA%\\Kira`. `KIRA_DATA_DIR` remains an explicit override for portable/test setups.

- The release workflow file itself is included in its path filters; workflow and permission changes therefore trigger validation.

- The release workflow has one top-level `permissions: contents: write` declaration, required by the GitHub Release action. Avoid duplicate YAML permission keys.


## Character-scoped long-term memory
- `persona_memory.character_scope(id)` uses a context-local character ID so concurrent execution contexts do not accidentally write to another profile's memory.
- Kira keeps the legacy `kira_persona_memory.json`; other profiles use `kira_persona_memory_<id>.json`. The external user-data directory and migration/backup logic cover all these files.
- Kira alone uses the evidence-backed SQLite fact index. Ren/Mika facts, voice samples, moments, habits and summaries are stored in their own JSON files and never query Kira's evidence index.
- The Memory dialog is bound to the active character. Short-term SQLite chat history remains shared; this change isolates long-term persona memory only.

- The storage layer discovers every `kira_persona_memory*.json` file for migration and rolling backups, so the newly separated Ren/Mika memory stores survive data-folder migration and recovery.

- The old SQLite chat schema has no character ID, so Ren/Mika must not digest its older rows or run per-profile summaries against the global chat. Kira alone retains the legacy history digest. Clearing the shared chat resets voice/digest state for all profiles while preserving their facts/moments/habits.
- The pre-existing Kira evidence index may include unattributed facts backfilled from shared historical chat. New Ren/Mika messages are excluded; no historical attribution is invented.


## Character chat sessions
- `kira/chat_sessions.py` (Qt-free): `ChatSession` holds everything one conversation needs (busy, worker, pending queue, stream text/position, turn state, router, view, timer, badge, draft, unread). `session_property` makes MainWindow's old attribute names (`busy`, `worker`, `_stream_text`, ...) read/write the *current* session; `front_only_property` exposes one-per-computer objects (speaker, director, animator, bubble, status line, stop/send buttons, input, voice button) normally for the front session and as `NOOP`/`Muted` stand-ins for background sessions (director keeps `parse_reply/format_hint/library`).
- `MainWindow._as(session)` runs a handler as that session (sets `cur` and temporarily `settings['active_character_id']`). Worker/timer/search signals reach the GUI thread through one `SessionRelay(QObject)` per session, which calls the normal handlers inside `_as`. `front` is the visible tab; `switch_session(cid)` changes it (theme, art, badge, draft, stop-button state), `sync_sessions()` creates/removes tabs after add/delete character.
- Storage: `kira/memory.py` `messages.character_id`; all reads/writes/clears accept `character_id`; `read_rows_full/_merge/_write_all` carry a 4-tuple (role, content, created_at, character_id).
- Theme: `kira/theme.py` `CHARACTER_THEMES`, `character_theme`, `character_style(theme, effect)`; `chat_render.message_html(..., accent=)`.
- Shared on purpose: ToolAgent, EmotionDirector/animator (front only), Speaker (front only), route health/cooldowns (`states`, `cooldowns` dicts shared by the per-session routers), settings.
- Tests: `tests/test_character_chats.py` (storage, session helpers, themes; GUI cases run only where PySide6 exists).
