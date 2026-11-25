"""Qt-free regression tests for Vision runtime responsibility boundaries."""

from types import SimpleNamespace

from kira.app.desktop_capture_application import DesktopCaptureApplicationService
from kira.app.vision_application import VisionApplicationService
from kira.vision_runtime_services import (
    EncodedLiveFrame,
    LiveSessionManager,
    VisionAnalysisCoordinator,
    VisionCaptureService,
)


class FakeImage:
    def isNull(self):
        return False


class FakePixmap:
    def isNull(self):
        return False

    def toImage(self):
        return FakeImage()


class FakePrivacy:
    enabled = True
    selected_monitor_id = "display-1"

    def __init__(self, allowed=True):
        self.allowed = allowed
        self.calls = []

    def evaluate_window(self, window_info, *, explicit=False):
        self.calls.append((window_info, explicit))
        return self.allowed, "blocked-by-policy" if not self.allowed else ""


class FakeCaptureAdapter:
    def __init__(self, *, window=None, privacy=None):
        self.privacy = privacy or FakePrivacy()
        self.last_game = {
            "hwnd": 1, "pid": 2, "exe": "game.exe", "title": "Arena",
            "path": "/games/game.exe",
        }
        self.poll_count = 0
        self.calls = []
        self.window = window or self.last_game

    def poll(self):
        self.poll_count += 1

    @property
    def capture_service(self):
        return self

    def list_monitors(self):
        return [SimpleNamespace(id="display-1", name="Main", primary=True)]

    def foreground_window_info(self, *, allow_partial_identity=False):
        self.calls.append(("foreground", allow_partial_identity))
        return self.window

    def capture_window(self, window_info, **kwargs):
        self.calls.append(("window", window_info, kwargs))
        return FakePixmap()

    def capture_monitor_for_window(self, window_info, **kwargs):
        self.calls.append(("monitor", window_info, kwargs))
        return FakePixmap()


class FakeVisionPolicy:
    def __init__(self, privacy):
        self.desktop_capture_application_service = privacy
        self.policy = SimpleNamespace(max_width=800, max_height=450, jpeg_quality=60)

    def capture_allowed(self, enabled, profile, *, source="game", window_info=None):
        if source == "game":
            if not enabled:
                return False
            if window_info is None:
                return True
            return self.desktop_capture_application_service.evaluate_window(
                window_info, explicit=True
            )[0]
        if source == "desktop":
            return self.desktop_capture_application_service.evaluate_window(
                window_info
            )[0]
        return False


class FakeSignal:
    def __init__(self):
        self.callbacks = []

    def connect(self, callback):
        self.callbacks.append(callback)


class FakeWorker:
    def __init__(self, router, image, **kwargs):
        self.router = router
        self.image = image
        self.kwargs = kwargs
        self.done_with_context = FakeSignal()
        self.finished = FakeSignal()
        self.running = False
        self.cancelled = False

    def start(self):
        self.running = True

    def isRunning(self):
        return self.running

    def cancel_request(self):
        self.cancelled = True
        self.running = False


class FakeTransport:
    def __init__(self, ready=True, accept=True):
        self.ready = ready
        self.accept = accept
        self.sent = []
        self.cleared = 0

    def is_gemini_live_ready(self):
        return self.ready

    def clear_gemini_video_frames(self):
        self.cleared += 1

    def send_gemini_video_frame(self, jpeg):
        self.sent.append(jpeg)
        return self.accept


class FakeGameMode:
    def permissions(self, profile):
        return {"vision_capture": True}


class FakeLiveVision:
    def __init__(self, privacy):
        self.desktop_capture_application_service = privacy
        self.allowed = True
        self.current = True
        self.released = 0
        self.committed = 0

    def capture_allowed(self, enabled, profile, *, source, window_info=None):
        return self.allowed

    def frame_context_is_current(self, context):
        return self.current

    def release_frame_budget(self, context):
        self.released += 1
        return True

    def commit_frame_budget(self, context):
        self.committed += 1
        return True


