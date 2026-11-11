# Ai1 Architecture

## Product identity
Ai1 is the application. Kira, Mika and Ren are character profiles within Ai1.

## Character specialties and portraits
- `kira/characters.py` defines Kira (coding/software), Mika (medical information) and Ren (news/intelligence) as prompt/presentation profiles.
- All characters use the same model routes, tools, computer access and safety permissions. Specialty prompts do not grant capabilities.
- Medical guidance is informational, not diagnosis or prescribing. Current conversation history/memory is shared across profiles; Mika's prompt requests careful handling but does not enforce profile-level medical-data isolation.
- Current-events analysis should use available research tools, validate dates and independent sources, and disclose uncertainty.
- Kira's original profile portrait is `assets/characters/kira.svg`; keep this original SVG as her active portrait. Ren and Mika use separate generated JPEG text assets in `assets/characters/*.jpg.b64`, decoded by `MainWindow.refresh_character_card()`.

## Release packaging
- `.gitattributes` enforces CRLF working-tree line endings for Windows `.bat` scripts.
- The ZIP builder independently normalizes batch-file line endings to CRLF, regardless of source checkout line endings.
- `tests/test_release.py` validates optional `psutil` and the batch-line-ending normalization helper.

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


## Ai1 Code workspace

- Entry point: `kira/code_workspace.py`, opened from the main navigation menu.
- The workspace owns a project root, QFileSystemModel tree, text editor and explicit-save path. Save creates a one-time `.ai1code.bak` backup before replacing the file.
- The PowerShell terminal runs only after a per-command confirmation. Commands execute as the current Windows user in the selected project working directory; they are not sandboxed and may affect paths outside the project.
- `kira/code_agent.py` is the provider-neutral read-only coding engine. It uses the shared configured HybridRouter routes but does not inherit any companion character prompt and has no ToolAgent / MCP / desktop tools.
- Project context construction is bounded, skips secret files and runtime/build/dependency directories, rejects symlinks/path escapes, and includes only the selected text file plus a bounded tree.
- Code Agent cannot write files or run tests in this initial version. Future patch generation must show a diff and require explicit approval before writing. Debugger, breakpoints, Git UI and test orchestration remain future work.


### Ai1 Code: proposal, Diff and approval flow
- The Code Agent may return a complete replacement for only the selected file, wrapped in exact protocol markers. The engine validates markers, non-empty content and the 512 KiB proposal ceiling; malformed output is rejected.
- If the selected context contains `[REDACTED]`, patch generation is blocked so a masked credential can never be accidentally written over its original value.
- `CodeWorkspaceDialog` renders a unified Diff in a read-only preview dialog. The user must choose the explicit apply action; closing/rejecting the preview leaves the file untouched.
- Apply re-validates the selected path, compares current disk bytes with the snapshot taken when the file was opened, and compares editor text with the base text used for the proposal. Any stale state aborts the write.
- Approved content is limited to 2 MiB, backed up once as `.ai1code.bak`, written to a temporary sibling file and atomically replaced. The editor and disk snapshot are refreshed only after success.
- This is a single-file replacement workflow, not a general multi-file patch engine. The Agent itself still has no filesystem or shell write capability.


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
