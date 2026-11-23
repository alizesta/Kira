"""Bounded visual change detection; only a tiny grayscale sample is retained."""
from __future__ import annotations

import time


class ChangeDetector:
    def __init__(self, *, threshold: float = 0.025, min_interval: float = 0.75, clock=time.monotonic):
        self.threshold = max(0.0, min(1.0, float(threshold)))
        self.min_interval = max(0.0, float(min_interval))
        self._clock = clock
        self._last_sample = b""
        self._last_at: float | None = None

    def changed(self, sample: bytes, *, force: bool = False) -> bool:
        current = bytes(sample or b"")
        if not current:
            return False
        now = self._clock()
        if not force and self._last_at is not None and now - self._last_at < self.min_interval:
            return False
        previous = self._last_sample
        if not previous or len(previous) != len(current):
            result = True
        else:
            delta = sum(abs(left - right) for left, right in zip(previous, current))
            result = (delta / (255.0 * len(current))) >= self.threshold
        if result:
            self._last_sample = current
            self._last_at = now
        return result

    def reset(self) -> None:
        self._last_sample = b""
        self._last_at = None
