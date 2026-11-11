# Changelog

## 2026-11-11

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