class FakeLiveCapture:
    def __init__(self, window):
        self.window = window
        self.capture_calls = []

    def foreground_window_info(self, *, allow_partial_identity=False):
        return self.window

    def capture_live_monitor_frame(self, window_info, **kwargs):
        self.capture_calls.append((window_info, kwargs))
        return FakeImage()


class FakeDesktopContext:
    def __init__(self):
        self.events = []

    def record_event(self, kind, content, **kwargs):
        self.events.append((kind, content, kwargs))

    def snapshot(self):
        return {"recent_events": tuple(self.events)}


class FakeCodec:
    def __init__(self, sample=b"sample"):
        self.sample = sample
        self.prepared = []

    def prepare_live_frame(self, frame, *, width, height):
        self.prepared.append((width, height))
        return frame, self.sample

    def encode_live_frame(self, image, max_bytes):
        return EncodedLiveFrame(b"jpeg-frame", 25, 320, 180)


class TestVisionRuntimeServiceTests:
    def test_game_capture_checks_source_before_polling_or_capture(self):
        privacy = FakePrivacy()
        adapter = FakeCaptureAdapter(privacy=privacy)
        service = VisionCaptureService(adapter, FakeVisionPolicy(privacy))

        result = service.capture_game_frame(False, "story")

        assert not result.allowed
        assert result.stage == "source"
        assert adapter.poll_count == 0
        assert adapter.calls == []

    def test_game_capture_uses_privacy_policy_and_capture_dimensions(self):
        privacy = FakePrivacy()
        adapter = FakeCaptureAdapter(privacy=privacy)
        service = VisionCaptureService(adapter, FakeVisionPolicy(privacy))

        result = service.capture_game_frame(True, "story")

        assert result.allowed
        assert isinstance(result.frame, FakeImage)
        assert adapter.poll_count == 1
        assert adapter.calls[-1][0] == "window"
        assert adapter.calls[-1][2] == {"max_width": 800, "max_height": 450}
        assert privacy.calls[-1][1] is True

    def test_desktop_privacy_block_prevents_capture(self):
        privacy = FakePrivacy(allowed=False)
        adapter = FakeCaptureAdapter(privacy=privacy)
        service = VisionCaptureService(adapter, FakeVisionPolicy(privacy))

        result = service.capture_desktop_frame()

        assert not result.allowed
        assert result.reason == "blocked-by-policy"
        assert not any(call[0] == "monitor" for call in adapter.calls)

    def test_explicit_window_capture_keeps_explicit_privacy_check(self):
        privacy = FakePrivacy()
        adapter = FakeCaptureAdapter(privacy=privacy)
        service = VisionCaptureService(adapter, FakeVisionPolicy(privacy))

        result = service.capture_explicit_window()

        assert result.allowed and isinstance(result.frame, FakeImage)
        assert privacy.calls[-1][1] is True
        assert adapter.calls[-1][0] == "window"

    def test_desktop_attachment_requires_manual_source_and_privacy_permission(self):
        privacy = FakePrivacy()
        adapter = FakeCaptureAdapter(privacy=privacy)
        service = VisionCaptureService(adapter, FakeVisionPolicy(privacy))

        blocked = service.capture_desktop_attachment(source_enabled=False)
        allowed = service.capture_desktop_attachment(source_enabled=True)

        assert not blocked.allowed and blocked.stage == "source"
        assert allowed.allowed and isinstance(allowed.frame, FakeImage)
        assert adapter.calls[-1][0] == "monitor"

    def test_analysis_coordinator_queues_only_the_selected_analysis_route(self):
        vision = VisionApplicationService()
        encoded = []

        def encode(frame, quality):
            encoded.append((frame, quality))
            return b"jpeg-analysis", b"visual-sample"

        coordinator = VisionAnalysisCoordinator(vision, encode)
        context, decision = coordinator.submit_frame(
            FakeImage(),
            "game",
            {"hwnd": 3, "pid": 4, "exe": "game.exe", "title": "Arena"},
            session_id="session-a",
            live_ready=False,
            analysis_allowed=True,
            interval_seconds=1.0,
            max_frames_per_minute=10,
        )

        job = coordinator.take_next_job("session-a")
        assert decision.route == vision.frame_orchestrator.ANALYSIS
        assert job.context == context
        assert job.payload == b"jpeg-analysis"
        assert job.visual_sample == b"visual-sample"
        assert encoded[0][1] == vision.policy.jpeg_quality

    def test_live_route_does_not_enqueue_an_analysis_job_for_the_same_frame(self):
        vision = VisionApplicationService()
        coordinator = VisionAnalysisCoordinator(
            vision, lambda _frame, _quality: (b"jpeg", b"sample")
        )

        context, decision = coordinator.submit_frame(
            FakeImage(),
            "desktop",
            {"hwnd": 3, "pid": 4, "exe": "browser.exe", "title": "Work"},
            session_id="session-a",
            live_ready=True,
            analysis_allowed=True,
            interval_seconds=1.0,
            max_frames_per_minute=10,
        )

        assert context is not None
        assert decision.route == vision.frame_orchestrator.LIVE
        assert coordinator.take_next_job("session-a") is None

    def test_session_cancellation_invalidates_context_and_pending_job(self):
        vision = VisionApplicationService()
        coordinator = VisionAnalysisCoordinator(
            vision, lambda _frame, _quality: (b"jpeg", b"sample")
        )
        context, _decision = coordinator.submit_frame(
            FakeImage(),
            "game",
            {"hwnd": 3, "pid": 4, "exe": "game.exe", "title": "Arena"},
            session_id="session-a",
            live_ready=False,
            analysis_allowed=True,
            interval_seconds=1.0,
            max_frames_per_minute=10,
        )

        coordinator.cancel_session("session-a")

        assert not coordinator.is_current(context)
        assert coordinator.take_next_job("session-a") is None

    def test_dispatch_worker_is_bound_to_session_context_and_cancellable(self):
        privacy = DesktopCaptureApplicationService()
        privacy.set_enabled(True)
        vision = VisionApplicationService(desktop_capture_application_service=privacy)
        identity = {
            "hwnd": 3, "pid": 4, "exe": "browser.exe", "title": "Work",
            "path": "/apps/browser", "rect": (0, 0, 1280, 720),
        }
        capture = VisionCaptureService(
            FakeCaptureAdapter(window=identity, privacy=privacy), vision
        )
        coordinator = VisionAnalysisCoordinator(
            vision, lambda _frame, _quality: (b"jpeg", b"sample"),
            capture_service=capture,
        )
        identity = {
            "hwnd": 3, "pid": 4, "exe": "browser.exe", "title": "Work",
            "path": "/apps/browser",
            "rect": (0, 0, 1280, 720),
        }
        context, _decision = coordinator.submit_frame(
            FakeImage(), "desktop", identity,
            session_id="session-a", live_ready=False, analysis_allowed=True,
            interval_seconds=1.0, max_frames_per_minute=10,
        )
        relay = SimpleNamespace(
            game_vision_done_with_context=object(),
            game_vision_finished=object(),
        )
        session = SimpleNamespace(
            status="active",
            busy=False,
            client=SimpleNamespace(busy=False),
            vision_router=object(),
            relay=relay,
            _vision_worker=None,
            _vision_frame_context=None,
        )
        errors = []
        worker = coordinator.dispatch_next(
            session,
            session_id="session-a",
            closing=False,
            game_mode_enabled=False,
            game_mode_profile=None,
            speech_active=False,
            settings={},
            worker_factory=FakeWorker,
            attachment_factory=lambda payload, name, mime: {
                "data": payload, "name": name, "mime_type": mime,
            },
            dispose_session=lambda _session: None,
            report_error=errors.append,
        )

        assert worker is session._vision_worker
        assert worker.running
        assert worker.done_with_context.callbacks == [relay.game_vision_done_with_context]
        assert worker.finished.callbacks == [relay.game_vision_finished]
        assert session._vision_frame_context == context
        assert not errors

        coordinator.cancel_worker(session, "session-a")
        assert worker.cancelled
        assert session._vision_frame_context is None
        assert not coordinator.is_current(context)

    def test_live_session_sends_changed_frames_and_skips_identical_frames(self):
        privacy = FakePrivacy()
        capture = FakeLiveCapture({
            "hwnd": 1, "pid": 2, "exe": "browser.exe", "title": "Work",
            "path": "/apps/browser",
        })
        vision = FakeLiveVision(privacy)
        transport = FakeTransport()
        codec = FakeCodec()
        manager = LiveSessionManager(
            {"eye_live_min_interval_seconds": 1, "eye_live_max_frames_per_minute": 10},
            capture,
            vision,
            FakeGameMode(),
            transport,
            codec,
            max_frame_bytes_provider=lambda: 1024,
        )

        first_context = SimpleNamespace(frame_id="frame-first", session_id="session-a")
        second_context = SimpleNamespace(frame_id="frame-second", session_id="session-a")
        first = manager.stream_frame(
            None, "desktop", capture.window,
            frame_context=first_context,
            game_mode_enabled=False, game_mode_profile=None,
        )
        second = manager.stream_frame(
            None, "desktop", capture.window,
            frame_context=second_context,
            game_mode_enabled=False, game_mode_profile=None,
        )

        assert first is True
        assert second is False
        assert transport.sent == [b"jpeg-frame"]
        assert vision.committed == 1
        assert vision.released == 1
        assert codec.prepared == [(480, 270), (480, 270)]
        assert len(capture.capture_calls) == 2

    def test_live_transport_rejection_does_not_commit_selector_reference(self):
        privacy = FakePrivacy()
        capture = FakeLiveCapture({
            "hwnd": 1, "pid": 2, "exe": "browser.exe", "title": "Work",
            "path": "/apps/browser",
        })
        vision = FakeLiveVision(privacy)
        transport = FakeTransport(accept=False)
        manager = LiveSessionManager(
            {}, capture, vision, FakeGameMode(), transport, FakeCodec(),
            max_frame_bytes_provider=lambda: 1024,
        )

        rejected = manager.stream_frame(
            None, "desktop", capture.window,
            game_mode_enabled=False, game_mode_profile=None,
        )
        transport.accept = True
        accepted = manager.stream_frame(
            None, "desktop", capture.window,
            game_mode_enabled=False, game_mode_profile=None,
        )

        assert rejected is False
        assert accepted is True
        assert vision.committed == 0
        assert manager.selector.snapshot()["sent"] == 1

    def test_live_privacy_rejection_releases_reservation_and_clears_stream(self):
        privacy = FakePrivacy()
        privacy.enabled = False
        capture = FakeLiveCapture({"hwnd": 1, "pid": 2, "exe": "browser.exe"})
        vision = FakeLiveVision(privacy)
        transport = FakeTransport()
        manager = LiveSessionManager(
            {}, capture, vision, FakeGameMode(), transport, FakeCodec(),
            max_frame_bytes_provider=lambda: 1024,
        )
        reservation = object()

        result = manager.stream_frame(
            FakeImage(), "desktop", capture.window,
            frame_context=reservation,
            game_mode_enabled=False, game_mode_profile=None,
        )

        assert result is False
        assert vision.released == 1
        assert transport.cleared == 1
        assert transport.sent == []

    def test_live_budget_is_clamped_and_invalid_settings_use_selector_defaults(self):
        manager = LiveSessionManager(
            {
                "eye_live_min_interval_seconds": -20,
                "eye_live_max_frames_per_minute": 999,
            },
            FakeLiveCapture({}),
            FakeLiveVision(FakePrivacy()),
            FakeGameMode(),
            FakeTransport(),
            FakeCodec(),
            max_frame_bytes_provider=lambda: 1024,
        )
        assert manager.budget_values() == (1.0, 60)

        manager._settings["eye_live_min_interval_seconds"] = "invalid"
        manager._settings["eye_live_max_frames_per_minute"] = None
        interval, per_minute = manager.budget_values()
        assert interval >= 1.0
        assert 1 <= per_minute <= 60

    def test_desktop_result_survives_foreground_switch_and_records_observation(self):
        privacy = DesktopCaptureApplicationService()
        privacy.set_enabled(True)
        captured = {
            "hwnd": 10, "pid": 20, "exe": "browser.exe", "title": "Captured",
            "path": "/apps/browser", "rect": (0, 0, 1280, 720),
        }
        current = {
            "hwnd": 11, "pid": 21, "exe": "editor.exe", "title": "Now active",
            "path": "/apps/editor", "rect": (0, 0, 1280, 720),
        }
        vision = VisionApplicationService(desktop_capture_application_service=privacy)
        capture = VisionCaptureService(FakeCaptureAdapter(window=current, privacy=privacy), vision)
        coordinator = VisionAnalysisCoordinator(
            vision, lambda _frame, _quality: (b"jpeg", b"sample"), capture_service=capture
        )
        context, _decision = coordinator.submit_frame(
            FakeImage(), "desktop", captured, session_id="session-desktop",
            live_ready=False, analysis_allowed=True,
            interval_seconds=1.0, max_frames_per_minute=10,
        )
        session = SimpleNamespace(_vision_frame_context=context)
        history = FakeDesktopContext()
        outcome = coordinator.process_result(
            True, "A visible editor window", 42, session,
            session_id="session-desktop", closing=False,
            game_mode_enabled=True, game_mode_profile=None,
            desktop_context_service=history,
            fingerprint=lambda _message: "stable-fingerprint",
        )
        assert outcome.status == "ready"
        assert outcome.same_window is False
        assert outcome.message == "A visible editor window"
        assert history.events[0][0] == "visual_observation"
        assert history.events[0][2]["dedupe_key"] == "visual:stable-fingerprint"
        assert session._vision_frame_context is None

    def test_stale_result_generation_is_discarded_without_consuming_result(self):
        privacy = DesktopCaptureApplicationService()
        privacy.set_enabled(True)
        window = {
            "hwnd": 1, "pid": 2, "exe": "browser.exe", "title": "Work",
            "path": "/apps/browser", "rect": (0, 0, 1280, 720),
        }
        vision = VisionApplicationService(desktop_capture_application_service=privacy)
        capture = VisionCaptureService(FakeCaptureAdapter(window=window, privacy=privacy), vision)
        coordinator = VisionAnalysisCoordinator(
            vision, lambda _frame, _quality: (b"jpeg", b"sample"), capture_service=capture
        )
        context, _decision = coordinator.submit_frame(
            FakeImage(), "desktop", window, session_id="session-stale",
            live_ready=False, analysis_allowed=True,
            interval_seconds=1.0, max_frames_per_minute=10,
        )
        session = SimpleNamespace(_vision_frame_context=context)
        coordinator.cancel_session("session-stale")
        history = FakeDesktopContext()
        outcome = coordinator.process_result(
            True, "Must not be consumed", 10, session,
            session_id="session-stale", closing=False,
            game_mode_enabled=True, game_mode_profile=None,
            desktop_context_service=history,
            fingerprint=lambda _message: "unused",
        )
        assert outcome.status == "discarded"
        assert outcome.reason == "stale_session_generation"
        assert session._vision_frame_context is None
        assert history.events == []
        assert vision.last_note == ""

