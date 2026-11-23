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
    assert "MAX_VIDEO_FRAME_BYTES = 128 * 1024" in source
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
    assert "LIVE_VIDEO_MAX_WIDTH = 480" in source
    assert "LIVE_VIDEO_MAX_HEIGHT = 270" in source
    assert "LIVE_VIDEO_CHANNEL_LEVELS = 16" in source
    assert "LIVE_VIDEO_PALETTE_COLORS = LIVE_VIDEO_CHANNEL_LEVELS ** 3" in source
    assert "bytes(rgb.constBits()).translate(_LIVE_VIDEO_CHANNEL_LUT)" in source
    assert "palette_colors=LIVE_VIDEO_PALETTE_COLORS" in source
    assert "jpeg_quality=quality" in source
    assert "approx_kib_per_second=" in source
    assert "frame_exceeds_size_limit" in source
    assert "def set_live_video_active(self, enabled)" in source
    assert 'return 1000 if getattr(self, "_live_video_active", False) else base' in source


def test_stop_and_privacy_disable_clear_pending_video():
    voice = read("kira/ui/main_window_runtime_voice.py")
    assert "set_live_video_active(False)" in voice
    assert "clear_gemini_video_frames()" in read("kira/ui/main_window_attachments_vision.py")



def test_eye_mode_is_the_single_desktop_and_game_capture_switch():
    source = read("kira/ui/main_window_attachments_vision.py")
    assert 'privacy.set_enabled(allowed)' in source
    assert 'self._capture_desktop_frame()' in source
    assert 'def set_desktop_vision(self, enabled, *, announce=True):' in source
    assert 'return self.set_game_mode(bool(enabled), announce=announce)' in source
    assert 'def _capture_active_vision_frame(self):' in source
    dispatch = source.split('def _capture_active_vision_frame(self):', 1)[1].split('def _cancel_vision_worker', 1)[0]
    assert '_capture_desktop_frame()' in dispatch
    assert '_capture_game_frame()' not in dispatch
    assert '"eye_mode_set"' in source
    assert '"Game Mode خاموش' not in source


def test_eye_mode_control_uses_eye_identity():
    source = read("kira/ui/components/chat_composer.py")
    assert 'setProperty("kiraIconName", "eye")' in source
    assert 'make_icon("eye")' in source
    assert 'Eye Mode خاموش است' in source



def test_eye_mode_has_one_toggle_and_monitor_selection_only():
    source = read("kira/ui/main_window_composition.py")
    assert 'self.views.desktop_vision_action = None' in source
    assert 'addAction("Live Desktop Vision")' not in source
    assert 'addMenu("Eye Mode · انتخاب مانیتور")' in source
    assert 'desktop_policy.set_enabled(False)' in source



def test_eye_mode_uses_the_selected_monitor_for_chat_and_background_analysis():
    source = read("kira/ui/main_window_attachments_vision.py")
    live_attach = source.split("def _live_vision_attachment(self):", 1)[1].split("def _game_vision_attachment(self):", 1)[0]
    desktop_capture = source.split("def _capture_desktop_frame(self):", 1)[1].split("def _submit_vision_frame(self, frame, source, window_info):", 1)[0]
    assert 'if not self.context.state._game_mode_enabled:' in live_attach
    assert 'source="desktop"' in live_attach
    assert 'capture.capture_monitor_for_window(' in live_attach
    assert 'return att.image_attachment(jpeg, "eye-screen.jpg", "image/jpeg")' in live_attach
    assert 'capture.capture_monitor_for_window(' in desktop_capture
    assert 'self._submit_vision_frame(frame, "desktop", window_info)' in desktop_capture



def test_eye_mode_runtime_does_not_require_voice_session_initialization():
    source = read("kira/ui/main_window_runtime_voice.py")
    assert 'getattr(self, "_voice_session_requested", False)' in source
    assert "self._voice_session_requested\n" not in source
    assert "if self._voice_session_requested" not in source
    assert "and self._voice_session_requested" not in source


def test_eye_mode_eye_icon_asset_exists():
    source = read("assets/icons/eye.svg")
    assert '<svg' in source
    assert 'viewBox="0 0 24 24"' in source
    assert '<circle cx="12" cy="12" r="3"/>' in source
