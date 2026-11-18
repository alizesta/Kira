"""Application policy for the bounded game-vision capture loop.

Qt screen capture, image encoding, timers and worker objects remain UI/adapter
responsibilities. This service owns the policy gate, capture eligibility and
duplicate-result suppression.
"""
from __future__ import annotations

from typing import Any

from ..vision_pipeline import FrameGate, policy_for


class VisionApplicationService:
    """Own vision cadence and Game Mode capture/result policy."""

    def __init__(self, game_mode_service: Any, mode: str | None = None) -> None:
        if game_mode_service is None:
            raise TypeError("game_mode_service is required")
        self.game_mode_service = game_mode_service
        self.frame_gate = FrameGate(policy_for(mode))
        self._last_note = ""

    @property
    def last_note(self) -> str:
        return self._last_note

    @last_note.setter
    def last_note(self, value: str) -> None:
        self._last_note = str(value or "")

    def set_mode(self, mode: str):
        """Set a supported cadence; unknown values resolve to the economic policy."""
        policy = policy_for(mode)
        self.frame_gate.set_policy(policy)
        return policy

    def capture_allowed(self, enabled: bool, profile: str | None) -> bool:
        """Require an explicit Game Mode opt-in and a profile that permits capture."""
        return bool(enabled) and self.game_mode_service.can_capture_vision(profile)

    def should_analyze(
        self,
        *,
        enabled: bool,
        profile: str | None,
        frame_available: bool,
        worker_running: bool,
        chat_busy: bool,
        provider_busy: bool,
        speech_active: bool,
    ) -> bool:
        """Avoid stale/overlapping analysis and never compete with interactive chat."""
        return (
            self.capture_allowed(enabled, profile)
            and bool(frame_available)
            and not bool(worker_running)
            and not bool(chat_busy)
            and not bool(provider_busy)
            and not bool(speech_active)
        )

    def consume_result(self, *, enabled: bool, profile: str | None, ok: bool, result: Any) -> str | None:
        """Return a new user-presentable result once; suppress empty and duplicate notices."""
        if not self.capture_allowed(enabled, profile):
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
        return self.frame_gate.accept(jpeg, visual_sample=visual_sample)

    def mark_latency(self, milliseconds: int) -> None:
        self.frame_gate.mark_latency(milliseconds)

    def snapshot(self):
        return self.frame_gate.snapshot()

    def reset(self) -> None:
        """Clear cadence and duplicate suppression when capture is disabled."""
        self.frame_gate.reset()
        self._last_note = ""
