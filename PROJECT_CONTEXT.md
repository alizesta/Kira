# Ai1 Project Context

## Product identity
- **Ai1** is the desktop application and product name.
- **Kira**, Mika and Ren are selectable companion characters inside Ai1; Kira is not the application name.
- Kira specializes in coding and software development; Mika specializes in safe medical information and health education; Ren specializes in current news, fact-checking and intelligence analysis. Their specialties shape prompts and presentation only; shared routes, tools and permissions remain common.
- Game Mode is a manually enabled gameplay feature. Game detection may suggest it, but must never enable it automatically.

## Release packaging safeguards
- Git checkout uses `.gitattributes` with `*.bat text eol=crlf`; Windows batch files must remain ASCII and CRLF in working trees.
- `scripts/build_release.py` independently normalizes all `.bat` bytes to CRLF when writing the ZIP, so package correctness does not depend on the build host's checkout settings.
- Release tests include optional `psutil` and must not treat its intentional presence as an unexpected dependency.
- Streaming tests must respect LeakGuard's 48-character undecided preamble buffer: short normal answers are released at stream completion, while short fragments are not promised to display before the guard can classify them.

## Startup performance boundaries (2026-11-23)
The desktop startup path is intentionally chat-first. `kira/ui/bootstrap.py` must not import or construct ToolAgent eagerly; it receives a `LazyToolAgent` facade and realizes the concrete agent/tool registry only when the chat/tool path first needs it. Passive cancel/release operations must not realize an unused agent. Explicit task-history clearing may realize it because it must clear durable task state.

The tool protocol imports the standalone provider-neutral `kira/think_filter.py`, not `kira/hybrid_ai.py`. Settings tabs keep stable indexes with lightweight placeholders and build their actual page on first navigation. Piper warm-up, Windows MusicWatcher, and provider model-catalog refresh are optional work and must not block initial chat display; provider refresh begins on first visit to the AI/Provider page. App-catalog warm-up is triggered by app-tool execution, and MCP setup by explicit MCP/agent intent.

These are implementation boundaries for the Task 1 startup optimization. They do not assert a measured startup-time or memory improvement until Windows measurements are recorded in `logs/startup-performance.jsonl`.

## Tool schema scope boundaries (2026-11-23)
Tool exposure is distinct from runtime permission. In `tools_mode=auto`, `ToolPlan.categories` remains the full set used for availability/security policy, while `ToolPlan.schema_categories` controls which tool schemas and text catalog are shown to the model for the current turn. The selected scope is derived from detected request topics and includes every registered tool tagged with at least one selected category. Mixed-category requests retain all detected groups; `tools_mode=always` retains the full catalog.

Unclassified wording must stay on the compact capability-index triage path, including when the active provider supports native function calling. Only an explicit `use_tools` escalation expands the scope to the local tool catalog. MCP and independent-agent schemas remain opt-in. An empty selected scope means no tools, never “all tools”. ToolAgent enforces the current per-session schema scope again before registry dispatch, so a model-supplied hidden function name is denied before its handler runs. Competitive Safe intersects both the runtime allowance and model-visible scope with its web-only policy.

This is a source-level implementation contract; schema counts, provider token usage, request latency and full regression behavior remain unverified until the focused tests and Windows/provider acceptance are executed.

## Version metadata and developer attribution (mandatory)
This rule binds every developer and every AI agent (Codex, OpenCode, Claude Code, ChatGPT) that changes this repository.

