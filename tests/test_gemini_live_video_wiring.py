"""Static contracts for Gemini Live visual stream wiring."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return (ROOT / path).read_text(encoding="utf-8")


def test_worker_uses_bounded_video_on_existing_live_session():
    source = read("kira/gemini_live.py")
    assert "class LiveVideoFrameGate" in source
    assert "MAX_VIDEO_CHUNKS = 1" in source
    assert "VIDEO_FRAME_INTERVAL_SECONDS = 1.0" in source
    assert 'video=types.Blob(data=chunk, mime_type="image/jpeg")' in source
    assert "async with self._send_lock" in source
    assert "def clear_video_frames(self)" in source


def test_runtime_bridge_requires_connected_gemini_audio_session():
    source = read("kira/ui/main_window_runtime_voice.py")
    assert "def is_gemini_live_ready(self)" in source
    assert 'getattr(self, "_voice_mode", "") == "gemini_live"' in source
    assert "worker.video_ready" in source
    assert "def send_gemini_video_frame(self, jpeg: bytes)" in source


def test_live_stream_uses_full_monitor_and_privacy_rechecks():
    source = read("kira/ui/main_window_attachments_vision.py")
    assert "def _maybe_stream_gemini_live_frame" in source
    assert "capture_monitor_for_window(" in source
    assert "service.capture_allowed(" in source
    assert "LIVE_VIDEO_CHANGE_THRESHOLD" in source
    assert "def set_live_video_active(self, enabled)" in source
    assert 'return 1000 if getattr(self, "_live_video_active", False) else base' in source


def test_stop_and_privacy_disable_clear_pending_video():
    voice = read("kira/ui/main_window_runtime_voice.py")
    assert "set_live_video_active(False)" in voice
    assert "clear_gemini_video_frames()" in read("kira/ui/main_window_attachments_vision.py")
