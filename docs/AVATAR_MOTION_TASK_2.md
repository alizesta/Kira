# Task 2 — Kira Character Motion

## Implemented behavior

- Existing idle behavior was retained: blinking, breathing, subtle head/body movement, cursor tracking, and occasional low-frequency automatic motions.
- Listening is connected to the actual local microphone and Gemini Live states. A curious reaction and a short head movement are enabled.
- Thinking begins when a request starts and releases the Listening state.
- Speaking uses local Speaker signals for local TTS and output-audio activity for Gemini Live. Audio level drives mouth animation.
- Playback completion, microphone stop, and session disconnection return the character to the appropriate state.
- Reply emotions and event/click reactions use the existing EmotionDirector and animation packs.
- Existing frame rates are retained: 60 FPS while the avatar is visible and 5 FPS while hidden.

## Current avatar-model limitation

The current PNG avatar is a flat image. Its profile disables eye layers and VRM for this image, so independent pupil/eye movement is not possible without a suitable layered asset or model. Head and body movement use a soft-body rig. Full-body VRM control is available only when a VRM model is active.

No theme, colour, layout, or application version was changed.
