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

## Purpose
Ai1 is a Windows desktop anime-style digital companion. It combines local and cloud chat models, persistent memory, character profiles, speech input/output, controlled desktop tools, and optional game-screen understanding.

## Character profiles
- Kira's original profile portrait is `assets/characters/kira.svg` and must remain unchanged unless the user explicitly requests a replacement. Ren and Mika currently have no built-in portraits; their image fields are intentionally empty until new portraits are supplied.
- Kira: coding, architecture, debugging and technical support; use Ai1 Code for project-file workflows and never claim unperformed tests.
- Mika: medical information and health education only, not diagnosis or independent prescribing; flag emergencies and preserve health-data privacy.
- Ren: current news and intelligence analysis; verify dates and independent sources, distinguish facts from claims/opinion, and disclose unavailable live verification.
- All three share the same Route Manager, model intelligence, tools, computer permissions, safety policy and current chat history/memory. Specialty is not an access-control boundary. Mika's prompt requests careful handling, but profile-level medical-memory isolation is not implemented.

## Current platform
- Windows 11
- Python / PySide6 desktop application
- Local chat through Ollama
- Cloud chat through the Route Manager
- Voice services managed separately in Cloud Voice

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
- `kira/voice.py`: sentence-level speech queue, pre-generation and playback.
- `kira/cloud_voice.py`: cloud STT/TTS provider registry, key storage, validation, priorities, cooldowns and failover.
- `kira/cloud_voice_ui.py`: Cloud Voice settings UI.
- `kira/listener.py`: microphone/STT input pipeline and wake-word handling.
- `kira/game_audio.py`: Windows WASAPI loopback capture and local-only game speech transcription/important-event filtering.
- Cloud Voice settings and protected API keys are stored outside the application folder.

## Active work
MiniMax Global TTS integration. It is a TTS-only provider; it must not be added to chat Route Manager or STT provider lists. Supported models: `speech-2.8-turbo`, `speech-2.8-hd`.

## Working rules
- Preserve existing provider and local voice fallbacks.
- Never log or display full API keys.
- Keep provider settings and keys outside the application folder.
- Add regression tests for provider-specific behavior and safety-sensitive capture behavior.
- Do not claim real-time streaming unless audio chunks are actually played before synthesis completes.
- Every completed project change should produce a timestamped `ProjectKira_YYMMDD_HHMM.zip` release when CI succeeds.


## Ai1 Code
- Ai1 Code is a separate engineering workspace inside the Ai1 application; it is not a character and does not change Kira/Ren/Mika identity.
- The first workspace provides project-folder selection, a file tree, a bounded UTF-8 text editor, explicit save with a one-time backup, a PowerShell terminal with per-command user confirmation, and a read-only Code Agent.
- Code Agent uses the existing configured HybridRouter routes but owns a separate prompt/worker lifecycle. It has no Tool Registry access, filesystem write access, or shell execution.
- Project context is bounded and excludes secret/configuration files, virtual environments, build output, dependency folders, databases and key material. Only the selected text file content is sent alongside a bounded file listing.
- Agent-generated edits, automatic patch application, debugger integration, Git controls, breakpoints and test orchestration are not implemented yet. They are planned for the debugging phase.


## Ai1 Code phase 2
- Code Agent can propose a complete replacement for the currently selected text file.
- Proposed content is parsed only when the explicit Ai1 markers are present and the result is non-empty and within the file-size limit.
- Patch proposals are blocked when the selected context contains redacted secrets, preventing masked credentials from being written back over real values.
- The workspace shows a unified Diff preview. No file is written until the user explicitly approves the change.
- Before applying, the workspace verifies that the on-disk file and editor base content have not changed since proposal generation; stale proposals are rejected.
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
- Legacy migration now copies persona memory and the evidence database as well as settings/chat/Cloud Voice data, without overwriting files already present in the destination or deleting the source.
- Rolling backups now include the persona memory JSON and evidence database. Added tests for data-directory resolution, legacy migration and backup coverage.
