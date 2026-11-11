# Ai1 Project Context

## Product identity
- **Ai1** is the desktop application and product name.
- **Kira**, Ren and Mika are selectable companion characters inside Ai1; Kira is not the application name.
- Game Mode is a manually enabled gameplay feature. Game detection may suggest it, but must never enable it automatically.

## Purpose
Ai1 is a Windows desktop anime-style digital companion. It combines local and cloud chat models, persistent memory, character profiles, speech input/output, controlled desktop tools, and optional game-screen understanding.

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
- The workspace shows a unified Diff preview. No file is written until the user explicitly approves the change.
- Before applying, the workspace verifies that the on-disk file and editor base content have not changed since proposal generation; stale proposals are rejected.
- Approved changes use the existing one-time `.ai1code.bak` backup and an atomic temporary-file replacement.
- This phase does not add multi-file patches, automatic test execution, a debugger, or Git controls. GUI/PowerShell runtime still requires validation on Windows 11.
