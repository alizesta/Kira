"""Qt-free decision logic: which captured frames are worth sending to Gemini Live.

The capture timer runs at a fixed cadence; this module decides, per tick, whether the
screen changed enough to deserve a new frame. It deliberately knows nothing about Qt,
JPEG encoding or the Live worker, so it can be tested without a display.

Two kinds of change count:
  * global change: the mean luminance difference over the whole frame, which is what
    scrolling, page loads and video produce;
  * local change: enough individual cells changed strongly, which is what a small popup,
    an error line or a notification produces even though the global mean barely moves.

The reference is always the last frame that was actually sent (``commit``), so slow drift
accumulates instead of being lost, and a frame that failed to encode or was rejected by
the Live rate limit is retried on the next tick.
"""
from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass

SAMPLE_WIDTH = 64
SAMPLE_HEIGHT = 36
SAMPLE_CELLS = SAMPLE_WIDTH * SAMPLE_HEIGHT


@dataclass(frozen=True)
class SelectorPolicy:
    # Mean absolute luminance difference (0..1) that counts as a global change.
    mean_threshold: float = 0.015
    # A single cell counts as "changed" when its luminance moved by at least this fraction.
    cell_threshold: float = 0.12
    # This many changed cells count as a local change.
    hotspot_cells: int = 12
    # Frame budget (0 disables a limit). A changed frame that is over budget is not lost:
    # the reference stays on the last sent frame, so the newest screen is sent once allowed.
    min_interval_seconds: float = 5.0
    max_frames_per_minute: int = 10


@dataclass(frozen=True)
class SelectorDecision:
    send: bool
    reason: str  # first | size_changed | mean_change | local_change | unchanged | rate_limited
    mean_change: float = 0.0
    changed_cells: int = 0


def measure_change(previous: bytes, current: bytes, cell_threshold: float) -> tuple[float, int]:
    """Return (mean luminance change 0..1, number of strongly changed cells)."""
    count = len(current)
    if not count or len(previous) != count:
        return 1.0, count
    cell_limit = max(1, round(float(cell_threshold) * 255.0))
    total = 0
    strong = 0
    for before, after in zip(previous, current):
        delta = before - after
        if delta < 0:
            delta = -delta
        total += delta
        if delta >= cell_limit:
            strong += 1
    return total / (255.0 * count), strong


class LiveFrameSelector:
    def __init__(self, policy: SelectorPolicy | None = None) -> None:
        self.policy = policy or SelectorPolicy()
        self._reference = b""
        self.evaluated = 0
        self.sent = 0
        self.skipped_unchanged = 0
        self.skipped_rate_limited = 0
        self._sent_times: deque[float] = deque()

    @property
    def has_reference(self) -> bool:
        return bool(self._reference)

    def _over_budget(self, now: float) -> bool:
        policy = self.policy
        if not self._sent_times:
            return False
        if policy.min_interval_seconds > 0 and now - self._sent_times[-1] < policy.min_interval_seconds:
            return True
        if policy.max_frames_per_minute > 0:
            recent = sum(1 for moment in self._sent_times if now - moment < 60.0)
            if recent >= policy.max_frames_per_minute:
                return True
        return False

    def evaluate(self, sample: bytes, now: float | None = None) -> SelectorDecision:
        """Judge a sample against the last sent frame. Does not change the reference."""
        moment = time.monotonic() if now is None else float(now)
        current = bytes(sample or b"")
        self.evaluated += 1
        if not current:
            self.skipped_unchanged += 1
            return SelectorDecision(False, "unchanged")
        if not self._reference:
            reason, mean, strong = "first", 1.0, len(current)
        elif len(self._reference) != len(current):
            reason, mean, strong = "size_changed", 1.0, len(current)
        else:
            mean, strong = measure_change(self._reference, current, self.policy.cell_threshold)
            if mean >= self.policy.mean_threshold:
                reason = "mean_change"
            elif strong >= self.policy.hotspot_cells:
                reason = "local_change"
            else:
                self.skipped_unchanged += 1
                return SelectorDecision(False, "unchanged", mean, strong)
        if self._over_budget(moment):
            self.skipped_rate_limited += 1
            return SelectorDecision(False, "rate_limited", mean, strong)
        return SelectorDecision(True, reason, mean, strong)

    def commit(self, sample: bytes, now: float | None = None) -> None:
        """Remember a frame that was really queued for Gemini Live."""
        moment = time.monotonic() if now is None else float(now)
        self._reference = bytes(sample or b"")
        self.sent += 1
        self._sent_times.append(moment)
        while self._sent_times and moment - self._sent_times[0] >= 60.0:
            self._sent_times.popleft()

    def reset(self) -> None:
        """Forget the reference so the next frame is always sent (new session, privacy stop)."""
        self._reference = b""

    def snapshot(self) -> dict:
        return {
            "evaluated": self.evaluated,
            "sent": self.sent,
            "skipped_unchanged": self.skipped_unchanged,
            "skipped_rate_limited": self.skipped_rate_limited,
        }
