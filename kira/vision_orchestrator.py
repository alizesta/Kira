"""Central frame lifecycle, routing and bounded backpressure for Vision.

The orchestrator is deliberately independent of Qt and provider SDKs. Capture adapters
create immutable contexts; this service assigns exactly one cloud route to each frame,
keeps only the newest pending job, and invalidates work when a session is cancelled.
"""
from __future__ import annotations

from collections import OrderedDict, deque
from dataclasses import dataclass
import threading
import time
import uuid
from typing import Any


@dataclass(frozen=True)
class FrameContext:
    frame_id: str
    session_id: str
    source: str
    captured_at: float
    window_identity: tuple[Any, ...] = ()
    generation: int = 0

    @classmethod
    def create(
        cls,
        session_id: str,
        source: str,
        window_info: dict | None = None,
        *,
        captured_at: float | None = None,
        generation: int = 0,
    ) -> "FrameContext":
        info = window_info if isinstance(window_info, dict) else {}
        identity = (
            int(info.get("hwnd") or 0),
            int(info.get("pid") or 0),
            str(info.get("exe") or "").casefold(),
            str(info.get("title") or "").strip(),
            str(info.get("path") or "").casefold(),
        )
        return cls(
            frame_id=uuid.uuid4().hex,
            session_id=str(session_id or ""),
            source=str(source or ""),
            captured_at=time.monotonic() if captured_at is None else float(captured_at),
            window_identity=identity,
            generation=int(generation),
        )


@dataclass(frozen=True)
class FrameJob:
    context: FrameContext
    payload: bytes
    visual_sample: bytes = b""

    def __post_init__(self):
        object.__setattr__(self, "payload", bytes(self.payload or b""))
        object.__setattr__(self, "visual_sample", bytes(self.visual_sample or b""))


@dataclass(frozen=True)
class FrameRoute:
    frame_id: str
    route: str
    reason: str