- **About section.** Settings → General shows an About group with four rows: Version, Build Date, Build Time and Developer. No About values are typed by hand.
- **Formats.** Build Date is Gregorian `YYYY-MM-DD`; Build Time is 24-hour `HH:MM` (Asia/Tehran build time); Developer is exactly one of `Codex`, `OpenCode`, `Claude Code`, `ChatGPT`.
- **Single sources.** The version lives only in `VERSION` (`kira/config.py`). The build stamp lives only in `kira/build_info.py`, a generated file (never edit it by hand); `kira/about.py` reads it for the About rows.
- **Automatic developer detection.** `scripts/build_metadata.py` resolves the developer in this order: explicit `KIRA_DEVELOPER` override → build-host markers (`CLAUDECODE`/`CLAUDE_CODE_ENTRYPOINT`, `CODEX_SANDBOX`/`CODEX_HOME`, `OPENCODE`/`OPENCODE_SESSION_ID`, `AI_AGENT`, `AGENT`) → previously recorded `kira/build_info.py` → git author/committer name. An unknown or unresolvable value is an error, not a default.
- **Changelog coupling.** In addition to updating `CHANGELOG.md` / release notes, every change updates the version and authors the build metadata. The release check requires the current `VERSION` string to appear in `CHANGELOG.md`.
- **Build/release gate.** `scripts/build_metadata.py` re-stamps `kira/build_info.py` and validates version, date, time, developer and the changelog. `scripts/build_release.py` runs `ensure_release_metadata()` before packaging, and CI runs `python scripts/build_metadata.py --check`. Any missing or malformed field stops the release with a non-zero exit code.
- **How to work.** Bump `VERSION` when the release changes, add the matching `CHANGELOG.md` entry, run `python scripts/build_metadata.py --check` (and let the build stamp the file), and add regression tests for behaviour you change.

## Purpose
Ai1 is a Windows desktop anime-style digital companion. It combines local and cloud chat models, persistent memory, character profiles, speech input/output, controlled desktop tools, and optional game-screen understanding.

## Character profiles
- Kira's original profile portrait is `assets/characters/kira_portrait.png` (2D portrait cropped from her art; replaced the old kira.svg on 2026-11-21). Ren and Mika have portraits (`assets/characters/ren_portrait.jpg`, `mika_portrait.jpg`, 784x1168) and full-body pictures (`ren_full.jpg`, `mika_full.jpg`, 720x1280) supplied by the user; profile field `image` = portrait, `avatar` = full-body picture.
- The chat page avatar card and the floating companion always show the ACTIVE character: Kira = her animated PNG (`assets/kira_character.png`, with eyelid/mouth overlays), Ren/Mika = their full-body picture driven by the same soft-body rig at reduced strength (`FaceAnimator.set_character_art`, geometry in `kira/avatar_art.py`). Face overlays (blink, mouth) are measured on Kira's face and are therefore off for other characters until their own landmarks/layers exist. A profile without an `avatar` file (custom characters) keeps Kira's animated art.
- Kira: coding, architecture, debugging and technical support; use Ai1 Code for project-file workflows and never claim unperformed tests.
- Mika: medical information and health education only, not diagnosis or independent prescribing; flag emergencies and preserve health-data privacy.
- Ren: current news and intelligence analysis; verify dates and independent sources, distinguish facts from claims/opinion, and disclose unavailable live verification.
- All three share the same Route Manager, model intelligence, tools, computer permissions and safety policy. Each has its OWN saved conversation (chat tab) and long-term memory. Specialty is not an access-control boundary. Mika's prompt requests careful handling, but profile-level medical-memory isolation is not implemented.

## Current platform
- Windows 11
- Python / PySide6 desktop application
- Local chat through Ollama
- Cloud chat through the Route Manager
- Speech input/output use local Qwen3-ASR, faster-whisper fallback and Piper; Chat Route providers are not used for audio

