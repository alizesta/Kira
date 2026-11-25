# Eye Mode — Desktop Observation and Understanding Guide

## Overview

Eye Mode is Kira's unified screen-observation capability. When explicitly enabled, Kira periodically samples the selected monitor and builds a bounded context from visible content, the foreground window, visual changes, and (when local OCR is enabled) readable on-screen text. It applies to the whole desktop, not just games.

Eye Mode has two related consumers:

1. **Desktop Context for ordinary chat:** a bounded text summary of desktop state is included in conversation context.
2. **Gemini Live:** when a Live voice session is active and the visual source is permitted, changed JPEG samples are sent to that same session through the capture path.

## Behavior and sampling rate

- Capture occurs only after the user explicitly enables Eye Mode.
- The selected monitor is used. In automatic mode, Kira uses the monitor associated with the foreground window.
- The Perception path detects meaningful changes and runs OCR only when needed.
- Gemini Live receives at most one frame per second, and its send queue keeps only the latest frame.
- This is not continuous 30/60 FPS video, and Kira does not see every monitor frame.
- Ordinary chat does not automatically attach raw screenshots; it uses the text summary from DesktopContext. Raw images are sent to Gemini Live only while a Live session and the visual source are active.

## Screen-information freshness

DesktopContext labels the latest observation as follows:

| Label | Age of latest observation | Usage |
|---|---:|---|
| Fresh | Up to 15 seconds | May be described as the currently observed state. |
| Recent | More than 15 and up to 60 seconds | May be described only as the latest recorded observation, not a guarantee of the current state. |
| Stale | More than 60 seconds | Must not be described as the current screen state. |
| Unknown | Invalid or unknown timestamp | Do not claim that the observation is current. |

Previous observations are separated as visual history and must not be combined with current state. Kira should not narrate when an image was seen unless it matters; when data is old, uncertainty must be explicit.

## Privacy and lifecycle

- Foreground window/process identity and allow/block rules are checked again before and after capture.
- If a window is blocked or unknown, sensitive text context and current active context are cleared.
- Raw frames and OCR text are not saved to log files or a database. DesktopContext is RAM-only and capped at 2,000 characters.
- Disabling Eye Mode, disabling the visual source, or failing the privacy policy must stop capture and clear queued frames and current visual state.
- OCR is optional and local; no language package or data is installed automatically. OCR is off by default in Game Mode.

## Architecture components

- **DesktopCaptureService:** monitor capture and HWND/PID revalidation.
- **PerceptionEngine:** foreground-window normalization, change detection, and Perception event creation.
- **OcrEngine / `vision_ocr.py`:** replaceable OCR contract and optional Tesseract implementation.
- **DesktopContext:** bounded RAM-only context, deduplication, and freshness labels.
- **AttachmentsVisionController:** opt-in, monitor selection, privacy policy, change sampling, and JPEG creation.
- **RuntimeVoiceMixin:** narrow bridge for Gemini Live readiness, frame sending, and queue clearing.
- **GeminiLiveWorker:** one-frame queue and synchronized audio/visual transport.

## Limitations and verification status

- OCR quality depends on installed language data, text clarity, and screen content.
- Gemini Live image support depends on the selected model and Provider.
- Multi-monitor capture, CPU/RAM behavior, latency, audio/video synchronization, and actual Windows behavior must be checked on the target device.
- Regression tests exist in the repository, but the presence of a test does not mean it has passed. Until tests are executed and the feature is accepted on Windows, these items are not runtime-verified.

## Related files

- `kira/perception/`
- `kira/app/desktop_context.py`
- `kira/vision_ocr.py`
- `kira/ui/main_window_attachments_vision.py`
- `kira/voice.py`
- `tests/test_desktop_context.py`
- `tests/test_perception_engine.py`
- `tests/test_vision_ocr.py`