class VisionFrameOrchestrator:
    """Serialize per-frame route decisions and bound pending work to the newest frame."""

    LIVE = "live"
    ANALYSIS = "analysis"
    DROP = "drop"

    def __init__(
        self,
        *,
        capacity: int = 1,
        max_frames_per_minute: int = 60,
        min_interval_seconds: float = 0.0,
        clock=time.monotonic,
        history_size: int = 4096,
    ) -> None:
        if int(capacity) < 1:
            raise ValueError("capacity must be at least one")
        self.capacity = int(capacity)
        self.max_frames_per_minute = max(0, int(max_frames_per_minute))
        self.min_interval_seconds = max(0.0, float(min_interval_seconds))
        self._clock = clock
        self._lock = threading.RLock()
        self._pending: deque[FrameJob] = deque()
        self._decisions: OrderedDict[str, FrameRoute] = OrderedDict()
        self._generations: dict[str, int] = {}
        self._sent_at: dict[str, deque[float]] = {}
        self._budget_decisions: dict[str, tuple[str, float]] = {}
        self._history_size = max(64, int(history_size))
        self.dropped_pending = 0
        self.duplicate_frames = 0
        self.cancelled_frames = 0

    def is_current(self, context: FrameContext) -> bool:
        with self._lock:
            return context.generation == self._generations.get(context.session_id, 0)

    def generation(self, session_id: str) -> int:
        with self._lock:
            return self._generations.get(str(session_id or ""), 0)

    def create_context(self, session_id: str, source: str, window_info: dict | None = None):
        key = str(session_id or "")
        with self._lock:
            generation = self._generations.setdefault(key, 0)
        return FrameContext.create(session_id, source, window_info, generation=generation)

    def _remember(self, decision: FrameRoute) -> None:
        self._decisions[decision.frame_id] = decision
        self._decisions.move_to_end(decision.frame_id)
        while len(self._decisions) > self._history_size:
            self._decisions.popitem(last=False)

    def configure_budget(self, *, max_frames_per_minute: int, min_interval_seconds: float) -> None:
        """Update the active route budget while retaining the shared session history."""
        with self._lock:
            self.max_frames_per_minute = max(0, int(max_frames_per_minute))
            self.min_interval_seconds = max(0.0, float(min_interval_seconds))

    def _over_budget(self, session_id: str, now: float) -> bool:
        sent = self._sent_at.setdefault(session_id, deque())
        while sent and now - sent[0] >= 60.0:
            sent.popleft()
        if self.max_frames_per_minute and len(sent) >= self.max_frames_per_minute:
            return True
        return bool(
            self.min_interval_seconds and sent
            and now - sent[-1] < self.min_interval_seconds
        )

    def decide(
        self,
        context: FrameContext,
        *,
        live_ready: bool,
        analysis_allowed: bool = True,
        now: float | None = None,
    ) -> FrameRoute:
        """Choose one and only one cloud path for a frame; repeated calls are idempotent."""
        moment = self._clock() if now is None else float(now)
        with self._lock:
            current_generation = self._generations.get(context.session_id, 0)
            if context.generation != current_generation:
                decision = FrameRoute(context.frame_id, self.DROP, "stale_session_generation")
                self._remember(decision)
                return decision
            previous = self._decisions.get(context.frame_id)
            if previous is not None:
                self.duplicate_frames += 1
                return previous
            if self._over_budget(context.session_id, moment):
                decision = FrameRoute(context.frame_id, self.DROP, "frame_budget_exhausted")
            elif live_ready:
                decision = FrameRoute(context.frame_id, self.LIVE, "live_session_ready")
            elif analysis_allowed:
                decision = FrameRoute(context.frame_id, self.ANALYSIS, "analysis_permitted")
            else:
                decision = FrameRoute(context.frame_id, self.DROP, "no_eligible_route")
            if decision.route != self.DROP:
                self._sent_at.setdefault(context.session_id, deque()).append(moment)
                self._budget_decisions[context.frame_id] = (context.session_id, moment)
            self._remember(decision)
            return decision

    def enqueue(self, job: FrameJob) -> bool:
        """Keep at most capacity pending jobs; a new job evicts the oldest pending frame."""
        with self._lock:
            if job.context.generation != self._generations.get(job.context.session_id, 0):
                self.cancelled_frames += 1
                return False
            if not job.payload:
                return False
            if any(item.context.frame_id == job.context.frame_id for item in self._pending):
                self.duplicate_frames += 1
                return False
            session_pending = [
                item for item in self._pending
                if item.context.session_id == job.context.session_id
            ]
            if len(session_pending) >= self.capacity:
                dropped = session_pending[0]
                self._pending.remove(dropped)
                self._release_budget(dropped.context.frame_id)
                self.dropped_pending += 1
            self._pending.append(job)
            return True

    def _release_budget(self, frame_id: str) -> bool:
        reservation = self._budget_decisions.pop(str(frame_id or ""), None)
        if reservation is None:
            return False
        session_id, moment = reservation
        sent = self._sent_at.get(session_id)
        if sent is not None:
            try:
                sent.remove(moment)
            except ValueError:
                pass
            if not sent:
                self._sent_at.pop(session_id, None)
        return True

    def release(self, context: FrameContext) -> bool:
        """Return a reserved quota token when a frame was not dispatched."""
        with self._lock:
            return self._release_budget(context.frame_id)

    def take_next(self, session_id: str | None = None) -> FrameJob | None:
        """Take an eligible job for one session without stealing another session's work."""
        key = None if session_id is None else str(session_id or "")
        with self._lock:
            for job in tuple(self._pending):
                if key is not None and job.context.session_id != key:
                    continue
                self._pending.remove(job)
                if job.context.generation == self._generations.get(job.context.session_id, 0):
                    return job
                self.cancelled_frames += 1
            return None

    def cancel_session(self, session_id: str) -> int:
        """Invalidate in-flight contexts and remove pending work for one session."""
        key = str(session_id or "")
        with self._lock:
            self._generations[key] = self._generations.get(key, 0) + 1
            kept = deque(job for job in self._pending if job.context.session_id != key)
            removed = len(self._pending) - len(kept)
            self._pending = kept
            self.cancelled_frames += removed
            self._sent_at.pop(key, None)
            self._budget_decisions = {
                frame_id: reservation
                for frame_id, reservation in self._budget_decisions.items()
                if reservation[0] != key
            }
            return removed

    def cancel_all(self) -> int:
        with self._lock:
            removed = len(self._pending)
            self._pending.clear()
            for session_id in set(self._generations) | set(self._sent_at):
                self._generations[session_id] = self._generations.get(session_id, 0) + 1
            self._sent_at.clear()
            self._budget_decisions.clear()
            self.cancelled_frames += removed
            return removed

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "pending": len(self._pending),
                "capacity": self.capacity,
                "dropped_pending": self.dropped_pending,
                "duplicate_frames": self.duplicate_frames,
                "cancelled_frames": self.cancelled_frames,
                "sessions": len(self._generations),
            }
