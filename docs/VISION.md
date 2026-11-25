# Live Game and Desktop Vision in Kira

## Perception Engine and DesktopContext — Task 2

- `ActiveWindowProbe` obtains foreground-window metadata from the existing Win32 adapter and normalizes its identity. Only an active, permitted window is processed.
- `ChangeDetector` keeps a small grayscale image sample in RAM. OCR runs only after a meaningful change in an allowed window; raw frames are not stored to build Context.
- `OcrEngine` is a replaceable contract. The Tesseract implementation works only when Pillow, pytesseract, the Tesseract engine, and language data are already installed. No package or language file is downloaded or installed automatically.
- OCR output contains bounded text, language, and confidence. Missing engine/language data or an OCR error leaves the text empty and does not stop Capture or Chat.
- `DesktopContext` is held in RAM and includes the active application/window title, foreground duration, visible text, and up to 12 recent events. The summary sent to the model is capped at 2,000 characters and is not persisted to disk.
- OCR text is accepted only after the identity of the same window is revalidated. Entering a blocked or unknown window clears prior OCR text and window metadata. Full titles and OCR text are not included in vision_trace.
- Desktop OCR can be disabled with `desktop_vision_ocr_enabled`. Game Mode OCR is controlled by `vision_ocr_in_game_mode` and is off by default so it does not compete with the game.
- Ordinary chat receives the DesktopContext summary instead of automatically attaching raw frames. Images are sent from a user-selected attachment or manual capture; independent Vision analysis and FrameGate continue separately.
- Trace records summary-build time, OCR time, character count, and confidence to measure real cost on the target hardware. These values are not a substitute for a real benchmark.

## Behavior

Vision may capture and analyze frames only after Game Mode is manually enabled and a foreground game window is detected. Both Story Mode and Competitive Safe allow read-only visual analysis; Competitive Safe still blocks game-audio monitoring and input/desktop control.

Explicit Persian/English chat commands may also enable, disable, or report Game Mode. They are connected directly to the real controller; the model does not guess the current status. The LIVE GAME VISION STATUS in each request's Context indicates whether a frame was actually attached to that specific model request. Game Mode being on does not by itself mean the model has seen an image.

Three modes are available from the 🎮 menu:

| Mode | Analysis interval | Target size | JPEG quality |
|---|---:|---:|---:|
| Economy | 5 seconds | Up to 854×480 | 62 |
| Smart | 1 second | Up to 960×540 | 66 |
| Fast | 0.5 seconds | Up to 1280×720 | 70 |

Economy is the default. These intervals control the **model analysis request rate**, not screen-capture FPS; not every display frame is sent to the model.

## Processing path

1. GameModeMonitor first captures the display output through DXcam using DXGI Desktop Duplication and crops the game window. If DXGI is unavailable or returns no frame, it tries the Windows Graphics Capture backend. If DXcam cannot be used, the older Qt path (`QScreen.grabWindow`) remains as a fallback. The final image is resized to the configured limit.
2. FrameGate limits the analysis rate and removes duplicate frames.
3. The image is converted to JPEG and sent through Kira's existing attachment path.
4. VisionAnalysisWorker runs the analysis outside the UI thread through HybridRouter.
5. If the previous analysis is still running, new frames are not accumulated for that request; the next cycle captures the newest image.
6. The result enters the conversation only while Game Mode and Vision permission remain enabled.

## Windows capture path

- DXcam, under the MIT license, is installed only on Windows. The DXGI path has priority for Direct3D and fullscreen games.
- The Windows Graphics Capture backend is tried only when DXGI fails or is unavailable. If DXcam is absent or both backends fail, the app falls back to Qt.
- BGRA frames are converted directly to QImage; OpenCV is not required for this path.
- The capture rectangle is computed from foreground-window coordinates and constrained to output dimensions. The size sent to the model remains subject to Vision policy.
- The current DXcam implementation uses the primary Windows output. Capturing a game on a secondary monitor still needs explicit DXGI-output mapping and must be tested separately with multiple monitors.
- Performance figures in the DXcam project README are that project's own benchmarks, not Kira benchmarks.

## Model compatibility

Image analysis requires a model that supports image input (multimodal/vision). HybridRouter attaches the image in a standard format; a text-only model cannot analyze its content, and a Provider error is shown clearly. Actual vision support for the installed Ollama model must be verified at runtime; a model name alone does not guarantee image support.

## Resources and safety

- Image processing and model requests run on a background thread.
- At most one Vision analysis is active at a time.
- No video is saved or uploaded continuously; only sampled frames are sent for analysis.
- Competitive Safe does not change game-access or system-control restrictions.
- Local OCR is optional and independent of the Vision model; no engine or dependency is installed automatically.
- FrameGate keeps counters and the latency of the latest analysis.