## Game Mode
- Game Mode has two manually selected profiles: Story Mode and Competitive Safe.
- Story Mode is intended for offline/story games and permits the existing game-window Vision sampling plus local-only WASAPI game/system audio speech analysis.
- Competitive Safe is the default/fail-closed profile for online/PvP and unknown games. It disables game-window capture, Vision attachments, system/game loopback audio, foreground-process polling, and local desktop/app/file/MCP/agent control tools; it retains ordinary chat, independent microphone/wake-word interaction and web tools.
- Game detection is advisory only. It cannot reliably infer online/offline/PvP status from process metadata, so it recommends the conservative profile and never selects or enables one automatically.
- Story Mode keeps the existing user-requested desktop controls available for offline play. Competitive Safe blocks those controls. Both profiles prohibit overlays, game-process memory access, code injection, graphics hooks, game-file modification and game-driver installation.
- Switching from Story Mode to Competitive Safe immediately stops capture/audio listeners and clears the cached frame. Disabling Game Mode stops all game capture/audio and restores the previous microphone/wake settings.
- The foreground-game detector is advisory only and polls the foreground Windows process/window.
- A game process receives one suggestion per process ID during the current Ai1 session.
- Game Mode starts disabled on every application launch and is enabled only by the user's explicit toggle.
- Screen capture is prohibited while Game Mode is off. The capture timer runs only while the user has manually enabled Game Mode and is stopped immediately when disabled.
- While enabled, the most recently detected game window is sampled once per second. Frames are downscaled to fit within 854×480 (aspect ratio preserved) and held in memory; only the newest JPEG frame is attached when the user sends a chat message. No frames are uploaded continuously.
- While Game Mode is active, the default Windows WASAPI output through PyAudioWPatch (game + system audio) is listened to in memory. Speech segments are transcribed with local faster-whisper only; game audio is not sent to cloud STT and is not saved to disk. A conservative keyword filter keeps ordinary dialogue silent and allows only selected critical/mission/combat alerts.
- Game Mode temporarily enables the existing microphone wake-word listener. Kira stays asleep until the user says her wake name; unrelated microphone speech is ignored. Previous microphone/wake settings are restored when Game Mode is turned off.
- Disabling Game Mode immediately stops image and audio capture and restores the previous microphone/wake state. It does not terminate the game or change its settings.
- Detection uses process/window metadata and a conservative title/process/fullscreen heuristic; it is not guaranteed to identify every game.
- Vision requests require a vision-capable model on the selected Route. Text-only models may reject image payloads; the existing provider error path explains this limitation.

## Voice architecture
- `kira/listener.py`: microphone capture, segmentation, local Qwen3-ASR recognition and local faster-whisper fallback.
- `kira/vad.py`: room calibration, speech segmentation, pause merging and barge-in detection.
- `kira/local_voice.py`: local Qwen3-ASR loading/transcription and Piper TTS synthesis/warmup.
- `kira/voice.py`: sentence queue, local Piper WAV generation/cache, Qt playback and lip-sync envelope.
- `kira/game_audio.py`: Windows WASAPI loopback capture and local-only game speech transcription/important-event filtering.
- Speech recognition and synthesis never use Cloud Voice, Edge TTS, Windows SAPI or Google Speech Recognition. Cloud API providers remain available for chat text only.
- A legacy `cloud_voice.json`, if present from an older release, is preserved with user data for safety but is not read or used by the active application.

## Active work
Local-only speech stack: Qwen3-ASR primary STT, faster-whisper local fallback, Piper local TTS. Do not reintroduce remote speech recognition or synthesis fallbacks.

## Working rules
- Never introduce remote voice fallback; STT and TTS must remain local. Cloud providers are for text chat only.
- Never log or display full API keys.
- Keep provider settings and keys outside the application folder.
- Add regression tests for provider-specific behavior and safety-sensitive capture behavior.
- Do not claim real-time streaming unless audio chunks are actually played before synthesis completes.
- Every completed project change should produce a timestamped `ProjectKira_YYMMDD_HHMM.zip` release when CI succeeds.
- **Mandatory version metadata:** every change must keep `VERSION` (`kira/config.py`), the generated build stamp (`kira/build_info.py`) and `CHANGELOG.md` in sync. The developer is auto-detected (Codex / OpenCode / Claude Code / ChatGPT), never typed by hand. Incomplete metadata stops the build and release. See "Version metadata and developer attribution" below and `docs/VERSION_METADATA_FA.md`.


