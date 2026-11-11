# Project Kira Context

## Purpose
Kira is a Windows desktop anime-style digital companion. The project combines local and cloud chat models, persistent memory, character profiles, speech input/output, and controlled desktop tools. The long-term goal is natural, continuous interaction rather than a text-only chatbot.

## Current platform
- Windows 11
- Python / PySide6 desktop application
- Local chat through Ollama
- Cloud chat through the Route Manager
- Voice services are managed separately in Cloud Voice and stored outside the application folder

## Voice architecture
- `kira/voice.py`: sentence-level speech queue, pre-generation and playback.
- `kira/cloud_voice.py`: cloud STT/TTS provider registry, key storage, validation, priorities, cooldowns and failover.
- `kira/cloud_voice_ui.py`: Cloud Voice settings UI.
- `kira/listener.py`: microphone/STT input pipeline.
- Cloud Voice settings and protected API keys are stored in `%LOCALAPPDATA%\\Kira\\cloud_voice.json`.

## Active work
MiniMax Global TTS integration. It is a TTS-only provider; it must not be added to chat Route Manager or STT provider lists. Current supported model catalogue: `speech-2.8-turbo`, `speech-2.8-hd`.

## Working rules
- Preserve existing Google, Groq, ElevenLabs and local voice fallbacks.
- Never log or display full API keys.
- Keep provider settings and keys outside the application folder.
- Add regression tests for provider-specific behavior.
- Do not claim real-time streaming unless audio chunks are actually played before synthesis completes.
- Every completed project change should produce a timestamped `ProjectKira_YYMMDD_HHMM.zip` release when CI succeeds.
