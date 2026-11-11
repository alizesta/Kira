# Changelog

## 2026-11-11

### Game Mode Windows CI gate
- Added a Windows runner for Game Mode identity and monitor regression tests using PySide6 with Qt offscreen.
- Made the release packaging job depend on the Windows Game Mode test job, so a failed Windows regression blocks publishing the ZIP.
- Kept the Linux portable test suite and syntax check unchanged.
- Clarified that CI uses mocked foreground-window data and does not replace a real interactive Windows 11 smoke test.

## 2026-11-11

### Temporary portrait removal for release build
- Removed Ren and Mika portrait assets and cleared their built-in image references until replacement portraits are ready.
- Updated the character card to support an intentionally empty portrait without substituting another character's artwork.
- Kept Kira's original SVG portrait unchanged.

## 2026-11-11

### Game detector self-identification fix
- Exclude Ai1's own process ID before game title hints and large-window heuristics.
- Add a regression test using the `Project Kira 1 stable` window title and a full-screen window rectangle.

## 2026-11-11

### Linux regression and Windows ZIP fixes
- Updated the requirements regression test to recognize the intentionally optional `psutil` dependency.
- Added `.gitattributes` enforcement and release-time normalization so every packaged `.bat` file uses CRLF, including archives built on Linux.
- Updated stream/persistence test fixtures to account for LeakGuard's deliberate short-preamble buffering without weakening its filtering behavior.
- Updated GUI navigation tests for the current menu, including the separator and Ai1 Code entry.
- Expanded CI coverage to include streaming, chat persistence and release regression modules.

### Character specialties and profile portraits
- Defined Kira as the coding/software-development specialist, Mika as the medical-information guide, and Ren as the news and intelligence analyst.
- Added scope-aware specialty prompts while keeping model routes, tools and permissions shared across characters.
- Added medical safety boundaries: no definitive diagnosis or independent prescribing, emergency red flags, reputable evidence and privacy-aware handling of sensitive health details.
- Restored Kira's original SVG portrait as her active profile image. Removed the unfinished Ren and Mika portrait assets; their profile image fields are empty until replacement portraits are supplied.
- Added regression coverage for each built-in character's specialty prompt.

### Ai1 Code workspace (initial foundation)
- Added a separate Ai1 Code workspace with project folder selection, file tree, bounded UTF-8 editor and explicit save with a one-time backup.
- Added a PowerShell terminal that requires confirmation for every command; it runs as the current Windows user and is not a sandbox.
- Added a read-only Code Agent that uses shared configured routes without inheriting Kira/Ren/Mika persona prompts or ToolAgent/MCP permissions.
- Project context is bounded and excludes secret/configuration files, runtime/build/dependency directories and symlinks/path escapes.
- Automatic edits, approved Diff application, debugger, breakpoints, Git controls and test orchestration are deferred to the debugging phase.

### Dual Game Mode profiles and permission boundaries
- Added manual Story Mode for offline/story games and Competitive Safe for online/PvP or unknown games.
- Competitive Safe disables game-window Vision/capture, game/system WASAPI loopback and local desktop/app/file/MCP/agent control tools. It retains ordinary chat, web tools and independent microphone/wake-word interaction.
- Added a central ToolRegistry execution guard so restrictions also apply to direct tool calls, confirmations and Agent tasks.
- Unknown profiles fail closed to Competitive Safe; detection only recommends and never auto-enables a profile.
- Story Mode retains existing user-requested desktop controls for offline play; Competitive Safe blocks desktop controls and gameplay input. Both profiles keep code injection, game memory access, graphics hooks, overlays, game-file modification and driver installation disabled.
- Added pure-Python regression tests for profile capabilities and tool-category restrictions.

### Game Mode audio and wake update
- Added Windows WASAPI loopback capture via PyAudioWPatch for default system/game output.
- Game speech is segmented and transcribed locally with faster-whisper; audio is neither saved nor sent to cloud STT.
- Ordinary game dialogue stays silent. A conservative keyword filter with cooldowns allows selected critical, mission and combat alerts.
- Game Mode temporarily enables microphone wake-word listening. Kira stays quiet until called; previous mic/wake states are restored when Game Mode is disabled.
- Loopback capture stops on Game Mode shutdown and application exit.

