"""Qt-free regression coverage for local desktop perception runtime ownership."""

from kira.app.desktop_context import DesktopContext
from kira.app.perception_application import PerceptionApplicationService
from kira.perception.events import PerceptionEvent
from kira.vision_ocr import OcrResult


def window(hwnd=10, pid=20, exe="code.exe", title="project.py"):
    return {
        "hwnd": hwnd,
        "pid": pid,
        "exe": exe,
        "title": title,
        "path": r"C:\Program Files\Code.exe",
        "rect": (0, 0, 1280, 720),
    }


class FakeClock:
    def __init__(self):
        self.value = 10.0

    def __call__(self):
        return self.value


class FakePrivacy:
    enabled = True

    def __init__(self, allowed=True):
        self.allowed = allowed
        self.calls = []

    def evaluate_window(self, info, *, explicit=False):
        self.calls.append((info, explicit))
        return self.allowed and isinstance(info, dict), (
            "blocked-by-policy" if not self.allowed else ""
        )


class FakeCapture:
    def __init__(self, privacy, current=None):
        self.privacy = privacy
        self.current = current or window()
        self.calls = []

    def foreground_window_info(self, *, allow_partial_identity=False):
        self.calls.append(allow_partial_identity)
        return self.current


class FakeOcr:
    def __init__(self, result=None):
        self.result = result or OcrResult("Open project", "eng", 0.91)
        self.received_frame_ids = []

    def diagnostics(self):
        return {
            "selected_engine": "fake",
            "ready": True,
            "engines": {"fake": {"python_bindings_ready": True, "binary_ready": True}},
            "languages": {"fas": True, "eng": True},
        }

    def recognize(self, image_bytes, *, source_frame_id=""):
        self.received_frame_ids.append(source_frame_id)
        return OcrResult(
            self.result.text,
            self.result.language,
            self.result.confidence,
            self.result.error_code,
            source_frame_id=source_frame_id,
        )


class FakeWorker:
    def __init__(self):
        self.running = True
        self.cancelled = False

    def isRunning(self):
        return self.running

    def cancel(self):
        self.cancelled = True
        self.running = False