## Ai1 Code
- Ai1 Code is part of Kira's own chat (no button, no menu entry; not in Ren/Mika's chats): she recognises coding requests from conversation. Kira answers code questions as herself; the shared Code Agent rules (no tools, no file access of its own) still apply and her specialty does not grant extra permissions.
- Kira's coding side (no button; she understands coding requests from conversation) is an autonomous coding agent (`kira/auto_agent.py`): plain-language missions, self-directed file discovery, planning, multi-file edits on a copy, test/fix loop, PowerShell only with per-command approval, and a verified timestamped zip delivered in the chat. Questions are answered by a read-only investigation. The old separate workspace window (file tree + editor) was removed; `/patch @file` keeps the one-file Diff flow.
- Code Agent uses the chat session's own HybridRouter but owns a separate prompt/worker lifecycle. It has no Tool Registry access, filesystem write access, or shell execution.
- Project context is bounded and excludes secret/configuration files, virtual environments, build output, dependency folders, databases and key material. Only the selected text file content is sent alongside a bounded file listing.
- Ai1 Code auto mode now builds a bounded Python AST map, runs Ruff/Pyflakes after Python edits, shows snapshot-based diffs/status, performs a separate review call before finishing, and carries durable notes in `.ai1/PROJECT_MEMORY.md` inside the delivered ZIP. Planning, execution and review use the configured `deep`, `surface` and `reflection` route roles with normal fallback. It can write focused tests as ordinary project files and run the approved Python check commands. Git branch/commit/push and automatic copy-back are still not implemented.


## Ai1 Code phase 2
- Code Agent can propose a complete replacement for the currently selected text file.
- Proposed content is parsed only when the explicit Ai1 markers are present and the result is non-empty and within the file-size limit.
- Patch proposals are blocked when the selected context contains redacted secrets, preventing masked credentials from being written back over real values.
- The chat shows a unified Diff with approve / reject links. No file is written until the user explicitly approves the change.
- Before applying, the on-disk bytes are compared with the snapshot taken at proposal time; stale proposals are rejected. Files over the context budget are analysis-only.
- Approved changes use the existing one-time `.ai1code.bak` backup and an atomic temporary-file replacement.
- This phase does not add multi-file patches, automatic test execution, a debugger, or Git controls. GUI/PowerShell runtime still requires validation on Windows 11.


## Game detector self-exclusion
- The foreground detector must ignore Ai1's own process ID before applying title hints or large-window heuristics. Ai1's main/companion windows share the same process and must never trigger a game suggestion.


## Native Function Calling (2026-11-11)
- Native function calling is available through OpenAI-compatible routes, including Google AI Studio/Gemini, Groq, Mistral, OpenRouter and configured OpenAI-compatible endpoints.
- Ollama uses its native `/api/chat` tools schema when the selected local model supports tool calling. Models that explicitly reject tools are treated as unsupported and return to the existing text-protocol path.
- Tool schemas are generated from the existing ToolRegistry. All calls still pass through the same argument validation, permission checks, explicit confirmation flow, duplicate-call cache and Game Mode execution guard.
- Cloudflare and any provider/model without a compatible native adapter retain the existing text-protocol fallback. Native support is capability-based, not assumed from a provider name.
- Native tool request rounds are non-streaming; ordinary final answers continue through the existing streamed chat path.

- The Ai1/Kira foreground-window identity check is isolated in kira/game_detection.py and covered by portable tests/test_game_detection.py, so title/PID exclusion logic is tested without importing the Windows/PySide6 monitor.


## Game Mode Windows CI validation
- The release workflow runs `tests.test_game_detection` and `tests.test_game_mode` on `windows-latest` with PySide6 and Qt's offscreen platform before the packaging/release job can start.
- Linux portable coverage remains in place. This CI validates mocked foreground PID/title integration and safety behavior; it does not replace a real interactive Windows 11 test with the user's actual desktop/window title.

- The Windows Game Mode test fixture initializes QApplication before exercising the monitor's large-window heuristic; CI runs the Qt integration offscreen.

- Native Ollama regression tests use JSON serialization for assistant tool-call arguments so the multi-round message fixture remains valid Python and verifies the actual JSON object sent to Ollama.


