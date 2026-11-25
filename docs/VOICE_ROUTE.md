# Voice and Route Settings

## 1. Speech input and output

All speech recognition and speech synthesis use local engines only:

- **Input/STT:** local Qwen3-ASR first; local faster-whisper if the primary engine is not ready or returns empty output.
- **Output/TTS:** local Piper and a WAV file generated on the same computer.
- **Microphone:** recording through sounddevice and the selected input device.
- **Speaker/headphones:** local WAV playback through the selected output device.
- Speech speed, output volume, microphone gain, and input sensitivity are independent settings.

There is no Edge TTS, Windows SAPI, Google Speech Recognition, or Cloud Voice path for this local voice pipeline. If a local engine is not ready, the app shows an error and does not switch to an online service.

## 2. Route is only for chat models

Route Manager selects the conversation model:

- Local Ollama models.
- Chat API Providers added by the user.

Adding or validating an API key checks only chat capability; no test STT/TTS request is sent. Enabling a cloud Provider for chat does not change the voice path.

## 3. Application separation

- Voice engines only convert speech to text or text to WAV.
- The Chat Router only selects the response-generation model.
- Memory and character behavior remain independent of STT/TTS engines.
- Audio models can be loaded once and kept in memory for subsequent messages.
