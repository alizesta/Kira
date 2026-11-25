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
    assert "approx_kib_per_frame=" in source
    assert "min_interval_seconds=selector.policy.min_interval_seconds" in source
    assert "max_frames_per_minute=selector.policy.max_frames_per_minute" in source
    assert ", fps=1," not in source
    assert "gate_max_fps=1" in source
    assert "frame_exceeds_size_limit" in source
    assert "def set_live_video_active(self, enabled)" in source
    assert 'return 1000 if getattr(self, "_live_video_active", False) else base' in source


def test_vision_controller_has_no_undefined_names():
    """A NameError inside the Live try/except is swallowed and silently stops all video."""
    import ast
    import builtins

    tree = ast.parse(read("kira/ui/main_window_attachments_vision.py"))
    defined = set(dir(builtins))
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            defined.update((alias.asname or alias.name).split(".")[0] for alias in node.names)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            defined.add(node.name)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            defined.add(node.id)
        elif isinstance(node, ast.arg):
            defined.add(node.arg)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            defined.add(node.name)
    used = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
    assert sorted(used - defined) == []


def test_live_system_instruction_uses_the_configured_budget():
    source = read("kira/ui/main_window_runtime_voice.py")
    assert ".live_video_budget()" in source
    assert "at least {interval_seconds:g} seconds apart" in source
    assert "no more than {max_frames_per_minute} times in any rolling 60-second window" in source


def test_live_frame_decision_is_made_by_the_selector_and_committed_after_queueing():
    source = read("kira/ui/main_window_attachments_vision.py")
    assert "from ..gemini_live import MAX_VIDEO_FRAME_BYTES" in source
    assert "decision = selector.evaluate(sample)" in source
    queued = source.split("if not runtime.send_gemini_video_frame(jpeg):", 1)[1]
    assert queued.lstrip().startswith("return False")
    assert "selector.commit(sample)" in queued
    assert "self._live_selector().reset()" in source.split("def set_live_video_active", 1)[1]


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


def test_live_reuses_the_captured_frame_and_preserves_live_resolution_limit():
    source = read("kira/ui/main_window_attachments_vision.py")
    live = source.split("def _maybe_stream_gemini_live_frame", 1)[1].split(
        "def _queue_perception_ocr", 1
    )[0]
    assert "frame_image = _frame.scaled(" in live
    assert "LIVE_VIDEO_MAX_WIDTH, LIVE_VIDEO_MAX_HEIGHT" in live
    assert "frame_context=frame_context" in source


def test_one_frame_has_one_central_cloud_route_and_a_bounded_analysis_queue():
    source = read("kira/ui/main_window_attachments_vision.py")
    orchestrator = read("kira/vision_orchestrator.py")
    assert "decision = orchestrator.decide(" in source
    assert "if decision.route != orchestrator.ANALYSIS:" in source
    assert "FrameJob(frame_context, jpeg, visual_sample)" in source
    assert "service.enqueue_frame(" in source
    assert "def _dispatch_next_vision_job(self):" in source
    assert "job = service.take_next_frame(session_id)" in source
    assert "def take_next(self, session_id: str | None = None)" in orchestrator
    assert "if len(session_pending) >= self.capacity:" in orchestrator
    assert "self._pending.remove(session_pending[0])" in orchestrator
    assert "worker_running=False" in source


def test_frame_result_and_cancellation_are_bound_to_owning_session_generation():
    source = read("kira/ui/main_window_attachments_vision.py")
    relay = read("kira/ui/main_window_support.py")
    orchestrator = read("kira/vision_orchestrator.py")
    assert "session._vision_frame_context = frame_context" in source
    assert "service.frame_orchestrator.is_current(frame_context)" in source
    assert "service.frame_orchestrator.cancel_session(session_id)" in source
    assert 'self._run("_dispatch_next_vision_job")' in relay
    assert "def is_current(self, context: FrameContext)" in orchestrator
    assert "generation=self._generations.setdefault(key, 0)" in orchestrator


def test_desktop_live_and_analysis_reuse_the_same_capture_result():
    source = read("kira/ui/main_window_attachments_vision.py")
    capture = source.split("def _capture_desktop_frame(self):", 1)[1].split(
        "def _submit_vision_frame(self, frame, source, window_info):", 1
    )[0]
    live = source.split("def _maybe_stream_gemini_live_frame", 1)[1].split(
        "def _queue_perception_ocr", 1
    )[0]
    assert "frame_context, decision = self._submit_vision_frame(frame, \"desktop\", window_info)" in capture
    assert "self._maybe_stream_gemini_live_frame(" in capture
    assert "frame, \"desktop\", window_info, frame_context=frame_context" in capture
    assert "frame_image = _frame.scaled(" in live
    assert "capture.capture_monitor_for_window(" in live
