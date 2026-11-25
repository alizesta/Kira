"""Qt-free runtime services for desktop Vision capture, routing and Live sessions.

The UI controller owns Qt widgets and the Qt worker adapter. These services own
capture policy, frame-route lifecycle, worker admission and Live-session policy.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Protocol

from .live_video_selector import LiveFrameSelector, SelectorPolicy
from .vision_orchestrator import FrameJob


def _service_value(service: Any, name: str) -> Any:
    """Read a concrete or lazily proxied non-callable service attribute."""
    value_reader = getattr(service, "value", None)
    if callable(value_reader):
        return value_reader(name)
    return getattr(service, name)


@dataclass(frozen=True)
class CaptureResult:
    source: str
    window_info: dict[str, Any] | None
    frame: Any = None
    allowed: bool = True
    reason: str | None = None
    stage: str | None = None


@dataclass(frozen=True)
class EncodedLiveFrame:
    jpeg: bytes
    quality: int
    width: int
    height: int


class VisionWorkerSignal(Protocol):
    def connect(self, callback: Callable[..., Any]) -> Any: ...


class VisionWorkerContract(Protocol):
    """Only worker/UI boundary: result-with-context and thread completion signals."""

    done_with_context: VisionWorkerSignal
    finished: VisionWorkerSignal

    def cancel_request(self) -> None: ...
    def isRunning(self) -> bool: ...
    def start(self) -> None: ...


class LiveFrameTransport(Protocol):
    """Transport capability required by LiveSessionManager."""

    def is_gemini_live_ready(self) -> bool: ...
    def clear_gemini_video_frames(self) -> None: ...
    def send_gemini_video_frame(self, jpeg: bytes) -> bool: ...


def _valid_frame(frame: Any) -> bool:
    if frame is None:
        return False
    is_null = getattr(frame, "isNull", None)
    return not callable(is_null) or not bool(is_null())


def _to_image(pixmap: Any) -> Any:
    if not _valid_frame(pixmap):
        return None
    to_image = getattr(pixmap, "toImage", None)
    return to_image() if callable(to_image) else pixmap


def _window_identity(window_info: dict | None) -> tuple[Any, ...]:
    info = window_info if isinstance(window_info, dict) else {}
    return (
        int(info.get("hwnd") or 0),
        int(info.get("pid") or 0),
        str(info.get("exe") or "").casefold(),
        str(info.get("title") or "").strip(),
        str(info.get("path") or "").casefold(),
    )


class VisionCaptureService:
    """Capture policy and adapter boundary; contains no Qt or MainWindow dependency."""

    def __init__(self, game_mode_adapter: Any, vision_service: Any) -> None:
        self._game_mode_adapter = game_mode_adapter
        self._capture = game_mode_adapter.capture_service
        self._vision = vision_service

    @property
    def privacy(self):
        return _service_value(self._vision, "desktop_capture_application_service")

    def list_monitors(self):
        return self._capture.list_monitors()

    def foreground_window_info(self, *, allow_partial_identity: bool = False):
        return self._capture.foreground_window_info(
            allow_partial_identity=allow_partial_identity
        )

    def capture_game_frame(self, enabled: bool, profile: str | None) -> CaptureResult:
        if not self._vision.capture_allowed(enabled, profile, source="game"):
            return CaptureResult(
                "game", None, allowed=False, reason="source_disabled", stage="source"
            )

        self._game_mode_adapter.poll()
        window_info = self._game_mode_adapter.last_game
        if not isinstance(window_info, dict) or not window_info:
            return CaptureResult(
                "game", None, allowed=False,
                reason="foreground_game_unavailable", stage="capture",
            )
        if not self._vision.capture_allowed(
            enabled, profile, source="game", window_info=window_info
        ):
            _allowed, reason = self.privacy.evaluate_window(
                window_info, explicit=True
            )
            return CaptureResult(
                "game", window_info, allowed=False,
                reason=reason or "window_not_permitted", stage="privacy",
            )

        policy = _service_value(self._vision, "policy")
        pixmap = self._capture.capture_window(
            window_info,
            max_width=policy.max_width,
            max_height=policy.max_height,
        )
        return CaptureResult("game", window_info, _to_image(pixmap))

    def capture_desktop_frame(self) -> CaptureResult:
        privacy = self.privacy
        window_info = self.foreground_window_info(allow_partial_identity=True)
        allowed, reason = privacy.evaluate_window(window_info)
        if not allowed or not self._vision.capture_allowed(
            True, None, source="desktop", window_info=window_info
        ):
            return CaptureResult(
                "desktop", window_info, allowed=False,
                reason=reason or "vision_service_inactive", stage="privacy",
            )

        policy = _service_value(self._vision, "policy")
        pixmap = self._capture.capture_monitor_for_window(
            window_info,
            monitor_id=_service_value(privacy, "selected_monitor_id") or None,
            max_width=policy.max_width,
            max_height=policy.max_height,
        )
        return CaptureResult("desktop", window_info, _to_image(pixmap))

    def capture_explicit_window(self) -> CaptureResult:
        privacy = self.privacy
        window_info = self.foreground_window_info()
        allowed, reason = privacy.evaluate_window(window_info, explicit=True)
        if not allowed or not self._vision.capture_allowed(
            False, None, source="desktop", window_info=window_info, explicit=True
        ):
            return CaptureResult(
                "desktop", window_info, allowed=False,
                reason=reason or "vision_service_inactive", stage="privacy",
            )

        policy = _service_value(self._vision, "policy")
        pixmap = self._capture.capture_window(
            window_info,
            monitor_id=_service_value(privacy, "selected_monitor_id") or None,
            max_width=policy.max_width,
            max_height=policy.max_height,
        )
        return CaptureResult("desktop", window_info, _to_image(pixmap))

    def capture_desktop_attachment(self, *, source_enabled: bool) -> CaptureResult:
        """Capture a user-requested Eye Mode attachment after both source gates pass."""
        if not source_enabled:
            return CaptureResult(
                "desktop", None, allowed=False,
                reason="eye_mode_source_disabled", stage="source",
            )
        privacy = self.privacy
        if not _service_value(privacy, "enabled"):
            return CaptureResult(
                "desktop", None, allowed=False,
                reason="eye_mode_source_disabled", stage="source",
            )
        window_info = self.foreground_window_info(allow_partial_identity=True)
        allowed, reason = self.privacy.evaluate_window(window_info)
        if not allowed or not self._vision.capture_allowed(
            False, None, source="desktop", window_info=window_info
        ):
            return CaptureResult(
                "desktop", window_info, allowed=False,
                reason=reason or "privacy_or_source_disabled", stage="privacy",
            )
        policy = _service_value(self._vision, "policy")
        pixmap = self._capture.capture_monitor_for_window(
            window_info,
            monitor_id=_service_value(privacy, "selected_monitor_id") or None,
            max_width=policy.max_width,
            max_height=policy.max_height,
        )
        return CaptureResult("desktop", window_info, _to_image(pixmap))

    def capture_live_monitor_frame(
        self,
        window_info: dict | None,
        *,
        monitor_id: str | None,
        max_width: int,
        max_height: int,
    ):
        pixmap = self._capture.capture_monitor_for_window(
            window_info,
            monitor_id=monitor_id or None,
            max_width=max_width,
            max_height=max_height,
        )
        return _to_image(pixmap)


@dataclass(frozen=True)
class VisionResultOutcome:
    """Qt-free result of validating and consuming one immutable Vision result."""

    status: str
    source: str | None = None
    reason: str | None = None
    message: str | None = None
    latency_ms: int = 0
    stats: dict[str, Any] | None = None
    same_window: bool | None = None
    history_events: int | None = None


class VisionAnalysisCoordinator:
    """Qt-free owner of frame routing, queue admission and worker lifecycle."""

    def __init__(
        self,
        vision_service: Any,
        frame_encoder: Callable[[Any, int], tuple[bytes, bytes]],
        *,
        capture_service: VisionCaptureService | None = None,
        trace: Callable[..., Any] | None = None,
    ) -> None:
        self._vision = vision_service
        self._frame_encoder = frame_encoder
        self._capture = capture_service
        self._trace = trace or (lambda *_args, **_kwargs: None)

    def submit_frame(
        self,
        frame: Any,
        source: str,
        window_info: dict | None,
        *,
        session_id: str,
        live_ready: bool,
        analysis_allowed: bool,
        interval_seconds: float,
        max_frames_per_minute: int,
    ):
        if not _valid_frame(frame):
            return None, None

        orchestrator = _service_value(self._vision, "frame_orchestrator")
        orchestrator.configure_budget(
            max_frames_per_minute=max_frames_per_minute,
            min_interval_seconds=interval_seconds,
            session_id=session_id,
        )
        context = self._vision.create_frame_context(
            session_id, source, window_info
        )
        decision = self._vision.route_frame(
            context,
            live_ready=live_ready,
            analysis_allowed=analysis_allowed,
        )
        self._trace(
            "frame_route_decided",
            frame_id=context.frame_id,
            session_id=context.session_id,
            source=source,
            route=decision.route,
            reason=decision.reason,
            generation=context.generation,
        )
        if decision.route != orchestrator.ANALYSIS:
            return context, decision

        try:
            payload, visual_sample = self._frame_encoder(
                frame, int(_service_value(self._vision, "policy").jpeg_quality)
            )
            payload = bytes(payload or b"")
            visual_sample = bytes(visual_sample or b"")
            if not payload:
                self._vision.release_frame_budget(context)
                return context, decision
            if not self._vision.enqueue_frame(
                FrameJob(context, payload, visual_sample)
            ):
                self._vision.release_frame_budget(context)
        except Exception:
            self._vision.discard_frame(context)
            raise
        return context, decision

    def take_next_job(self, session_id: str):
        return self._vision.take_next_frame(session_id)

    def is_current(self, context: Any) -> bool:
        return self._vision.frame_context_is_current(context)

    def release(self, context: Any) -> bool:
        return self._vision.release_frame_budget(context)

    def discard(self, context: Any) -> bool:
        return self._vision.discard_frame(context)

    def commit(self, context: Any) -> bool:
        return self._vision.commit_frame_budget(context)

    def cancel_session(self, session_id: str) -> int:
        return self._vision.cancel_frame_session(session_id)

    def cancel_worker(self, session: Any, session_id: str) -> None:
        """Invalidate queued and in-flight generations before interrupting the worker."""
        self.cancel_session(session_id)
        session._vision_frame_context = None
        worker = getattr(session, "_vision_worker", None)
        if worker is not None and worker.isRunning():
            worker.cancel_request()

    def dispatch_next(
        self,
        session: Any,
        *,
        session_id: str,
        closing: bool,
        game_mode_enabled: bool,
        game_mode_profile: str | None,
        speech_active: bool,
        settings: Any,
        worker_factory: Callable[..., VisionWorkerContract],
        attachment_factory: Callable[..., dict],
        dispose_session: Callable[[Any], Any],
        report_error: Callable[[str], Any],
    ):
        """Admit a frame and bind its worker to its ChatSession, without Qt imports."""
        if session is None:
            return None
        if closing:
            self.cancel_worker(session, session_id)
            return None

        status = getattr(session, "status", "")
        if status in ("closing", "closed", "failed"):
            self.cancel_worker(session, session_id)
            active = getattr(session, "_vision_worker", None)
            if status == "closing" and (active is None or not active.isRunning()):
                dispose_session(session)
            return None

        active = getattr(session, "_vision_worker", None)
        if active is not None and active.isRunning():
            return None

        job = self.take_next_job(session_id)
        if job is None:
            return None

        context = job.context
        if session_id != context.session_id or not self.is_current(context):
            self.release(context)
            self._trace(
                "analysis_discarded",
                frame_id=context.frame_id,
                session_id=context.session_id,
                source=context.source,
                reason="stale_session_context",
            )
            return None

        source = context.source
        enabled = game_mode_enabled if source == "game" else True
        profile = game_mode_profile if source == "game" else None
        if self._capture is None:
            self.release(context)
            raise RuntimeError("VisionAnalysisCoordinator requires a capture service for worker dispatch")
        window_info = self._capture.foreground_window_info(
            allow_partial_identity=(source == "desktop")
        )
        if not isinstance(window_info, dict):
            self.release(context)
            self._trace(
                "analysis_discarded", frame_id=context.frame_id,
                session_id=context.session_id, source=source,
                reason="foreground_window_unavailable",
            )
            return None
        if source == "game" and _window_identity(window_info)[:2] != context.window_identity[:2]:
            self.release(context)
            self._trace(
                "analysis_discarded", frame_id=context.frame_id,
                session_id=context.session_id, source=source,
                reason="foreground_window_changed",
            )
            return None
        try:
            eligible = self._vision.should_analyze(
                enabled=enabled,
                profile=profile,
                frame_available=True,
                worker_running=False,
                chat_busy=session.busy,
                provider_busy=session.client.busy,
                speech_active=speech_active,
                source=source,
                window_info=window_info,
            )
            if not eligible:
                self.release(context)
                return None
            if not self._vision.accept_frame(
                job.payload,
                visual_sample=job.visual_sample,
                session_id=session_id,
            ):
                self.release(context)
                return None

            image_name = "desktop-screen.jpg" if source == "desktop" else "game-screen.jpg"
            image = attachment_factory(job.payload, image_name, "image/jpeg")
            router = getattr(session, "vision_router", None)
            if router is None:
                raise RuntimeError("session-owned Vision router is unavailable")
            worker = worker_factory(
                router,
                image,
                ocr_enabled=(
                    bool(settings.get("vision_ocr_in_game_mode", False))
                    if source == "game" else False
                ),
                frame_context=context,
            )
            session._vision_session = session
            session._vision_frame_context = context
            session._vision_worker = worker
            self._trace(
                "analysis_started",
                frame_id=context.frame_id,
                session_id=context.session_id,
                source=source,
                jpeg_bytes=len(job.payload),
            )
            worker.done_with_context.connect(session.relay.game_vision_done_with_context)
            worker.finished.connect(session.relay.game_vision_finished)
            worker.start()
            self.commit(context)
            return worker
        except Exception as exc:
            self.release(context)
            self._trace(
                "analysis_error",
                frame_id=context.frame_id,
                session_id=context.session_id,
                source=source,
                error=f"{type(exc).__name__}: {exc}",
            )
            report_error(f"Vision: آماده‌سازی فریم ناموفق بود: {str(exc)[:180]}")
            return None


    def process_result(
        self,
        ok: bool,
        result: Any,
        latency_ms: int,
        session: Any,
        *,
        session_id: str,
        closing: bool,
        game_mode_enabled: bool,
        game_mode_profile: str | None,
        desktop_context_service: Any,
        fingerprint: Callable[[str], str],
        frame_context: Any = None,
    ) -> VisionResultOutcome:
        """Apply result freshness/privacy policy and record observations without Qt."""
        session_id = str(session_id or "")
        if frame_context is None:
            frame_context = getattr(session, "_vision_frame_context", None)
        if frame_context is None:
            self._trace("analysis_discarded", session_id=session_id, reason="missing_frame_context")
            return VisionResultOutcome("discarded", reason="missing_frame_context")
        if frame_context.session_id != session_id:
            self._trace(
                "analysis_discarded", frame_id=frame_context.frame_id,
                session_id=frame_context.session_id, active_session_id=session_id,
                source=frame_context.source, reason="session_context_mismatch",
            )
            return VisionResultOutcome("discarded", source=frame_context.source, reason="session_context_mismatch")

        owned = getattr(session, "_vision_frame_context", None)
        if owned is not None and owned.frame_id != frame_context.frame_id:
            self._trace(
                "analysis_discarded", frame_id=frame_context.frame_id,
                session_id=session_id, source=frame_context.source,
                reason="superseded_session_job",
            )
            return VisionResultOutcome("discarded", source=frame_context.source, reason="superseded_session_job")
        if closing or not self.is_current(frame_context):
            reason = "window_shutdown" if closing else "stale_session_generation"
            self._trace(
                "analysis_discarded", frame_id=frame_context.frame_id,
                session_id=session_id, source=frame_context.source, reason=reason,
            )
            if owned is not None and owned.frame_id == frame_context.frame_id:
                session._vision_frame_context = None
            return VisionResultOutcome("discarded", source=frame_context.source, reason=reason)
        if owned is not None and owned.frame_id == frame_context.frame_id:
            session._vision_frame_context = None

        source = frame_context.source
        hwnd, pid, exe, title, path = frame_context.window_identity
        captured = {"hwnd": hwnd, "pid": pid, "exe": exe, "title": title, "path": path}
        if self._capture is None:
            raise RuntimeError("VisionAnalysisCoordinator requires a capture service for result validation")
        current = self._capture.foreground_window_info(
            allow_partial_identity=(source == "desktop")
        )
        same_window = (
            isinstance(current, dict)
            and int(current.get("hwnd") or 0) == int(hwnd or -1)
            and int(current.get("pid") or 0) == int(pid or -1)
        )
        privacy = _service_value(self._vision, "desktop_capture_application_service")
        desktop_source_active = (
            source == "desktop" and not closing and bool(game_mode_enabled)
            and privacy is not None and bool(_service_value(privacy, "enabled"))
        )
        desktop_allowed, desktop_reason = (
            privacy.evaluate_window(current)
            if desktop_source_active else (False, "source_disabled")
        )
        current_result = (
            desktop_source_active and current is not None and desktop_allowed
            if source == "desktop"
            else same_window and bool(game_mode_enabled)
        )

        self._vision.mark_latency(latency_ms, session_id=session_id)
        stats = self._vision.snapshot(session_id=session_id)
        if not current_result:
            reason = (
                "capture_source_disabled" if source == "desktop" and not desktop_source_active
                else desktop_reason if source == "desktop" and not desktop_allowed
                else "foreground_window_changed"
            )
            self._trace(
                "analysis_discarded", source=source,
                exe=str(exe or "")[:80] or None, reason=reason,
            )
            return VisionResultOutcome(
                "discarded", source=source, reason=reason,
                latency_ms=int(latency_ms or 0), stats=stats,
                same_window=bool(same_window),
            )
        if source == "desktop" and not same_window:
            self._trace(
                "analysis_foreground_changed_accepted",
                source=source,
                captured_exe=str(exe or "")[:80] or None,
                current_exe=str((current or {}).get("exe") or "")[:80] or None,
                reason="selected_monitor_frame_is_independent_of_foreground_window",
            )

        message = self._vision.consume_result(
            enabled=bool(game_mode_enabled) if source == "game" else True,
            profile=game_mode_profile if source == "game" else None,
            ok=bool(ok), result=result, source=source,
            window_info=current, session_id=session_id,
        )
        self._trace(
            "analysis_result", source=source, ok=bool(ok),
            latency_ms=int(latency_ms or 0), result_chars=len(str(result or "")),
        )
        if message is None:
            return VisionResultOutcome(
                "no_message", source=source, latency_ms=int(latency_ms or 0),
                stats=stats, same_window=bool(same_window),
            )

        history_events = None
        if ok and game_mode_enabled:
            desktop_context_service.record_event(
                "visual_observation", message[:240], source=source,
                dedupe_key=f"visual:{fingerprint(message)}",
            )
            history_events = len(desktop_context_service.snapshot().get("recent_events", ()))
            self._trace(
                "visual_observation_recorded", source=source,
                observation_chars=len(message), history_events=history_events,
            )
        if not ok:
            self._trace("visual_observation_not_presented", source=source, reason="analysis_failed")
            return VisionResultOutcome(
                "failed", source=source, message=message,
                latency_ms=int(latency_ms or 0), stats=stats,
                same_window=bool(same_window), history_events=history_events,
            )
        self._trace("visual_observation_ready_for_chat", source=source, observation_chars=len(message))
        return VisionResultOutcome(
            "ready", source=source, message=message,
            latency_ms=int(latency_ms or 0), stats=stats,
            same_window=bool(same_window), history_events=history_events,
        )

class LiveSessionManager:
    """Own Live frame budgets, privacy revalidation, change detection and send admission."""

    def __init__(
        self,
        settings: Any,
        capture_service: VisionCaptureService,
        vision_service: Any,
        game_mode_service: Any,
        transport: LiveFrameTransport,
        frame_codec: Any,
        *,
        max_frame_bytes_provider: Callable[[], int] | None = None,
        trace: Callable[..., Any] | None = None,
    ) -> None:
        self._settings = settings
        self._capture = capture_service
        self._vision = vision_service
        self._game_mode = game_mode_service
        self._transport = transport
        self._codec = frame_codec
        self._max_frame_bytes_provider = max_frame_bytes_provider
        self._trace = trace or (lambda *_args, **_kwargs: None)
        self._selector = LiveFrameSelector(self.policy)
        self._identity = None
        self._disposed = False

    def budget_values(self) -> tuple[float, int]:
        defaults = SelectorPolicy()
        try:
            interval = float(self._settings.get(
                "eye_live_min_interval_seconds", defaults.min_interval_seconds
            ))
        except (TypeError, ValueError):
            interval = defaults.min_interval_seconds
        try:
            per_minute = int(self._settings.get(
                "eye_live_max_frames_per_minute", defaults.max_frames_per_minute
            ))
        except (TypeError, ValueError):
            per_minute = defaults.max_frames_per_minute
        return max(1.0, min(interval, 60.0)), max(1, min(per_minute, 60))

    @property
    def policy(self):
        interval, per_minute = self.budget_values()
        return SelectorPolicy(
            mean_threshold=0.015,
            min_interval_seconds=interval,
            max_frames_per_minute=per_minute,
        )

    @property
    def selector(self):
        if self._selector.policy != self.policy:
            self._selector.policy = self.policy
        return self._selector

    def refresh_policy(self) -> None:
        self._selector.policy = self.policy

    def activate(self, enabled: bool) -> None:
        if self._disposed:
            return
        if enabled:
            self.selector.reset()
        else:
            self.reset(clear_remote=True)

    def reset(self, *, clear_remote: bool = True) -> None:
        self.selector.reset()
        self._identity = None
        if clear_remote:
            self._transport.clear_gemini_video_frames()

    def dispose(self) -> None:
        if self._disposed:
            return
        self.reset(clear_remote=True)
        self._disposed = True

    def _release(self, frame_context) -> bool:
        if frame_context is not None:
            self._vision.release_frame_budget(frame_context)
        return False

    def _max_frame_bytes(self) -> int:
        if self._max_frame_bytes_provider is not None:
            return int(self._max_frame_bytes_provider())
        from .gemini_live import MAX_VIDEO_FRAME_BYTES
        return int(MAX_VIDEO_FRAME_BYTES)

    def stream_frame(
        self,
        frame: Any,
        source: str,
        window_info: dict | None,
        *,
        frame_context: Any = None,
        game_mode_enabled: bool,
        game_mode_profile: str | None,
    ) -> bool:
        if self._disposed or not self._transport.is_gemini_live_ready():
            return self._release(frame_context)

        max_bytes = self._max_frame_bytes()
        privacy = _service_value(self._vision, "desktop_capture_application_service")
        if source == "desktop":
            source_enabled = bool(_service_value(privacy, "enabled"))
        elif source == "game":
            permissions = self._game_mode.permissions(game_mode_profile)
            source_enabled = bool(game_mode_enabled and permissions["vision_capture"])
        else:
            source_enabled = False
        if not source_enabled:
            self.reset(clear_remote=True)
            return self._release(frame_context)

        current = self._capture.foreground_window_info(
            allow_partial_identity=(source == "desktop")
        )
        permitted = self._vision.capture_allowed(
            game_mode_enabled if source == "game" else False,
            game_mode_profile if source == "game" else None,
            source=source,
            window_info=current,
        )
        if not permitted:
            self.reset(clear_remote=True)
            self._trace(
                "live_video_blocked", source=source,
                reason="privacy_or_source_disabled",
            )
            return self._release(frame_context)

        foreground_identity = _window_identity(current)
        expected = _window_identity(window_info)
        identity = (
            ("desktop-monitor", str(_service_value(privacy, "selected_monitor_id") or "auto"))
            if source == "desktop" else foreground_identity
        )
        if source == "game" and (
            not all(foreground_identity) or foreground_identity != expected
        ):
            self.reset(clear_remote=True)
            self._trace("live_video_blocked", source=source, reason="foreground_changed")
            return self._release(frame_context)

        if identity != self._identity:
            self._transport.clear_gemini_video_frames()
            self.selector.reset()
            self._identity = identity

        if frame_context is not None and not self._vision.frame_context_is_current(frame_context):
            return self._release(frame_context)

        if _valid_frame(frame):
            frame_image = frame
        else:
            frame_image = self._capture.capture_live_monitor_frame(
                current,
                monitor_id=_service_value(privacy, "selected_monitor_id") if source == "desktop" else None,
                max_width=480,
                max_height=270,
            )
        if not _valid_frame(frame_image):
            self.reset(clear_remote=True)
            self._trace(
                "live_video_capture_skipped", source=source,
                reason="full_monitor_capture_failed",
            )
            return self._release(frame_context)

        latest = self._capture.foreground_window_info(
            allow_partial_identity=(source == "desktop")
        )
        latest_identity = _window_identity(latest)
        if (
            (source == "game" and latest_identity != foreground_identity)
            or not self._vision.capture_allowed(
                game_mode_enabled if source == "game" else False,
                game_mode_profile if source == "game" else None,
                source=source,
                window_info=latest,
            )
        ):
            self.reset(clear_remote=True)
            self._trace(
                "live_video_blocked", source=source,
                reason="foreground_changed_during_capture",
            )
            return self._release(frame_context)

        image, sample = self._codec.prepare_live_frame(
            frame_image, width=480, height=270
        )
        decision = self.selector.evaluate(sample)
        if not decision.send:
            return self._release(frame_context)

        try:
            encoded = self._codec.encode_live_frame(image, max_bytes)
        except Exception as exc:
            self._trace(
                "live_video_encode_failed", source=source,
                error=type(exc).__name__,
            )
            return self._release(frame_context)
        if encoded is None or not encoded.jpeg or len(encoded.jpeg) > max_bytes:
            self._trace(
                "live_video_frame_dropped",
                source=source,
                reason="frame_exceeds_size_limit",
                jpeg_bytes=len(encoded.jpeg) if encoded is not None else 0,
                max_bytes=max_bytes,
                width=encoded.width if encoded is not None else 0,
                height=encoded.height if encoded is not None else 0,
            )
            return self._release(frame_context)

        if not self._transport.send_gemini_video_frame(encoded.jpeg):
            return self._release(frame_context)

        self.selector.commit(sample)
        if frame_context is not None:
            self._vision.commit_frame_budget(frame_context)
        self._trace(
            "live_video_frame_queued",
            source=source,
            frame_id=frame_context.frame_id if frame_context is not None else None,
            session_id=frame_context.session_id if frame_context is not None else None,
            reason=decision.reason,
            mean_change=round(decision.mean_change, 4),
            changed_cells=decision.changed_cells,
            skipped_unchanged=self.selector.skipped_unchanged,
            skipped_rate_limited=self.selector.skipped_rate_limited,
            format="JPEG",
            width=encoded.width,
            height=encoded.height,
            jpeg_quality=encoded.quality,
            jpeg_bytes=len(encoded.jpeg),
            jpeg_kib=round(len(encoded.jpeg) / 1024.0, 2),
            max_bytes=max_bytes,
            gate_max_fps=1,
            min_interval_seconds=self.selector.policy.min_interval_seconds,
            max_frames_per_minute=self.selector.policy.max_frames_per_minute,
            approx_kib_per_frame=round(len(encoded.jpeg) / 1024.0, 2),
            color_levels=16,
            palette_colors=16 ** 3,
        )
        return True
