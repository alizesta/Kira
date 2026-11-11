# Ai1 Architecture

## Product identity
Ai1 is the application. Kira, Ren and Mika are character profiles within Ai1.

## Game Mode profiles

- `story`: manual opt-in for offline/story games. Enables the existing game-window Vision sampling and local WASAPI loopback speech analysis. Existing desktop tools remain available.
- `competitive_safe`: manual opt-in and fail-closed default for online/PvP or unknown games. Disables game-window capture, Vision attachment creation, system/game audio loopback, and local desktop/app/file/MCP/agent tools. Ordinary chat, web tools, the user's own microphone and local wake-word interaction remain available.
- Profile permissions are centralized in `kira/game_mode_policy.py`; unknown profile values resolve to the restrictive capability set.
- The Game Mode toolbar menu exposes Story Mode, Competitive Safe and Off. Detection only recommends a profile; it never chooses or enables one.
- A central `ToolRegistry.execution_guard` enforces Competitive Safe restrictions for direct tool calls, confirmation flows and planned Agent tasks.
- Both profiles prohibit overlays, game-process memory access, code injection, graphics API hooks, gameplay input automation, game-file modification and game-driver installation. Competitive Safe reduces interaction but cannot guarantee that every anti-cheat permits Ai1 to run.

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
