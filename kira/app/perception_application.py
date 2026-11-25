"""Qt-free orchestration for local desktop perception and OCR."""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any, Callable, Protocol

from ..perception import PerceptionEngine
from ..perception.events import PerceptionEvent
from ..vision_ocr import OcrResult, OcrService


class CancellableWorker(Protocol):
    def cancel(self) -> None: ...
    def isRunning(self) -> bool: ...


@dataclass(frozen=True)
class PerceptionOcrJob:
    generation: int
    frame_id: str
    source: str
    window_info: dict[str, Any]
    jpeg: bytes
    started_at: float


@dataclass(frozen=True)
class PerceptionOutcome:
    status: str
    source: str | None = None
    reason: str | None = None
    applied: bool = False
    latency_ms: int = 0
    text_chars: int = 0
    language: str | None = None
    confidence: float = 0.0
    error_code: str | None = None
    engine: str | None = None
    error_stage: str | None = None
    error_message: str | None = None


def _window_identity(info: dict | None) -> tuple[Any, ...] | None:
    if not isinstance(info, dict):
        return None
    return (
        int(info.get("hwnd") or 0),
        int(info.get("pid") or 0),
        str(info.get("exe") or "").casefold(),
        str(info.get("title") or "").strip(),
        str(info.get("path") or "").casefold(),
    )