## Model-routing completion and safe cancellation

- Automatic image analysis uses only a Route whose model is known to support Vision or whose Provider configuration has `vision_enabled: true`. Unknown models are deliberately not selected for images.
- For a custom OpenAI-compatible Provider, set `vision_enabled` only when the model actually accepts image input.
- Ollama capability detection is cached separately for each server address and model name. Temporary errors or a stopped server are not cached as permanent lack of model capability; embedding models are not misidentified as Vision models.
- Disabling Game Mode or actually exiting the application cancels active Vision requests and closes their HTTP connection.
- Ordinary messages do not automatically attach live raw frames; the DesktopContext summary is included in model Context. Images are sent only from a user attachment or manual capture.
- Commands such as “enable Game Mode”, “disable Game Mode”, and “Game Mode status” run deterministically. Questions about screen visibility receive the real capture Context: the model may describe the game only when a frame was attached to that request.
- Desktop OCR uses the replaceable OcrEngine. Tesseract and the `fas`/`eng` language data must already be installed. Without the engine or language data, OCR text is empty. Game Mode has no local OCR by default and can enable it with `vision_ocr_in_game_mode`.
- Local OCR rejects images above 15 megapixels or payloads above 12 MB and gives Tesseract at most 3 seconds.
- Switching from Story to Competitive Safe immediately stops capture and cancels an active Vision analysis; merely hiding the result is insufficient because an image must not be sent after permission is revoked.
- Entering Competitive Safe also revokes pending grants and stops local/Agent tasks and an active Ai1 Code command.
- Running tasks are cancelled only when entering the safe profile. Reapplying the same profile does not unnecessarily interrupt permitted web research.
- Fixed desktop shortcuts and browser launching are also blocked in this profile; disabling Tools mode is not a way to bypass restrictions.
- Ai1 Code cancellation is scoped to the same Session so another active tab does not have its Busy state or message queue changed.
- When Capture permission is revoked, scheduling and the previous frame fingerprint are reset so that re-enabling does not inherit the old sampling delay or suppress a duplicate result.
- When the game window leaves the foreground, the previous capture target is cleared. Disabling Game Mode also clears the stored window so an old game cannot be captured again.
- The foreground window is rechecked before every sample; the game-detection timer alone is insufficient to prevent background-window capture.
- Automatic background analysis uses the streaming path so Stop and profile changes can interrupt the active HTTP connection. A cancelled request does not add a partial result to chat.
- The Worker passes cancellation as a separate Event to the Router. If cancellation occurs during model detection or before a connection starts, the request is never sent to the Provider.
- Router checks the cancellation Event at the beginning, before Provider creation, and while reading the stream; clearing internal Stop state cannot reactivate a cancelled Event.
- The image-upload body also checks the cancellation Event for each chunk; cancellation during upload stops reading further image chunks.
- An image attached to an ordinary message selects the Vision Route after turn role selection. Vision scope is nested inside the role scope so the Vision model preference is not overwritten.
- Background analysis results are delivered to the character Session that initiated Capture. If another tab becomes active while analysis is running, the result is not inserted into the wrong character's conversation. A new message for the same Session remains queued until the cancelled Vision task finishes.
- SessionRelay delivers the result and drains the queue so background-thread signals reach the correct tab and no new message starts after the window closes.
- Queue dispatch after window closure is guarded; a late callback cannot create a new thread or request after shutdown.
- If the user sends a message during background analysis, analysis is cancelled and the message is queued for that Session. The voice-input flag is preserved with the queued message.
- Independent tests exist for Route selection, cancellation after profile change, frame-rate limits, duplicate-frame removal, one-frame queue behavior, and OCR error handling.

## Live Desktop Vision with Gemini Live (Task 3)

When Gemini Live voice conversation and a manually enabled visual source are active at the same time, the Vision controller captures the selected monitor (or the foreground window's monitor in automatic mode), creates a JPEG frame, and sends it to the same voice session. Sending is limited to one frame per second and occurs only after a meaningful change. This path is independent of cloud analysis for ordinary chat and may send live images to the Live session while an ordinary chat response is busy.

The privacy policy is rechecked against the foreground window identity. An image is sent only when HWND/PID and source permission are verified. Disabling Live Desktop Vision or Game Mode, stopping the conversation, or detecting a blocked window clears pending frames. Images are held in memory only and are not automatically added to conversation history or user files.

This capability provides the model with visible content from that monitor only; it does not grant access to other monitors. 1 FPS is not continuous 30/60 FPS video.
