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
    max_width: int = 640
    max_height: int = 360
    jpeg_quality: int = 45


# Escalated capture for small text / dense UI / OCR (used only when the question or a failed read needs it).
CAPTURE_DETAIL_MAX_WIDTH = 1280
CAPTURE_DETAIL_MAX_HEIGHT = 720
CAPTURE_DETAIL_JPEG_QUALITY = 80

# Frames are kept small on purpose: every analysed frame is uploaded to a cloud vision model.
POLICIES = {
    "economic": VisionPolicy("economic", 5.0, 0.045, 768, 432, 75),
    "smart": VisionPolicy("smart", 1.0, 0.035, 768, 432, 78),
    "fast": VisionPolicy("fast", 0.5, 0.025, 960, 540, 80),
}

# Words that mean the user needs to read small text / fine UI: such a question escalates the capture to 1280x720.
DETAIL_HINTS = (
    "متن", "ریز", "کوچک", "بخوان", "منو", "منوی", "زیرنویس", "دیالوگ", "استت", "آمار", "عدد", "اعداد", "جزئیات",
    "small text", "tiny", "read", "text", "menu", "dialogue", "dialog", "subtitle", "stats", "number", "detail", "ocr",
)
# Phrases in a model reply that mean it could not read the frame: one automatic retry at the detail size.
UNREADABLE_HINTS = (
    "نمی‌تونم بخونم", "نمی‌توانم بخوانم", "خوانا نیست", "تار", "خیلی ریز", "قابل خواندن نیست",
    "too small", "blurry", "unreadable", "illegible", "can't read", "cannot read", "not legible",
)


# Phrases that mean the question is about what is on the screen right now: only then is a screenshot attached.
SCREEN_HINTS = (
    "صفحه", "اسکرین", "صفحه‌نمایش", "مانیتور", "ببین", "نگاه کن", "نگاه کنی", "می‌بینی", "میبینی", "این چیه", "اینجا چیه",
    "چی نوشته", "چی میگه", "چی می‌گه", "کجام", "کجای", "این منو", "این بخش", "این دکمه",
    "screen", "look at", "do you see", "what is this", "what's this", "what does it say", "where am i", "this menu",
)


def refers_to_screen(question: str | None) -> bool:
    low = str(question or "").casefold()
    return any(hint in low for hint in SCREEN_HINTS)


from .character.repetition import too_similar

HIGHLIGHT_MARK = "[HIGHLIGHT]"


def extract_highlight(text: str | None, max_chars: int = 220) -> str | None:
    """The one-line comment the vision model appends after HIGHLIGHT_MARK, or None when nothing notable happened."""
    for line in reversed(str(text or "").splitlines()):
        line = line.strip()
        if line.upper().startswith(HIGHLIGHT_MARK):
            comment = line[len(HIGHLIGHT_MARK):].strip(" :-—")
            return comment[:max_chars] if comment else None
    return None


class HighlightGate:
    """Keep spontaneous game comments rare: minimum gap, hourly cap, and no repeating the same remark."""

    def __init__(self, min_interval: float = 60.0, per_hour: int = 10, clock=time.monotonic):
        self.min_interval, self.per_hour, self._clock = float(min_interval), int(per_hour), clock
        self._sent: list[float] = []
        self._recent: list[str] = []

    def allow(self, comment: str) -> bool:
        now = self._clock()
        self._sent = [t for t in self._sent if now - t < 3600]
        key = " ".join(str(comment or "").split()).casefold()
        if not key or key in self._recent or any(too_similar(key, old) for old in self._recent):
            return False
        if self._sent and now - self._sent[-1] < self.min_interval:
            return False
        if len(self._sent) >= self.per_hour:
            return False
        self._sent.append(now)
        self._recent = (self._recent + [key])[-5:]
        return True


def wants_detail_capture(question: str | None) -> bool:
    low = str(question or "").casefold()
    return any(hint in low for hint in DETAIL_HINTS)


def reply_was_unreadable(reply: str | None) -> bool:
    low = str(reply or "").casefold()
    return any(hint in low for hint in UNREADABLE_HINTS)


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
        self._last_at = None
        self._last_signature = b""
        self._last_visual_sample = b""
        self.captured = 0
        self.analyzed = 0
        self.skipped_unchanged = 0
        self.last_latency_ms = None

    def set_policy(self, policy: VisionPolicy):
        self.policy = policy
        self.reset()

    def reset(self):
        self._last_at = None
        self._last_signature = b""
        self._last_visual_sample = b""

    def accept(self, jpeg: bytes, force: bool = False, visual_sample: bytes | None = None) -> bool:
        self.captured += 1
        now = self._clock()
        if not jpeg:
            return False
        signature = frame_signature(jpeg)
        if not force and self._last_at is not None and now - self._last_at < self.policy.interval_seconds:
            return False
        if not force and visual_sample and self._last_visual_sample and len(visual_sample) == len(self._last_visual_sample):
            delta = sum(abs(a - b) for a, b in zip(visual_sample, self._last_visual_sample))
            change = delta / (255.0 * len(visual_sample))
            if change < self.policy.change_threshold:
                self.skipped_unchanged += 1
                self._last_at = now
                return False
        elif not force and self._last_signature and signature == self._last_signature:
            self.skipped_unchanged += 1
            self._last_at = now
            return False
        self._last_at = now
        self._last_signature = signature
        if visual_sample:
            self._last_visual_sample = bytes(visual_sample)
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
