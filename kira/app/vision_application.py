"""Application policy for Game Mode and Live Desktop Vision."""
from __future__ import annotations

from typing import Any

from ..vision_pipeline import FrameGate, policy_for
from ..vision_orchestrator import FrameContext, FrameJob, VisionFrameOrchestrator


class VisionApplicationService:
    """Own source-aware capture eligibility, cadence and result policy."""

    GAME_SOURCE = "game"
    DESKTOP_SOURCE = "desktop"

    def __init__(self, game_mode_service: Any | None = None, mode: str | None = None,
                 desktop_capture_application_service: Any | None = None) -> None:
        self.game_mode_service = game_mode_service
        self.desktop_capture_application_service = desktop_capture_application_service
        self.frame_gate = FrameGate(policy_for(mode))
        self.frame_orchestrator = VisionFrameOrchestrator(capacity=1)
        self._last_note = ""
        self._active = True
        self._disposed = False

    @property
    def last_note(self) -> str:
        return self._last_note

    @last_note.setter
    def last_note(self, value: str) -> None:
        self._last_note = str(value or "")

    def start(self) -> None:
        if self._disposed:
            raise RuntimeError("VisionApplicationService has been disposed")
        self._active = True

    def stop(self) -> None:
        self._active = False
        self.reset()

    def dispose(self) -> None:
        if self._disposed:
            return
        self.stop()
        self._disposed = True

    def set_mode(self, mode: str):
        if self._disposed:
            raise RuntimeError("VisionApplicationService has been disposed")
        policy = policy_for(mode)
        self.frame_gate.set_policy(policy)
        return policy

    def capture_allowed(self, enabled: bool, profile: str | None, *,
                        source: str = GAME_SOURCE, window_info: dict | None = None,
                        explicit: bool = False) -> bool:
        if not self._active or self._disposed:
            return False
        if source == self.DESKTOP_SOURCE:
            privacy = self.desktop_capture_application_service
            if privacy is None:
                return False
            allowed, _reason = privacy.evaluate_window(window_info, explicit=explicit)
            return bool(allowed)
        if source != self.GAME_SOURCE or self.game_mode_service is None:
            return False
        allowed = bool(enabled) and self.game_mode_service.can_capture_vision(profile)
        if not allowed:
            return False
        if window_info is None or self.desktop_capture_application_service is None:
            return True
        allowed, _reason = self.desktop_capture_application_service.evaluate_window(
            window_info, explicit=True
        )
        return bool(allowed)

    def should_analyze(self, *, enabled: bool, profile: str | None,
                       frame_available: bool, worker_running: bool,
                       chat_busy: bool, provider_busy: bool, speech_active: bool,
                       source: str = GAME_SOURCE, window_info: dict | None = None) -> bool:
        return (
            self.capture_allowed(enabled, profile, source=source, window_info=window_info)
            and bool(frame_available)
            and not bool(worker_running)
            and not bool(chat_busy)
            and not bool(provider_busy)
            and not bool(speech_active)
        )

    def consume_result(self, *, enabled: bool, profile: str | None, ok: bool,
                       result: Any, source: str = GAME_SOURCE,
                       window_info: dict | None = None) -> str | None:
        if not self.capture_allowed(enabled, profile, source=source, window_info=window_info):
            return None
        message = str(result or "").strip()
        if not ok and not message:
            message = "تحلیل تصویر ناموفق بود."
        if not message or message == self._last_note:
            return None
        self._last_note = message
        return message

    @property
    def policy(self):
        return self.frame_gate.policy

    def accept_frame(self, jpeg: bytes, visual_sample: bytes | None = None) -> bool:
        return self._active and not self._disposed and self.frame_gate.accept(
            jpeg, visual_sample=visual_sample
        )

    def mark_latency(self, milliseconds: int) -> None:
        self.frame_gate.mark_latency(milliseconds)

    def snapshot(self):
        return self.frame_gate.snapshot()

    def create_frame_context(self, session_id: str, source: str, window_info: dict | None = None) -> FrameContext:
        return self.frame_orchestrator.create_context(session_id, source, window_info)

    def route_frame(self, context: FrameContext, *, live_ready: bool, analysis_allowed: bool = True):
        return self.frame_orchestrator.decide(
            context, live_ready=live_ready, analysis_allowed=analysis_allowed
        )

    def frame_context_is_current(self, context: FrameContext) -> bool:
        return self.frame_orchestrator.is_current(context)

    def cancel_frame_session(self, session_id: str) -> int:
        return self.frame_orchestrator.cancel_session(session_id)

    def enqueue_frame(self, job: FrameJob) -> bool:
        return self.frame_orchestrator.enqueue(job)

    def take_next_frame(self, session_id: str | None = None) -> FrameJob | None:
        return self.frame_orchestrator.take_next(session_id)

    def release_frame_budget(self, context) -> bool:
        return self.frame_orchestrator.release(context)

    def commit_frame_budget(self, context) -> bool:
        return self.frame_orchestrator.commit(context)

    def reset(self) -> None:
        self.frame_gate.reset()
        self.frame_orchestrator.cancel_all()
        self._last_note = ""