### Game Mode Vision update
- Capture the active game window once per second only while Game Mode is manually enabled.
- Downscale frames to a maximum 854×480 while preserving aspect ratio.
- Keep only the newest frame in memory; attach it as JPEG (quality 68) when the user sends a message. No continuous upload.
- Stop the capture timer and clear the cached frame immediately when Game Mode is disabled.
- Suppress game-mode suggestions if Game Mode is already enabled.

### Added
- MiniMax Global as a TTS-only Cloud Voice provider.
- Manual Game Mode toggle in the chat toolbar.
- Foreground game detection with one advisory suggestion per process launch.
- Guarded game-window screenshot capture, attached to the next user message only while Game Mode is manually enabled.
- Regression tests for Game Mode's default-off and capture-safety behavior.
- Product naming clarification: Ai1 is the application; Kira, Ren and Mika are characters.

### Preserved
- Existing Google AI Studio, Groq and ElevenLabs providers.
- Existing local Edge TTS and Windows speech fallbacks.
- Existing independent STT configuration and chat Route Manager.
- Game Mode remains off at startup and never auto-enables after a game is detected.


### Ai1 Code phase 2: Diff and explicit patch approval
- Added selected-file replacement proposals through the independent Code Agent.
- Added strict response-marker validation and rejection of malformed or empty proposals.
- Added read-only unified Diff preview and explicit user approval before writing.
- Added stale-file/editor checks, one-time backup and atomic replacement for approved changes.
- Blocked patch proposals for contexts containing redacted credentials to avoid overwriting real secrets with placeholders.
- Added regression tests for patch-response validation. Windows GUI and PowerShell behavior still require manual testing on Windows 11.


## 2026-11-11

### Native Function Calling
- Added native JSON-schema tool calls for OpenAI-compatible Route providers.
- Reused the central ToolRegistry schemas and execution pipeline; native calls do not bypass permissions, confirmations, duplicate-call protection or Game Mode restrictions.
- Preserved standard assistant tool-call and tool-result messages across native rounds, with a safe text-result bridge if a later route lacks native support.
- Kept text-protocol fallback for providers without a native adapter.
- Added provider parsing and native message-normalization regression tests.

### Game Mode detector hardening
- Added an explicit product-window-title exclusion for Project Kira 1 stable / Kira / Ai1 windows in addition to the current-process-ID guard.
- Added regression tests for a mismatched reported PID and a positive large-game-window detection to avoid suppressing real games.

### Portable Game Mode identity regression coverage
- Extracted the current-process and known Ai1/Kira window-title exclusion into a pure-Python helper and added CI coverage for the false-positive case and a real-game negative control.

### Windows Game Mode test fixture correction
- Initialize a Qt application in the Game Mode test fixture so the primary-screen geometry query is available on Windows CI's offscreen platform.
- Include both Game Mode test modules in workflow path filters so future edits trigger the release gate.


### Native Function Calling: Gemini and Ollama
- Confirmed Google AI Studio/Gemini native tools through the existing OpenAI-compatible adapter and added a regression test for the official Google endpoint.
- Added Ollama `/api/chat` native tool requests, response parsing and assistant/tool-result message preservation.
- Added safe capability fallback: Ollama models that explicitly reject tool calling are marked unsupported so the router can continue to another native route or use the text protocol.
- Kept ToolRegistry validation, permission checks, confirmation flow, duplicate-call protection and Game Mode execution guard unchanged.

### Native Function Calling test fixture correction
- Build the assistant tool-call argument string with `json.dumps` in the Ollama multi-round regression fixture to avoid invalid Python escaping.


### Model Discovery and Route Manager validation
- Added Gemini pagination regression coverage for the official model-list API, including filtering non-chat models and verifying the API key remains in the header.
- Strengthened Google provider registration coverage to verify all discovered models remain visible while only the selected default model is activated as a Route.
- Extended Route Manager source-level tests to cover asynchronous refresh, registry merge and model enable/disable wiring.


### User-memory migration and backup hardening
- Include `kira_persona_memory.json` and `kira_evidence.sqlite3` in legacy-data detection and per-file migration.
- Include persona memory in rolling backups; keep evidence memory backed up through SQLite's online-backup API.
- Add tests proving the external Windows data directory/override, non-destructive migration, and backup restoration data coverage.

- Explicitly grant the release workflow `contents: write` so the GitHub Release action has the permission required to publish ZIP assets.

- Include the release workflow YAML in its own path filter and test that persona/evidence-only legacy folders are recognized as user data.
