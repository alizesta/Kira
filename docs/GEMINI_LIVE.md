# Gemini Live Voice Conversation in Kira

## Runtime architecture

Gemini Live is the default voice-conversation mode. Kira sends microphone audio as mono 16 kHz PCM directly to the Live model's WebSocket session and plays received mono 24 kHz PCM directly through the selected output device. Qwen3-ASR, Whisper, and Piper are not used on this path.

If the connection, session, or audio device fails, Live audio streams are released first. If the fallback option is enabled, the local listener is then started. The fallback uses Kira's existing local pipeline:

```text
Microphone → Qwen3-ASR / Whisper → Chat model → Piper
```

Selecting **Local** as the primary voice engine is also available in Voice settings.

## Setup

1. Register a valid Google AI Studio API key in Connections.
2. Open Voice settings and select that same Google connection in the Google key list.
3. Choose a Gemini Live model. The default is `gemini-3.8-live`.
4. Keep automatic fallback to local STT/TTS enabled.
5. Start with the microphone button on the main page. It starts the configured primary engine. The button on the Voice page controls the same session.

The Google key is read from the existing Connections settings; Voice does not store a separate key.

## Supported Live models

The Voice model selector exposes these current Google Live API model IDs:

- `gemini-3.8-live` — default and Google's recommended model for new production work.
- `gemini-3.8-live-extended-thinking` — deeper reasoning variant.
- `gemini-3.1-flash-live-preview` — legacy preview audio-to-audio option; Kira omits proactive-audio configuration because this model does not support it. Google recommends 3.8 for new production workloads.
- `gemini-2.5-flash-native-audio-preview-12-2025` — native-audio alternative with a different speech style. Google's current earliest shutdown date is March 31, 2027, so plan to migrate to 3.8 before then.

Gemini 1.5 is retired. The old `gemini-2.0-flash-live-001` Live endpoint shut down on December 9, 2025; neither old generation is offered as a selectable model. See Google's [Live API model guide](https://ai.google.dev/gemini-api/docs/live-api) and [model deprecation schedule](https://ai.google.dev/gemini-api/docs/deprecations).

## Main-page status

- **Connecting · Gemini Live:** a session is being established.
- **Live voice conversation · Gemini:** two-way audio is going directly through Gemini.
- **Fallback · STT + Piper:** the Live session has disconnected and the local pipeline is active.
- **Microphone off:** no audio input is active.

Input/output transcripts are added to conversation history only when session transcription is available and enabled. These transcripts are not the primary audio-processing path.

## Audio notes

- Headphones are recommended to prevent Kira's speaker output from being picked up by the microphone.
- Live sends audio at 16 kHz and receives audio at 24 kHz.
- The selected Voice input/output device is respected. If the selected device is no longer connected, the system default is used.
- If the Gemini SDK or connection is unavailable, Kira switches to the local fallback rather than waiting for cloud STT.
- The `google-genai` package must be installed for Gemini Live; the main Kira installation obtains it from `requirements.txt`.

## Live monitor imagery and visual companion (Task 3)

- The same Gemini Live session that receives microphone audio and plays the audio reply also receives JPEG frames as live visual input. No second voice session or second STT/TTS path is created.
- Live Desktop Vision sends the selected monitor. In automatic mode, this is the monitor containing the foreground window. Game Mode follows the monitor containing the active game window.
- Frames can be sent only while a Gemini Live conversation is connected and the user has manually enabled Live Desktop Vision or Game Mode. Starting voice alone does not capture the screen.
- Frames are sent only after a meaningful visual change and at a maximum rate of one frame per second. The queue keeps only the latest frame in RAM; older frames are discarded. Image data is not written to disk.
- Each frame is checked against the foreground window's HWND/PID and privacy policy before and after capture. A blocked, unknown, or changed window clears pending frames.
- Stopping Gemini Live, disabling the Vision source, or rejecting the privacy policy clears pending frames. The image is not attached to ordinary chat requests.
- The model should use frames actually received as visual conversation context, must not guess about windows outside the selected monitor, and should respond briefly only when an observation is useful.
- Current limitation: 1 FPS is sampled live visual input, not continuous video at the game's frame rate. The selected model/account must also support image input in Gemini Live.
