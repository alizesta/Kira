# Changelog

## 2026-11-11

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
