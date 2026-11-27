# Local Voice Engines

All local voice input and output is processed on the user's machine. Microphone audio and TTS text are not sent to Google, Edge, Windows SAPI, or cloud Providers by the local voice path.

- **Primary STT:** Qwen3-ASR 0.6B, running locally.
- **Fallback STT:** faster-whisper, running locally.
- **TTS:** Piper ONNX with the Mana Persian voice or a selected ONNX file. Speech speed uses Piper's native `length_scale`, so changing speed does not manipulate the sample rate or pitch.
- **Persian TTS preprocessing:** a quantized ALBERT model detects ezafe and inserts the appropriate kasra marker before Piper phonemization. It runs locally on CPU using ONNX Runtime.
- **Playback:** uses the selected Windows output device. This plays a local WAV file; it is not a Windows speech engine.

## Installation and preparation

For a fresh installation, run `install.bat`. The installer:

- Installs audio capture/playback dependencies.
- Installs Qwen3-ASR, faster-whisper, and Piper.
- Downloads the Qwen model and Persian Piper voice and prepares them for local use.

To install or repair only the voice engines in an existing environment:

```powershell
.venv\Scripts\python.exe scripts\setup_local_voice.py --install --prepare-models
```

The first download of packages and model weights requires internet access. After the models are prepared, recognition and synthesis run on the local computer. Model weights and caches are stored in Kira's persistent data directory, not in the application's temporary folder.

When local Piper TTS is enabled (the default), Kira also checks and prepares the Piper runtime and the default Mana Persian voice automatically in a background worker at startup. If speech is requested before that setup finishes, the first synthesis worker installs the missing Piper runtime and continues with the selected/default voice. The first-time package/model download requires internet access; subsequent synthesis is local. An explicitly disabled local TTS setting is respected.

The ALBERT model (`abreza/persian-ezafe-albert`) downloads its quantized version to the same Hugging Face cache during the first local voice warmup. Ezafe detection is then fully offline and CPU-based. Set `KIRA_TTS_EZAFE=0` to disable this preprocessing. If the model is missing or ALBERT fails, the original text is passed to Piper unchanged.

## Engine selection and testing

In the **Voice and Microphone** tab:

- Choose the language and local fallback Whisper model.
- Configure microphone sensitivity, input microphone, and output speaker.
- Enable or disable Qwen3-ASR and Piper independently in **Local Models**.
- Use **Test STT** and **Test TTS** to test each path.

## Failure behavior

- If Qwen3-ASR is unavailable or returns empty text, Kira falls back only to local faster-whisper.
- If local Whisper is not installed or ready, an explicit error is shown; no online service is substituted.
- If Piper is not ready or does not create a valid WAV, speech playback stops with an error. No cloud voice, Edge, or SAPI fallback is used.

Chat models (Ollama or API Providers) are independent of this voice path. Using an API for chat does not mean microphone audio or TTS text is sent to that Provider.
