# Ai1 Architecture

## Product identity
Ai1 is the application. Kira, Ren and Mika are character profiles within Ai1.

## Game Mode and Vision

### Components
- `kira/game_mode.py` owns foreground-window/process inspection and game-window capture.
- `GameModeMonitor.poll()` emits a detection signal once per process ID during the current application session. Detection never changes the manual enabled state.
- `MainWindow` owns the visible Game Mode toggle and the suggestion message.
- The manual toggle starts off on every launch; no persisted preference can silently enable capture. Capture interval and JPEG quality are centralized as `CAPTURE_INTERVAL_MS` and `CAPTURE_JPEG_QUALITY` constants in `kira/game_mode.py`.
- `capture_last_game()` returns a window pixmap only while the monitor's enabled flag is true.
- While Game Mode is enabled, a 1,000 ms Qt timer samples the detected game window. `GameModeMonitor` downsizes each captured frame to fit within 854×480 while preserving aspect ratio. MainWindow retains only the newest frame in memory and encodes it as JPEG (quality 68) when a user sends a message. The existing attachment composer and HybridRouter image payload path carry only that latest frame; no continuous background upload occurs.
- Turning Game Mode off stops the capture timer immediately, clears the cached frame, and ensures the next message is sent without a game frame.

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
