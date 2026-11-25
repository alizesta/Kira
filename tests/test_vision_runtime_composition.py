"""Composition tests for the single-owner Vision runtime graph."""
from types import SimpleNamespace

import pytest

from kira.app.vision_runtime import VisionRuntimeServices


class FakeCapture:
    def __init__(self):
        self.capture_service = SimpleNamespace(
            list_monitors=lambda: [],
            foreground_window_info=lambda **_kwargs: None,
        )


class FakeCodec:
    def encode_analysis_frame(self, frame, quality):
        return b"jpeg", b"sample"

    def encode_jpeg(self, frame, quality):
        return b"jpeg"


class FakeTransport:
    def __init__(self):
        self.clears = 0

    def is_gemini_live_ready(self):
        return False

    def clear_gemini_video_frames(self):
        self.clears += 1

    def send_gemini_video_frame(self, jpeg):
        return False


class FakeVision:
    desktop_capture_application_service = SimpleNamespace(
        enabled=False, selected_monitor_id=""
    )

    def capture_allowed(self, *args, **kwargs):
        return False


class FakeGameMode:
    def permissions(self, profile):
        return {"vision_capture": False}


class FakeDesktopContext:
    pass


def make_runtime():
    transport = FakeTransport()
    runtime = VisionRuntimeServices(
        game_mode_adapter=FakeCapture(),
        game_mode_application_service=FakeGameMode(),
        vision_application_service=FakeVision(),
        desktop_context_application_service=FakeDesktopContext(),
        settings={},
        frame_codec=FakeCodec(),
        live_transport=transport,
        max_frame_bytes_provider=lambda: 1024,
    )
    return runtime, transport


def test_runtime_composes_one_shared_capture_boundary_for_all_consumers():
    runtime, _transport = make_runtime()

    assert runtime.analysis_coordinator._capture is runtime.capture_service
    assert runtime.live_session_manager._capture is runtime.capture_service
    assert runtime.perception_application_service.capture is runtime.capture_service
    assert runtime.snapshot_service is not runtime.capture_service


def test_runtime_dispose_is_idempotent_and_clears_live_transport():
    runtime, transport = make_runtime()

    assert runtime.dispose() is True
    assert runtime.dispose() is True
    assert transport.clears == 1


def test_runtime_requires_complete_composition_dependencies():
    with pytest.raises(TypeError):
        VisionRuntimeServices(
            game_mode_adapter=None,
            game_mode_application_service=FakeGameMode(),
            vision_application_service=FakeVision(),
            desktop_context_application_service=FakeDesktopContext(),
            settings={},
            frame_codec=FakeCodec(),
            live_transport=FakeTransport(),
            max_frame_bytes_provider=lambda: 1024,
        )


def test_runtime_provider_is_lazy_and_reuses_its_single_instance():
    from kira.app.vision_runtime import VisionRuntimeProvider

    builds = []
    runtime, _transport = make_runtime()
    provider = VisionRuntimeProvider(lambda: (builds.append(runtime) or runtime))

    assert builds == []
    assert provider.peek() is None
    assert provider.get() is runtime
    assert provider.get() is runtime
    assert builds == [runtime]


def test_runtime_provider_disposes_without_eager_construction():
    from kira.app.vision_runtime import VisionRuntimeProvider

    provider = VisionRuntimeProvider(lambda: pytest.fail("must stay lazy"))

    assert provider.dispose() is True
    with pytest.raises(RuntimeError):
        provider.get()
