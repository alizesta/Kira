# Sentence-by-Sentence Speech

## What changed

- Replies are split into short sentences by `kira/speech_split.py` (Persian, English, and Japanese). Decimal numbers, URLs, and abbreviations such as `Dr.` do not split a sentence. Very short sentences are joined to the next one. A very long string without a period is split at a comma or space; the first segment may be split earlier at a comma.
- `Speaker` in `voice.py` owns one **Session** for each reply. A worker synthesizes sentences in order, prefetching at most two sentences ahead of the sentence being played (`PREFETCH`). Playback continues as soon as the next sentence is ready.
- `started`, `finished`, and `level` signals are emitted only once for the whole reply. Microphone behavior and Barge-in remain unchanged.
- Every sentence is synthesized only with local Piper. If the Piper model is not ready or WAV generation fails, an error is shown; audio is not redirected to Cloud, Edge, or a Windows speech engine.
- Sentence speech uses the selected local Piper model. This version does not automatically select an online/cloud voice based on language.

## Start speaking while the reply is still being generated

The **Start speech from the first complete sentence** setting is enabled by default. `main.py` sends cleaned response text to `Speaker.stream_text` as it arrives; only complete sentences are spoken. Stop, Barge-in, a new message, or an audio-device change cancels the remainder of that reply. Playback does not restart from the middle.

## True audio-byte streaming (not implemented)

The implementation synthesizes and plays sentence by sentence. It does not yet stream audio bytes within an individual sentence. Options and risks are recorded in the handoff report.
