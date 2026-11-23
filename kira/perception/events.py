"""Small, deduplicated facts emitted by the local perception layer."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import time


@dataclass(frozen=True)
class PerceptionEvent:
    event_type: str
    timestamp: str
    summary: str
    source: str = "desktop"
    dedupe_key: str = ""

    @staticmethod
    def fingerprint(value: str) -> str:
        return hashlib.blake2b(str(value or "").encode("utf-8"), digest_size=12).hexdigest()

    @classmethod
    def create(
        cls, event_type: str, summary: str, *, source: str = "desktop",
        dedupe_key: str = "", now: float | None = None,
    ) -> "PerceptionEvent":
        return cls(
            event_type=str(event_type or "event")[:48],
            timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            summary=" ".join(str(summary or "").split())[:260],
            source=str(source or "desktop")[:16],
            dedupe_key=str(dedupe_key or cls.fingerprint(summary))[:120],
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "type": self.event_type,
            "timestamp": self.timestamp,
            "summary": self.summary,
            "source": self.source,
            "dedupe_key": self.dedupe_key,
        }