## Stage 3: Model Discovery and Route Manager verification
- Automatic model discovery is already implemented for Google Gemini, Groq, Mistral, OpenRouter, Cloudflare and generic OpenAI-compatible providers. Ollama has its separate local installed-model scan.
- Google uses the official `/v1beta/models` endpoint with API key in the header and pagination; only chat-capable Gemini models are retained. Gemini capability values not explicitly reported by the listing API remain Unknown.
- The Route UI runs discovery asynchronously, merges new/unavailable models into the registry without silently deleting routes, and creates/enables a Route only when the user selects a model (apart from the provider's selected default).
- Added regression coverage for multi-page Gemini discovery, filtering non-chat models, key handling, registration and Route Manager refresh/toggle wiring.


## Stage 4: User-memory durability
- Settings, chat history, persona memory JSON and evidence-backed SQLite memory live under the external user-data directory (Windows: `%LOCALAPPDATA%\\Kira`; `KIRA_DATA_DIR` is the test/override path).
- Legacy migration now copies persona memory and the evidence database as well as settings/chat and legacy Cloud Voice data for preservation only, without overwriting files already present in the destination or deleting the source. The active application does not read legacy Cloud Voice data.
- Rolling backups now include the persona memory JSON and evidence database. Added tests for data-directory resolution, legacy migration and backup coverage.

- The release workflow now includes its own YAML file in the push path filter, so changes to release gates and permissions are validated by a fresh run rather than silently skipping the job.

- Release workflow permission is declared once at the top level (`contents: write`); the duplicate declaration introduced during the first permission fix was removed after GitHub rejected the workflow before creating jobs.


## Stage 5: Character-specific long-term memory
- Kira retains the existing `kira_persona_memory.json` path for compatibility. Ren and Mika now use separate `kira_persona_memory_ren.json` and `kira_persona_memory_mika.json` stores in the same external data directory.
- Voice samples, extracted facts, moments, habits and summaries are scoped to the active character. The evidence-backed SQLite index remains Kira-only; Ren/Mika use their own local persona-memory facts and do not receive Kira's evidence retrieval.
- The Memory dialog reads/edits/forgets only the active character's long-term memory. Short-term chat history is now per character (see 'Character chat tabs').

- Character memory migration and rolling backup enumerate all `kira_persona_memory*.json` files, including Ren/Mika and future custom profiles. Existing destination files remain authoritative.

- Ren/Mika memory no longer digests shared legacy chat rows or summarizes the global chat database. Clearing the shared chat resets voice/digest samples for all profiles but preserves each profile's facts/moments/habits. The legacy Kira evidence index may contain unattributed pre-isolation facts because older chat rows have no character ID; new Ren/Mika messages are not added to it.


## Avatar (2026-11-21)
- Only the 2D avatar exists (`kira/face.py` `AvatarView`, also in the companion window). The VRM avatar, its viewer page and dance library were removed; `kira/body.py` is kept but has no body to move until a new live 2D avatar uses it.
- 2026-11-22 UI polish (branch `fix/ui-polish-personas-svg-audit`): settings pages centred and width-capped, 14 px scrollbars, Kira's chat card shows the whole body canvas, per-character composer prompts, SVG-only icons (all mood faces plus copy/pencil for message actions), Preferences switch for Appllama + UNSLOP, Voice tab mic/speaker cards reduced to volume, sensitivity and a record-and-play test (`kira/ui/pages/audio_card_simplify.py`). Runtime verification on Windows pending.

## Settings tabs (2026-11-21)
- Pages: Chat, Voice, Character, Appearance, General, Connections & Models (+ Runtime Log). There is no Assistant tab: identity/persona/modes/temperature live in Character -> personality sub-tab; the local Ollama model group lives in Connections & Models. `AssistantPage` only owns those widgets (hidden).

## Character chat tabs (per-character conversations)
- The chat page has a tab strip at the top: one tab per character (Kira, Ren, Mika, custom ones). Each tab is an independent conversation: own saved history, own chat view, own HybridRouter (own Stop flag; health/cooldown state is shared), own stream state, own pending-message queue. Several characters can generate answers at the same time.
- `messages.character_id` (default 'kira') stores ownership. Old databases are migrated by `ALTER TABLE`; every old row is Kira's. Backups, corruption recovery, snapshots and import keep the owner. `recent_messages/message_count/conversation_context/clear_memory(character_id=None)` — None = every chat (legacy). "Clear chat memory" clears only the visible character's chat.
- Only the tab in front speaks, moves the face/companion, shows the companion bubble and writes the status line / route chip. A background tab's answer is saved, shown in its own view and marked with ● (⏳ while answering). Voice input and the companion bubble send to the tab in front.
- Switching a tab sets `active_character_id`, the avatar art, the character page card and the chat colours. The Settings → Character list is the same switch.
- The chat page theme (`theme.character_theme/character_style`) keeps the glass look (translucent cards) and neon edge/glow but takes colours from the character: Kira violet/cyan, Ren crimson/green, Mika pink/cyan. Assistant bubbles use the character tint (`message_html(accent=...)`). A custom profile may set `theme_color` ("#rrggbb").
- Ren and Mika full-body pictures are transparent PNGs (`ren_full.png`, `mika_full.png`, background removed from the supplied JPGs, which are kept as originals). Mika's supplied picture is a three-quarter view, not a full standing figure. Kira's `kira_character.png` was already transparent.
- Known limits: the ToolAgent (task plans, confirmations, MCP) is still one shared instance; Stop on one tab only cancels the tool loop when no other tab is busy. A reply that finishes in a background tab is not spoken. Windows runtime of the tab UI is unverified (see TASK_HANDOFF).

## Chat-controlled 3D body (2026-11-12)
- `kira/body.py` is the single list of body commands (POSES / CLEARS / GESTURES) and the Persian/English phrase reader; `assets/vrm/viewer.html` implements them (`POSE` table, `window.kiraBody`). `tests/test_body.py` keeps both in step.
- Flow: user message -> `body.parse_user_command` (immediate) and/or model reply `[body:name]` tags (`ReplyMeta.body`) -> `MainWindow.run_body` (each name once per message) -> `animator.body` signal -> `VrmView._body` -> page. Only while Kira's VRM is ready and front (`animator.body_enabled`, `kira_art_active`) and setting `body_control` is true.
- Desktop pet: `kira/pet.py` (PetController: hang from cursor, fall, perch on windows/taskbar via `kira/perch.py`), `kira/music_dance.py` (loopback beat detection) -> `window.kiraMusic`. Settings `companion_perch`, `companion_hang`, `auto_dance`.
- Dance library: files `*.vrma` / Mixamo `*.fbx` in `assets/vrm/animations/` (see its README.txt) are listed by `kira/dance_library.py` and sent with `VrmView.refresh_dances` -> `window.kiraDances`. On music start `viewer.html` plays a random clip (75%) or a built-in procedural style (AnimationMixer, rotations only, speed follows BPM). FBX needs the optional `vrm_vendor.OPTIONAL` files. Character tab has buttons to open the folder and Mixamo.
- Left/right are the character's own sides. Held poses release by `reset`, a pose of the same group, or after `HOLD_S` (150 s).

- 2026-11-21 23:49 Iran: UI icons live in `assets/icons/*.svg` (Lucide, ISC) rendered with glow by `kira/ui_icons.py`; `stop` and mood faces remain code-drawn.

- 2026-11-22 03:03 Iran: UNSLOP leftovers done (self-sizing tables via fit_height, collapsed advanced switches in Character tab, scoped notes labels).

- 2026-11-22 03:20 Iran: audio playback = `_PcmPlayer` (QAudioSink, PCM wav only) in kira/voice.py; QMediaPlayer / QSoundEffect / winsound removed. Needs a listening test on Windows.

- 2026-11-22 03:26 Iran: speech engine is switchable (settings `tts_engine`: piper | kitten; Kitten English-only, Persian sentences always Piper). See kira/voice.py `_use_kitten` / `_synth_kitten`.

- 2026-11-22 03:37 Iran: Voice tab = mode card (realtime/local) + mic/output cards + collapsed advanced; setting `gemini_voice`.
