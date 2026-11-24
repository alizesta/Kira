"""Bounded, in-memory context for local desktop perception.

No screenshot or extracted text is written to disk. Call clear_sensitive() whenever
window identity is unknown or a privacy rule denies capture.
"""
from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
from threading import RLock
import time
from typing import Any

from ..perception.events import PerceptionEvent

MAX_SUMMARY_CHARS = 2000
MAX_VISIBLE_TEXT_CHARS = 1100
MAX_WINDOW_TITLE_CHARS = 160
MAX_RECENT_EVENTS = 12


class DesktopContext:
    """Keep only the current allowed window, bounded OCR text and recent events."""

    def __init__(
        self, *, max_events: int = MAX_RECENT_EVENTS, clock=time.monotonic,
        wall_clock=lambda: datetime.now(timezone.utc),
    ) -> None:
        self._lock = RLock()
        self._clock = clock
        self._wall_clock = wall_clock
        self._max_events = max(1, int(max_events))
        self._active: dict[str, Any] | None = None
        self._active_key: tuple[int, int] | None = None
        self._active_since: float | None = None
        self._active_observed_at: datetime | None = None
        self._visible_text = ""
        self._ocr_language = ""
        self._ocr_confidence = 0.0
        self._text_fingerprint = ""
        self._events: deque[PerceptionEvent] = deque(maxlen=self._max_events)
        self._active_lifecycle = True
        self._disposed = False

    def start(self) -> None:
        with self._lock:
            if self._disposed:
                raise RuntimeError("DesktopContext has been disposed")
            self._active_lifecycle = True

    def stop(self) -> None:
        with self._lock:
            self._active_lifecycle = False
            self._clear_locked()

    def dispose(self) -> None:
        with self._lock:
            if self._disposed:
                return
            self._clear_locked()
            self._active_lifecycle = False
            self._disposed = True

    @staticmethod
    def _window_key(info: dict[str, Any]) -> tuple[int, int] | None:
        try:
            hwnd, pid = int(info.get("hwnd") or 0), int(info.get("pid") or 0)
        except (TypeError, ValueError):
            return None
        return (hwnd, pid) if hwnd > 0 and pid > 0 else None

    def update_active_window(self, info: dict[str, Any], *, source: str = "desktop") -> bool:
        """Update foreground metadata; return True only on an actual window switch."""
        if not isinstance(info, dict):
            self.clear_sensitive()
            return False
        key = self._window_key(info)
        exe = str(info.get("exe") or "").strip().lower()[:100]
        title = " ".join(str(info.get("title") or "").split())[:MAX_WINDOW_TITLE_CHARS]
        path = str(info.get("path") or "").strip()[:260]
        if key is None or not exe or not title or not path:
            self.clear_sensitive()
            return False
        now = self._clock()
        observed_at = self._wall_clock()
        with self._lock:
            if self._disposed or not self._active_lifecycle:
                return False
            previous = self._active or {}
            changed = (
                key != self._active_key
                or exe != str(previous.get("exe") or "")
                or title != str(previous.get("title") or "")
                or path.casefold() != str(previous.get("path") or "").casefold()
            )
            if changed:
                same_process = key == self._active_key and exe == str(previous.get("exe") or "")
                self._active_since = now
                self._visible_text = ""
                self._ocr_language = ""
                self._ocr_confidence = 0.0
                self._text_fingerprint = ""
                self._active_key = key
                self._events.append(PerceptionEvent.create(
                    "window_changed" if same_process else "application_changed",
                    f"Active application: {exe} — {title}",
                    source=source,
                    dedupe_key=f"window:{key[0]}:{key[1]}:{PerceptionEvent.fingerprint(title)}",
                    now=now,
                ))
            self._active = {
                "hwnd": key[0], "pid": key[1], "exe": exe,
                "title": title, "path": path, "source": str(source or "desktop")[:16],
            }
            self._active_observed_at = observed_at
            return changed

    def set_visible_text(
        self, text: str, *, language: str = "", confidence: float = 0.0,
        window_key: tuple[int, int] | None = None, source: str = "desktop",
    ) -> bool:
        """Accept OCR only for the same foreground window that initiated the work."""
        normalized = " ".join(str(text or "").split())[:MAX_VISIBLE_TEXT_CHARS]
        if not normalized:
            return False
        fingerprint = PerceptionEvent.fingerprint(normalized)
        with self._lock:
            if (
                self._disposed or not self._active_lifecycle or self._active is None
                or (window_key is not None and window_key != self._active_key)
                or fingerprint == self._text_fingerprint
            ):
                return False
            self._visible_text = normalized
            self._ocr_language = str(language or "")[:24]
            try:
                score = float(confidence)
            except (TypeError, ValueError):
                score = 0.0
            self._ocr_confidence = max(0.0, min(1.0, score))
            self._text_fingerprint = fingerprint
            self._events.append(PerceptionEvent.create(
                "visible_text_updated",
                f"Visible text updated ({len(normalized)} characters, {self._ocr_language or 'unknown language'})",
                source=source,
                dedupe_key=f"ocr:{self._active_key}:{fingerprint}",
                now=self._clock(),
            ))
            return True

    def record_event(
        self, event_type: str, summary: str, *, source: str = "desktop",
        dedupe_key: str = "",
    ) -> bool:
        event = PerceptionEvent.create(
            event_type, summary, source=source, dedupe_key=dedupe_key, now=self._clock()
        )
        with self._lock:
            if self._disposed or not self._active_lifecycle:
                return False
            if dedupe_key and any(event.dedupe_key == dedupe_key for event in self._events):
                return False
            self._events.append(event)
            return True

    def clear_sensitive(self, *, exe: str = "", reason: str = "") -> None:
        """Purge all text/window history before a blocked or unidentified window."""
        with self._lock:
            self._clear_locked()
            if self._active_lifecycle and not self._disposed:
                safe_exe = str(exe or "")[:100].lower()
                safe_reason = str(reason or "privacy_denied")[:64]
                self._events.append(PerceptionEvent.create(
                    "capture_blocked",
                    f"Capture blocked for {safe_exe or 'unidentified window'} ({safe_reason})",
                    source="privacy",
                    dedupe_key=f"blocked:{safe_exe}:{safe_reason}",
                    now=self._clock(),
                ))

    def _clear_locked(self) -> None:
        self._active = None
        self._active_key = None
        self._active_since = None
        self._active_observed_at = None
        self._visible_text = ""
        self._ocr_language = ""
        self._ocr_confidence = 0.0
        self._text_fingerprint = ""
        self._events.clear()

    def clear(self) -> None:
        with self._lock:
            self._clear_locked()

    @property
    def active_window_key(self) -> tuple[int, int] | None:
        with self._lock:
            return self._active_key

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            duration = max(0.0, self._clock() - self._active_since) if self._active_since is not None else 0.0
            return {
                "active_window": dict(self._active) if self._active else None,
                "active_seconds": duration,
                "active_observed_at": self._active_observed_at.isoformat() if self._active_observed_at else None,
                "visible_text": self._visible_text,
                "ocr_language": self._ocr_language,
                "ocr_confidence": self._ocr_confidence,
                "recent_events": tuple(event.to_dict() for event in self._events),
            }

    def summary(self, max_chars: int = MAX_SUMMARY_CHARS) -> str:
        """Return bounded desktop context, prioritizing the newest visual observations."""
        try:
            limit = max(0, min(MAX_SUMMARY_CHARS, int(max_chars)))
        except (TypeError, ValueError):
            limit = MAX_SUMMARY_CHARS
        if not limit:
            return ""
        data = self.snapshot()
        active = data["active_window"]
        if not active:
            return ""

        duration = int(data["active_seconds"])
        lines = [
            "DESKTOP CONTEXT (local perception; facts only):",
            f"Active application: {active['exe']}",
            f"Active window: {active['title']}",
            f"Time in foreground: {duration // 60}m {duration % 60}s",
        ]

        def append_bounded(line: str) -> bool:
            current = "\n".join(lines)
            remaining = limit - len(current) - 1
            if remaining <= 0:
                return False
            value = str(line)
            if len(value) > remaining:
                lines.append(value[:max(0, remaining - 1)].rstrip() + "…")
                return False
            lines.append(value)
            return True

        observed_at_value = data.get("active_observed_at")
        if observed_at_value:
            try:
                observed_at = datetime.fromisoformat(observed_at_value)
                now = self._wall_clock()
                if observed_at.tzinfo is None:
                    observed_at = observed_at.replace(tzinfo=timezone.utc)
                if now.tzinfo is None:
                    now = now.replace(tzinfo=timezone.utc)
                age_seconds = max(0, int((now - observed_at).total_seconds()))
                age_label = f"{age_seconds}s" if age_seconds < 60 else f"{age_seconds // 60}m {age_seconds % 60}s"
                freshness = "fresh" if age_seconds <= 15 else "recent" if age_seconds <= 60 else "stale"
            except (TypeError, ValueError):
                freshness, age_label = "unknown", "unknown"
            append_bounded(
                f"Foreground window identity freshness: {freshness}; age: {age_label} "
                "(window identity only; this is not visual verification of screen content)."
            )

        events = list(data["recent_events"])
        visual_events = [event for event in events if event.get("type") == "visual_observation"]
        if visual_events:
            # The newest observation is the only candidate for the current screen
            # state. Older observations are explicitly historical so the model
            # cannot blend them into a false description of what is on screen now.
            latest = visual_events[-1]
            try:
                observed_at = datetime.fromisoformat(latest["timestamp"])
                if observed_at.tzinfo is None:
                    observed_at = observed_at.replace(tzinfo=timezone.utc)
                age_seconds = max(0, int((self._wall_clock() - observed_at).total_seconds()))
                age_label = f"{age_seconds}s" if age_seconds < 60 else f"{age_seconds // 60}m {age_seconds % 60}s"
                freshness = "fresh" if age_seconds <= 15 else "recent" if age_seconds <= 60 else "stale"
            except (KeyError, TypeError, ValueError):
                age_label, freshness = "unknown", "unknown"
            source = str(latest.get("source") or "desktop")[:16]
            append_bounded(
                f"CURRENT SCREEN STATE (freshness: {freshness}; observation age: {age_label}; "
                f"source: {source}):"
            )
            append_bounded(f"Latest known screen state: {latest.get('summary', '')}")

            older_visual_events = visual_events[:-1]
            if older_visual_events and append_bounded(
                "Earlier visual observations (historical context only; not the current screen state):"
            ):
                for event in reversed(older_visual_events[-2:]):
                    try:
                        event_time = datetime.fromisoformat(event["timestamp"]).strftime("%H:%M:%S")
                    except (KeyError, TypeError, ValueError):
                        event_time = "--:--:--"
                    if not append_bounded(f"- {event_time} {event.get('summary', '')}"):
                        break

        if data["visible_text"]:
            ocr_events = [event for event in events if event.get("type") == "visible_text_updated"]
            ocr_freshness, ocr_age = "unknown", "unknown"
            if ocr_events:
                try:
                    observed_at = datetime.fromisoformat(ocr_events[-1]["timestamp"])
                    if observed_at.tzinfo is None:
                        observed_at = observed_at.replace(tzinfo=timezone.utc)
                    age_seconds = max(0, int((self._wall_clock() - observed_at).total_seconds()))
                    ocr_age = f"{age_seconds}s" if age_seconds < 60 else f"{age_seconds // 60}m {age_seconds % 60}s"
                    ocr_freshness = "fresh" if age_seconds <= 15 else "recent" if age_seconds <= 60 else "stale"
                except (KeyError, TypeError, ValueError):
                    pass
            append_bounded(f"OCR observation freshness: {ocr_freshness}; age: {ocr_age}.")
            append_bounded(
                f"Visible on-screen text [{data['ocr_language'] or 'unknown'}, "
                f"confidence {data['ocr_confidence']:.2f}]: {data['visible_text']}"
            )

        other_events = [event for event in events if event.get("type") != "visual_observation"]
        if other_events and append_bounded("Recent window events (newest first):"):
            for event in reversed(other_events[-3:]):
                try:
                    event_time = datetime.fromisoformat(event["timestamp"]).strftime("%H:%M:%S")
                except (TypeError, ValueError):
                    event_time = "--:--:--"
                if not append_bounded(f"- {event_time} {event.get('summary', '')}"):
                    break

        value = "\n".join(lines)
        return value if len(value) <= limit else value[:max(0, limit - 1)].rstrip() + "…"