class PerceptionApplicationService:
    """Own privacy policy, change detection, OCR jobs and result application.

    This service has no Qt dependency. The UI worker adapter supplies the image
    codecs and a cancellable worker implementing the small worker contract.
    """

    def __init__(
        self,
        desktop_context: Any,
        capture_service: Any,
        *,
        ocr_service: Any | None = None,
        trace: Callable[..., Any] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if desktop_context is None or capture_service is None:
            raise TypeError("desktop_context and capture_service are required")
        self.context = desktop_context
        self.capture = capture_service
        self.privacy = capture_service.privacy
        self.ocr_service = ocr_service or OcrService()
        self.engine = PerceptionEngine(self.context, self.ocr_service)
        self._trace = trace or (lambda *_args, **_kwargs: None)
        self._clock = clock
        self._generation = 0
        self._job: PerceptionOcrJob | None = None
        self._worker: CancellableWorker | None = None
        self._result: Any = None
        self._disposed = False
        self._ocr_shutdown = False
        self._trace_ocr_diagnostics()

    def _trace_ocr_diagnostics(self) -> None:
        status = self.ocr_service.diagnostics()
        engines = status.get("engines", {})
        selected = engines.get(status.get("selected_engine"), {})
        languages = status.get("languages", {})
        self._trace(
            "ocr_runtime_diagnostics",
            engine=status.get("selected_engine"),
            state=selected.get("status"),
            installed=selected.get("installed", False),
            available=selected.get("available", False),
            ready=status.get("ready"),
            python_bindings_ready=selected.get("python_bindings_ready", False),
            pillow_ready=selected.get("pillow_ready", False),
            binary_ready=selected.get("binary_ready", False),
            requested_languages=",".join(selected.get("requested_languages") or ()),
            installed_languages=",".join(selected.get("installed_languages") or ()),
            missing_languages=",".join(selected.get("missing_languages") or ()),
            persian_ready=languages.get("fas", False),
            english_ready=languages.get("eng", False),
            error=selected.get("error_code") or None,
            error_stage=selected.get("error_stage") or None,
            error_message=selected.get("error_message") or None,
        )

    @property
    def worker(self) -> CancellableWorker | None:
        return self._worker

    @property
    def worker_running(self) -> bool:
        worker = self._worker
        if worker is None:
            return False
        try:
            return bool(worker.isRunning())
        except RuntimeError:
            return False

    def prepare_frame(
        self,
        frame: Any,
        source: str,
        window_info: dict | None,
        *,
        ocr_enabled: bool,
        sample_encoder: Callable[[Any], bytes],
        jpeg_encoder: Callable[[Any, int], bytes],
    ) -> PerceptionOcrJob | None:
        """Observe policy/window changes; return a job only for a changed frame."""
        if self._disposed:
            return None

        allowed, reason = self.privacy.evaluate_window(
            window_info, explicit=(source == "game")
        )
        if not allowed:
            self.context.clear_sensitive(
                exe=str((window_info or {}).get("exe") or ""),
                reason=reason,
            )
            self.engine.change_detector.reset()
            self.cancel()
            self._trace(
                "perception_blocked",
                source=source,
                exe=str((window_info or {}).get("exe") or "")[:80] or None,
                reason=reason,
            )
            return None

        previous_window = self.context.snapshot().get("active_window")
        normalized = self.engine.observe_window(window_info, source=source)
        if normalized is None:
            self.context.clear_sensitive(reason="foreground_window_unidentified")
            self.cancel()
            return None

        if _window_identity(previous_window) != _window_identity(normalized):
            self._trace(
                "perception_event",
                event_type="active_window_changed",
                source=source,
                exe=str(normalized.get("exe") or "")[:80] or None,
            )

        # A QThread remains the owner until its finished signal is consumed.
        # This prevents overlapping jobs during Qt signal delivery.
        if self._worker is not None:
            return None

        try:
            sample = bytes(sample_encoder(frame) or b"")
        except Exception as exc:
            self._trace(
                "perception_sample_failed", source=source,
                reason=type(exc).__name__,
            )
            return None
        if not sample or not self.engine.screen_changed(sample):
            return None

        sample_key = PerceptionEvent.fingerprint(sample.hex())
        self.context.record_event(
            "screen_changed",
            "Visible foreground content changed",
            source=source,
            dedupe_key=f"screen:{source}:{sample_key}",
        )
        self._trace(
            "perception_event",
            event_type="screen_changed",
            source=source,
            sample_id=sample_key,
        )
        if not ocr_enabled:
            self._trace("perception_change", source=source, ocr_enabled=False)
            return None

        try:
            jpeg = bytes(jpeg_encoder(frame, 65) or b"")
        except Exception as exc:
            self._trace(
                "perception_ocr_skipped",
                source=source,
                reason=type(exc).__name__,
            )
            return None
        if not jpeg:
            self._trace(
                "perception_ocr_skipped",
                source=source,
                reason="jpeg_encode_failed",
            )
            return None

        self._generation += 1
        job = PerceptionOcrJob(
            generation=self._generation,
            frame_id=sample_key,
            source=source,
            window_info=dict(normalized),
            jpeg=jpeg,
            started_at=self._clock(),
        )
        self._job = job
        self._result = None
        return job

    def bind_worker(self, job: PerceptionOcrJob, worker: CancellableWorker) -> bool:
        if (
            self._disposed
            or self._worker is not None
            or self._job is not job
            or job.generation != self._generation
        ):
            return False
        self._worker = worker
        return True

    def worker_start_failed(
        self, job: PerceptionOcrJob, worker: CancellableWorker
    ) -> bool:
        """Release an unstarted QThread reservation when start() raises."""
        if self._worker is not worker:
            return False
        if self._job is job:
            self._generation += 1
            self._job = None
            self._result = None
        try:
            running = bool(worker.isRunning())
        except RuntimeError:
            running = False
        if running:
            try:
                worker.cancel()
            except RuntimeError:
                pass
            return False
        self._worker = None
        return True

    def worker_started(self, job: PerceptionOcrJob) -> None:
        if self._job is not job or self._worker is None:
            return
        self._trace(
            "perception_ocr_started",
            source=job.source,
            exe=str(job.window_info.get("exe") or "")[:80],
            image_bytes=len(job.jpeg),
            frame_id=job.frame_id,
        )

    def recognize(self, job: PerceptionOcrJob, cancel_event=None) -> OcrResult:
        """Run OCR off-thread and preserve the source frame identity in OcrResult."""
        if job.generation != self._generation or self._disposed:
            return OcrResult(error_code="stale_job", source_frame_id=job.frame_id)
        return self.engine.recognize(
            job.jpeg,
            cancel_event,
            source_frame_id=job.frame_id,
        )

    def accept_worker_result(self, result: Any) -> bool:
        if self._job is None or self._worker is None:
            return False
        self._result = result
        return True

    def cancel(self) -> None:
        """Invalidate the result before cooperatively cancelling its worker."""
        self._generation += 1
        self._job = None
        self._result = None
        worker = self._worker
        if worker is not None:
            try:
                if worker.isRunning():
                    worker.cancel()
            except RuntimeError:
                # The finished signal still owns final disposal of this worker.
                pass

    def finish_worker(
        self,
        *,
        closing: bool,
        game_mode_enabled: bool,
    ) -> PerceptionOutcome:
        """Consume one worker result after revalidating source, window and privacy."""
        job = self._job
        result = self._result
        self._job = None
        self._result = None
        self._worker = None
        if self._disposed:
            self._shutdown_ocr_runtime()

        if job is None or job.generation != self._generation:
            return PerceptionOutcome(
                "discarded",
                source=job.source if job is not None else None,
                reason="cancelled_or_stale_job",
            )

        latency_ms = int(max(0.0, self._clock() - job.started_at) * 1000)
        if not isinstance(result, tuple) or len(result) != 2 or not result[0]:
            self._trace(
                "perception_ocr_failed",
                source=job.source,
                latency_ms=latency_ms,
            )
            return PerceptionOutcome(
                "failed", source=job.source, reason="worker_failed",
                latency_ms=latency_ms,
            )

        ocr_result = result[1]
        if not isinstance(ocr_result, OcrResult):
            self._trace(
                "perception_ocr_failed",
                source=job.source,
                latency_ms=latency_ms,
                reason="invalid_worker_result",
            )
            return PerceptionOutcome(
                "failed", source=job.source, reason="invalid_worker_result",
                latency_ms=latency_ms,
            )

        source_enabled = (
            not bool(closing)
            and (
                bool(game_mode_enabled)
                if job.source == "game"
                else bool(self.privacy.enabled)
            )
        )
        current = self.capture.foreground_window_info(
            allow_partial_identity=(job.source == "desktop")
        )
        same_window = _window_identity(current) == _window_identity(job.window_info)
        allowed, reason = self.privacy.evaluate_window(
            current, explicit=(job.source == "game")
        )

        if not source_enabled:
            self.context.clear()
        elif not allowed:
            self.context.clear_sensitive(
                exe=str((current or {}).get("exe") or ""),
                reason=reason,
            )
        elif not same_window:
            if current is None:
                self.context.clear_sensitive(
                    reason="foreground_window_unidentified"
                )
            else:
                self.engine.observe_window(current, source=job.source)

        if not source_enabled or not same_window or not allowed:
            discard_reason = (
                "capture_source_disabled" if not source_enabled
                else "foreground_changed" if not same_window
                else reason
            )
            self._trace(
                "perception_ocr_discarded",
                source=job.source,
                reason=discard_reason,
            )
            return PerceptionOutcome(
                "discarded", source=job.source, reason=discard_reason,
                latency_ms=latency_ms,
            )

        applied = self.engine.apply_ocr(
            ocr_result, current, source=job.source
        )
        if ocr_result.error_code:
            self.context.record_event(
                "ocr_unavailable",
                "Local OCR unavailable; application and window metadata remain available",
                source=job.source,
                dedupe_key=f"ocr-unavailable:{ocr_result.error_code}",
            )
        self._trace(
            "perception_ocr_result",
            source=job.source,
            applied=applied,
            text_chars=len(ocr_result.text),
            language=ocr_result.language or None,
            confidence=round(ocr_result.confidence, 3),
            error=ocr_result.error_code or None,
            engine=ocr_result.engine or getattr(self.ocr_service, "selected_engine", None),
            error_stage=ocr_result.error_stage or None,
            error_message=ocr_result.error_message or None,
            latency_ms=latency_ms,
        )
        return PerceptionOutcome(
            "completed" if applied else "no_text",
            source=job.source,
            applied=bool(applied),
            latency_ms=latency_ms,
            text_chars=len(ocr_result.text),
            language=ocr_result.language or None,
            confidence=float(ocr_result.confidence),
            error_code=ocr_result.error_code or None,
            engine=ocr_result.engine or getattr(self.ocr_service, "selected_engine", None),
            error_stage=ocr_result.error_stage or None,
            error_message=ocr_result.error_message or None,
        )

    def _shutdown_ocr_runtime(self) -> None:
        if self._ocr_shutdown:
            return
        shutdown = getattr(self.ocr_service, "shutdown", None)
        try:
            if callable(shutdown):
                shutdown()
        except Exception as exc:
            self._trace("ocr_runtime_shutdown_failed", reason=type(exc).__name__)
        finally:
            self._ocr_shutdown = True

    def dispose(self) -> bool:
        self._disposed = True
        self.cancel()
        # A stopped QThread is still owned until its queued finished signal is consumed.
        # Do not release adapter resources until the worker has fully completed.
        if self._worker is None:
            self._shutdown_ocr_runtime()
        return self._worker is None
