# Emotion-driven Persian TTS

Kira's emotional engine already resolves the active reply emotion and intensity. This layer carries that metadata into the actual Piper synthesis path.

## Delivery pipeline

1. The reply parser removes the private emotion tag and keeps its emotion IDs/intensity.
2. The runtime forwards that metadata to Speaker before the first eligible streamed sentence is synthesized.
3. A bounded prosody profile is resolved for each emotion. A secondary emotion contributes a small blend; intensity interpolates from neutral.
4. Piper receives native length_scale, noise_scale and noise_w_scale parameters.
5. Comma/semicolon clauses are synthesized separately and joined with real, emotion-scaled silence. Inter-sentence silence is prepended to the next sentence, so a live stream never leaves an artificial pause after its final sentence.
6. PCM gain is adjusted subtly. A small pitch shift is attempted through ffmpeg when available; if ffmpeg is absent or fails, synthesis remains valid and only pitch adjustment is skipped.
7. The finished WAV is validated and cached. Cache identity includes model/sidecar signature, text, emotion profile and speed so a neutral clip cannot be reused for a sad or excited reply.

## Emotion profile intent

- Sad, lonely, disappointed and guilty: slower, softer, lower variation, longer pauses.
- Excited, laughing and surprised: faster, slightly brighter, more variation and shorter pauses.
- Calm, content and relieved: measured delivery and longer breathing room.
- Angry, frustrated and annoyed: firmer, clipped timing without extreme loudness.
- Affectionate, warm, grateful and protective: gentle, close delivery.
- Curious, confused and thinking: measured but lightly varied delivery.
- Shy, embarrassed and tsundere: slower, softer and slightly hesitant.

All 37 emotion IDs in EmotionalRuntime have an explicit profile. Values are conservative starting points; final tuning requires listening to the Mana voice on the target PC.

## Persian text preparation

The Persian TTS quality branch's normalization is retained: Arabic/Persian letter normalization, ZWNJ and punctuation cleanup, common technical-name pronunciation, and optional ezafe processing. This layer also spells out Persian-context integers/decimals and Jalali dates (e.g. 1405/08/28) before phonemization. Latin-only text and version-like Latin identifiers are left untouched.

## Medium vs low model benchmark

The bundled Mana voice is fa_IR-mana-medium.onnx; this repository does not currently bundle a verified Mana low model. The benchmark script compares any installed ONNX voices without changing the selected voice:

    python scripts/benchmark_piper_voices.py --models "path/to/medium.onnx" "path/to/low.onnx"

Compare median synthesis time and real-time factor (RTF). RTF below 1.0 means synthesis is faster than playback. Do not switch models solely on file size; listen to the same Persian samples and compare intelligibility and naturalness.

## Validation

Focused tests cover all emotion IDs, parameter bounds, emotion blending, comma/sentence silence, WAV assembly, gain, optional ffmpeg fallback, number/date expansion and Piper parameter forwarding. The test workflow also runs existing voice/TTS regression suites, Ruff and py_compile.

