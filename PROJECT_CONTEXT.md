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
- The foreground-game detector is advisory only and polls the foreground Windows process/window.
- A game process receives one suggestion per process ID during the current Ai1 session.
- Game Mode starts disabled on every application launch and is enabled only by the user's explicit toggle.
- Screen capture is prohibited while Game Mode is off.
- While enabled, the most recently detected game window is captured when the user sends a chat message; the frame is attached through the existing image pipeline.
- Disabling Game Mode immediately disables further capture. It does not terminate the game or change its settings.
- Detection uses process/window metadata and a conservative title/process/fullscreen heuristic; it is not guaranteed to identify every game.
- Vision requests require a vision-capable model on the selected Route. Text-only models may reject image payloads; the existing provider error path explains this limitation.

## Voice architecture
- `kira/voice.py`: sentence-level speech queue, pre-generation and playback.
- `kira/cloud_voice.py`: cloud STT/TTS provider registry, key storage, validation, priorities, cooldowns and failover.
- `kira/cloud_voice_ui.py`: Cloud Voice settings UI.
- `kira/listener.py`: microphone/STT input pipeline.
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