class TestPerceptionApplicationService:
    def setup_method(self):
        self.clock = FakeClock()
        self.context = DesktopContext(clock=self.clock)
        self.privacy = FakePrivacy()
        self.capture = FakeCapture(self.privacy, window())
        self.ocr = FakeOcr()
        self.service = PerceptionApplicationService(
            self.context,
            self.capture,
            ocr_service=self.ocr,
            clock=self.clock,
        )
        self.frame = object()
        self.sample = bytes(576)

    def prepare(self, *, source="desktop", info=None, ocr_enabled=True, jpeg=b"jpeg"):
        return self.service.prepare_frame(
            self.frame,
            source,
            info or self.capture.current,
            ocr_enabled=ocr_enabled,
            sample_encoder=lambda _frame: self.sample,
            jpeg_encoder=lambda _frame, quality: jpeg,
        )

    def bind_and_complete(self, job, *, result=None, closing=False, game_mode_enabled=True):
        worker = FakeWorker()
        assert self.service.bind_worker(job, worker)
        if result is None:
            result = (True, self.ocr.recognize(job.jpeg, source_frame_id=job.frame_id))
        assert self.service.accept_worker_result(result)
        self.clock.value += 0.125
        worker.running = False
        return self.service.finish_worker(
            closing=closing,
            game_mode_enabled=game_mode_enabled,
        )

    def test_worker_start_failure_releases_unstarted_worker_reservation(self):
        job = self.prepare()
        worker = FakeWorker()
        worker.running = False
        assert self.service.bind_worker(job, worker)

        assert self.service.worker_start_failed(job, worker)
        assert self.service.worker is None

        self.clock.value += 2.0
        self.sample = bytes([255]) * 576
        next_job = self.prepare()
        assert next_job is not None

    def test_changed_frame_creates_job_with_stable_identity_and_policy_event(self):
        job = self.prepare()

        assert job is not None
        assert job.source == "desktop"
        assert job.frame_id == PerceptionEvent.fingerprint(self.sample.hex())
        assert job.jpeg == b"jpeg"
        assert any(
            event.get("type", event.get("event_type")) == "screen_changed"
            for event in self.context.snapshot()["recent_events"]
        )

    def test_engine_passes_frame_fingerprint_to_the_ocr_engine(self):
        job = self.prepare()
        result = self.service.recognize(job)

        assert result.source_frame_id == job.frame_id
        assert self.ocr.received_frame_ids == [job.frame_id]

    def test_ocr_result_is_applied_only_after_full_window_identity_matches(self):
        job = self.prepare()

        outcome = self.bind_and_complete(job)

        assert outcome.status == "completed"
        assert outcome.applied
        assert outcome.latency_ms == 125
        assert "Open project" in self.context.summary()

    def test_foreground_title_change_discards_stale_ocr_and_refreshes_context(self):
        job = self.prepare()
        self.context.set_visible_text("Old OCR text", language="eng", confidence=0.8)
        self.capture.current = window(title="new-window.py")

        outcome = self.bind_and_complete(job)

        assert outcome.status == "discarded"
        assert outcome.reason == "foreground_changed"
        assert "Old OCR text" not in self.context.summary()
        assert self.context.snapshot()["active_window"]["title"] == "new-window.py"

    def test_cancel_invalidates_generation_before_worker_can_return_late_result(self):
        job = self.prepare()
        worker = FakeWorker()
        assert self.service.bind_worker(job, worker)

        self.service.cancel()

        assert worker.cancelled
        assert not self.service.accept_worker_result(
            (True, OcrResult("late text", "eng", 0.9))
        )
        outcome = self.service.finish_worker(
            closing=False, game_mode_enabled=True
        )
        assert outcome.status == "discarded"
        assert "late text" not in self.context.summary()

    def test_privacy_denial_clears_sensitive_context_and_cancels_worker(self):
        self.context.update_active_window(window())
        self.context.set_visible_text("Sensitive content", language="eng", confidence=0.9)
        self.privacy.allowed = False

        job = self.prepare()

        assert job is None
        assert self.context.summary() == ""
        assert self.context.snapshot()["active_window"] is None

    def test_game_mode_off_discards_result_and_clears_desktop_context(self):
        job = self.prepare(source="game")
        self.context.set_visible_text("Old game OCR", language="eng", confidence=0.9)

        outcome = self.bind_and_complete(job, game_mode_enabled=False)

        assert outcome.status == "discarded"
        assert outcome.reason == "capture_source_disabled"
        assert self.context.summary() == ""

    def test_shutdown_discards_result_without_applying_ocr(self):
        job = self.prepare()

        outcome = self.bind_and_complete(job, closing=True)

        assert outcome.status == "discarded"
        assert outcome.reason == "capture_source_disabled"
        assert "Open project" not in self.context.summary()

    def test_ocr_error_remains_a_visible_context_event_without_fabricated_text(self):
        self.ocr.result = OcrResult(error_code="tesseract_executable_unavailable")
        job = self.prepare()

        outcome = self.bind_and_complete(job)

        assert outcome.status == "no_text"
        assert not outcome.applied
        assert outcome.error_code == "tesseract_executable_unavailable"
        assert not self.context.snapshot().get("visible_text")
        assert any(
            event.get("type", event.get("event_type")) == "ocr_unavailable"
            for event in self.context.snapshot()["recent_events"]
        )

    def test_unchanged_frame_does_not_create_duplicate_ocr_job(self):
        first = self.prepare()
        assert first is not None
        self.clock.value += 2.0

        second = self.prepare()

        assert second is None

    def test_cancelled_worker_stays_owned_until_finished_signal_is_consumed(self):
        first = self.prepare()
        worker = FakeWorker()
        assert self.service.bind_worker(first, worker)

        # The native thread has stopped, but Qt's queued finished signal has not run.
        worker.running = False
        self.service.cancel()

        assert self.service.worker is worker
        self.clock.value += 2.0
        second = self.prepare()
        assert second is None

        outcome = self.service.finish_worker(
            closing=False, game_mode_enabled=True
        )
        assert outcome.status == "discarded"
        assert self.service.worker is None

        self.sample = bytes([255]) * 576
        third = self.prepare()
        assert third is not None
