"""Low-cost frame scheduling for Kira's desktop/game vision.

The capture loop may run frequently, but analysis is deliberately rate-limited.
Only the newest frame is retained; stale frames are discarded instead of queued.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import time


@dataclass(frozen=True)
class VisionPolicy:
    name: str
    interval_seconds: float
    change_threshold: float = 0.035
    max_width: int = 854
    max_height: int = 480
    jpeg_quality: int = 62


POLICIES = {
    "economic": VisionPolicy("economic", 5.0, 0.045, 854, 480, 62),
    "smart": VisionPolicy("smart", 1.0, 0.035, 960, 540, 66),
    "fast": VisionPolicy("fast", 0.5, 0.025, 1280, 720, 70),
}


def policy_for(name: str | None) -> VisionPolicy:
    return POLICIES.get(str(name or "economic").strip().lower(), POLICIES["economic"])


def frame_signature(data: bytes, sample_count: int = 768) -> bytes:
    """Hash a bounded, evenly sampled slice of an encoded frame."""
    raw = bytes(data or b"")
    if not raw:
        return b""
    count = min(max(32, int(sample_count)), len(raw))
    if count == len(raw):
        sample = raw
    else:
        step = (len(raw) - 1) / (count - 1)
        sample = bytes(raw[round(i * step)] for i in range(count))
    return hashlib.blake2b(sample, digest_size=16).digest()


class LatestFrameQueue:
    """Single-slot queue: pushing a new frame always replaces stale pending work."""
    def __init__(self):
        self._item = None
        self.dropped = 0

    def push(self, item):
        if self._item is not None:
            self.dropped += 1
        self._item = item

    def pop(self):
        item, self._item = self._item, None
        return item

    def clear(self):
        self._item = None

    def __bool__(self):
        return self._item is not None


class FrameGate:
    """Rate limit and suppress unchanged frames without retaining image buffers."""
    def __init__(self, policy: VisionPolicy | None = None, clock=time.monotonic):
        self.policy = policy or policy_for("economic")
        self._clock = clock
        self._last_at = 0.0
        self._last_signature = b""
        self.captured = 0
        self.analyzed = 0
        self.skipped_unchanged = 0
        self.last_latency_ms = None

    def set_policy(self, policy: VisionPolicy):
        self.policy = policy
        self.reset()

    def reset(self):
        self._last_at = 0.0
        self._last_signature = b""

    def accept(self, jpeg: bytes, force: bool = False) -> bool:
        self.captured += 1
        now = self._clock()
        if not jpeg:
            return False
        signature = frame_signature(jpeg)
        if not force and self._last_at and now - self._last_at < self.policy.interval_seconds:
            return False
        if not force and self._last_signature and signature == self._last_signature:
            self.skipped_unchanged += 1
            return False
        self._last_at = now
        self._last_signature = signature
        self.analyzed += 1
        return True

    def mark_latency(self, milliseconds: int):
        self.last_latency_ms = max(0, int(milliseconds))

    def snapshot(self):
        return {
            "mode": self.policy.name,
            "capture_count": self.captured,
            "analysis_count": self.analyzed,
            "unchanged_skips": self.skipped_unchanged,
            "last_latency_ms": self.last_latency_ms,
            "interval_seconds": self.policy.interval_seconds,
        }
