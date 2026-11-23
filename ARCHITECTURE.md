# Kira Architecture

**Current architecture source:** [docs/ARCHITECTURE_MASTER.md](docs/ARCHITECTURE_MASTER.md)  
**Snapshot branch:** `new-main`  
**Last synchronized:** 2026-11-23

This file is the short repository-level entry point. It intentionally contains no independent architecture claims; the linked documents below are the canonical records.

## Canonical architecture documents

1. [Architecture Master](docs/ARCHITECTURE_MASTER.md) — verified current structure, runtime composition, dependency directions and subsystem boundaries.
2. [Module Ownership](docs/MODULE_OWNERSHIP.md) — module owners, public contracts, allowed dependencies and forbidden coupling.
3. [Architecture Roadmap](docs/ARCHITECTURE_ROADMAP.md) — confirmed technical debt, extraction decisions and ordered next steps.
4. [Architecture Implementation Handoff](docs/ARCHITECTURE_IMPLEMENTATION_HANDOFF_2026-11-18.md) — implementation evidence and reviewer checklist for TASK 017–020.

## Current architecture facts

- Product entry point: `kira/main.py`.
- Production Qt Composition Root: `kira/ui/bootstrap.py`.
- Application services and feature factories are registered through `kira/app/feature_modules.py`.
- The production window is `kira/ui/main_window.py`, composed with eight window-scoped Feature Controllers and an explicit `FeatureControllerRegistry`.
- Chat domain/application services are under `kira/chat`, `kira/domain`, `kira/core/interfaces` and `kira/app`.
- The shared EventBus carries notifications; direct request/response work uses explicit service contracts.
- Durable Chat persistence is owned by the Chat persistence/repository boundary. Runtime Session state is separate from durable Conversation state.
- MainWindow is no longer the legacy monolith, but Qt presentation, worker/resource lifecycle and some UI orchestration remain in the UI layer.
- Startup deferral is now merged: inactive character sessions, optional services, ToolAgent construction, settings pages, feature controllers and selected worker/provider imports are deferred until needed.
- Auto-mode tool schemas are request-topic-scoped, with execution-time enforcement against hidden tools; explicit Always mode retains the full catalog.
- Chat history delegation and SQLite schema creation/backfill have dedicated owners (`ChatHistoryFacade` and `SqliteSchemaManager`); `ChatApplicationService` retains request dispatch and streaming ownership.

## Desktop pet and dance library

`CompanionWindow.pet` (`kira/pet.py`) handles dragging (hang), falling and perching (`kira/perch.py`), and receives beat state from `kira/music_dance.MusicWatcher`. While music plays it calls `view.refresh_dances()` (`kira/dance_library.scan()` of `assets/vrm/animations/`) and `view.music(state)`; `assets/vrm/viewer.html` then plays a VRMA/Mixamo clip through an AnimationMixer evaluated after the procedural body, or a built-in dance style.

## Verification policy

A source file, test, merged pull request or green workflow status alone does not prove runtime behavior. Report static inspection, test execution, CI runner execution and Windows desktop acceptance separately. A workflow job with no runner/steps is **not executed** and must never be reported as a passing test.

For current status and limitations, use the verification sections in the three canonical documents and the latest entry in [TASK_HANDOFF.md](TASK_HANDOFF.md). Historical migration notes belong in dated records under `docs/`, not in this entry point.

- Live Desktop Perception (Task 2): `kira/perception/` owns foreground-window normalization, change detection and perception events; `kira/app/desktop_context.py` owns the bounded, RAM-only desktop summary. Optional OCR is isolated behind `OcrEngine` in `kira/vision_ocr.py`.
- 2026-11-21 23:49 Iran: UI icons live in `assets/icons/*.svg` (Lucide, ISC) rendered with glow by `kira/ui_icons.py`; `stop` and mood faces remain code-drawn.

- 2026-11-22 03:20 Iran: audio playback = `_PcmPlayer` (QAudioSink, PCM wav only) in kira/voice.py; QMediaPlayer / QSoundEffect / winsound removed. Needs a listening test on Windows.

- 2026-11-22 03:26 Iran: speech engine is switchable (settings `tts_engine`: piper | kitten; Kitten English-only, Persian sentences always Piper). See kira/voice.py `_use_kitten` / `_synth_kitten`.

## Gemini Live visual companion

The existing Gemini Live audio worker accepts privacy-checked full-monitor JPEG snapshots through the same Live session. `AttachmentsVisionController` owns explicit source opt-in, full-monitor capture, foreground/privacy rechecks and change sampling; `RuntimeVoiceMixin` exposes only the send/clear/readiness bridge; `GeminiLiveWorker` owns the bounded one-frame queue and serialized audio/video transport. Video is sampled at no more than 1 FPS and remains RAM-only. Runtime acceptance is pending Windows/API testing.
