# Project Kira Architecture

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
- Model IDs are presented from a built-in catalogue because the integration does not rely on an unverified model-list endpoint.
- Key validation performs a short real synthesis request; this consumes a small amount of TTS quota.
- API key persistence reuses CloudVoiceStore and Windows DPAPI protection.

## Shared storage
Cloud Voice settings are written atomically to `%LOCALAPPDATA%\\Kira\\cloud_voice.json`, separate from the program installation directory.
