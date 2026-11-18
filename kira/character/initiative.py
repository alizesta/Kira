"""Safe, opt-in proactive check-in policy for one character's own remembered moments.

The engine is deterministic and side-effect free apart from its explicit mark_sent()
helper. Scheduling, persistence and presentation remain owned by the desktop runtime.
"""
from __future__ import annotations

import hashlib
import math
import re
import time


DAY = 86400
DEFAULT_MINIMUM_IDLE_SECONDS = 45 * 60
DEFAULT_COOLDOWN_SECONDS = 4 * 3600
DEFAULT_MEMORY_MAX_AGE_SECONDS = 10 * DAY
MAX_CHECKINS_PER_DAY = 2
QUIET_START_HOUR = 22
QUIET_END_HOUR = 9
FUTURE_CLOCK_SKEW_SECONDS = 60


def _finite_number(value):
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _bounded_seconds(value, default, *, allow_zero=False):
    number = _finite_number(value)
    if number is None:
        return int(default)
    minimum = 0 if allow_zero else 1
    return int(max(minimum, min(number, 365 * DAY)))


def _normalise(text):
    value = str(text or "").lower()
    return value.replace("ي", "ی").replace("ك", "ک").replace("\u200c", " ").replace("\u200f", " ")


def _event_not_before(text, created_at):
    """Do not ask about an event before an explicit relative future date has arrived."""
    value = _normalise(text)
    offsets = []
    if re.search(r"پس\s*فردا|day\s+after\s+tomorrow", value):
        offsets.append(2 * DAY)
    elif re.search(r"فردا|\btomorrow\b", value):
        offsets.append(DAY)
    if re.search(r"هفته(?:\s+ی)?\s*(?:بعد|آینده)|\bnext\s+week\b", value):
        offsets.append(7 * DAY)
    if re.search(r"ماه(?:\s+ی)?\s*(?:بعد|آینده)|\bnext\s+month\b", value):
        offsets.append(30 * DAY)
    return float(created_at) + max(offsets, default=0)


def _clean_memory_text(value):
    text = re.sub(r"[\x00-\x1f\x7f]+", " ", str(value or ""))
    return " ".join(text.split())[:280].strip()


class InitiativeEngine:
    """Select a due, recent event/promise and enforce quiet, idle and rate limits."""

    CANDIDATE_KINDS = frozenset({"event", "promise"})

    def __init__(
        self,
        minimum_idle_seconds=DEFAULT_MINIMUM_IDLE_SECONDS,
        cooldown_seconds=DEFAULT_COOLDOWN_SECONDS,
        memory_max_age_seconds=DEFAULT_MEMORY_MAX_AGE_SECONDS,
    ):
        self.minimum_idle_seconds = _bounded_seconds(minimum_idle_seconds, DEFAULT_MINIMUM_IDLE_SECONDS)
        self.cooldown_seconds = _bounded_seconds(cooldown_seconds, DEFAULT_COOLDOWN_SECONDS, allow_zero=True)
        self.memory_max_age_seconds = _bounded_seconds(memory_max_age_seconds, DEFAULT_MEMORY_MAX_AGE_SECONDS)
        self.last_initiative = 0.0

    @staticmethod
    def is_quiet_hour(now=None, *, local_hour=None, start_hour=QUIET_START_HOUR, end_hour=QUIET_END_HOUR):
        """Use the operating system's local clock; the default quiet window is 22:00–09:00."""
        try:
            hour = int(local_hour) if local_hour is not None else time.localtime(
                time.time() if now is None else float(now)
            ).tm_hour
            start = int(start_hour)
            end = int(end_hour)
        except (TypeError, ValueError, OverflowError, OSError):
            return True
        if not (0 <= hour <= 23 and 0 <= start <= 23 and 0 <= end <= 23) or start == end:
            return True
        if start < end:
            return start <= hour < end
        return hour >= start or hour < end

    @staticmethod
    def _item_id(item):
        raw = str(item.get("id") or "").strip()
        if raw:
            return raw[:64]
        # Compatibility for callers that supply older memory rows without an ID.
        digest = hashlib.sha256(
            f"{item.get('kind', '')}|{item.get('text', '')}".encode("utf-8", errors="replace")
        ).hexdigest()[:24]
        return f"legacy-{digest}"

    def select_candidate(self, items, now=None, exclude_id=None, exclude_ids=None):
        """Return the newest due event/promise, excluding recently contacted memory IDs.

        Static facts, jokes, summaries, malformed rows, future timestamps and expired
        memories never become unsolicited check-ins.
        """
        current = _finite_number(time.time() if now is None else now)
        if current is None or current < 0:
            return None

        if isinstance(exclude_ids, (str, bytes)):
            exclude_values = (exclude_ids,)
        else:
            exclude_values = exclude_ids or ()
        excluded = {str(value) for value in exclude_values if str(value or "").strip()}
        if exclude_id:
            excluded.add(str(exclude_id))
        candidates_by_id = {}

        for item in items or ():
            if not isinstance(item, dict) or item.get("group") != "moment":
                continue
            kind = str(item.get("kind") or "")
            if kind not in self.CANDIDATE_KINDS:
                continue

            memory_id = self._item_id(item)
            if memory_id in excluded:
                continue

            stamp = _finite_number(item.get("ts"))
            if stamp is None or stamp <= 0 or stamp > current + FUTURE_CLOCK_SKEW_SECONDS:
                continue
            age = max(0.0, current - stamp)
            if age > self.memory_max_age_seconds:
                continue

            text = _clean_memory_text(item.get("text"))
            if not text or current < _event_not_before(text, stamp):
                continue

            selected = dict(item)
            selected.update({"id": memory_id, "kind": kind, "text": text, "ts": stamp})
            previous = candidates_by_id.get(memory_id)
            if previous is None or stamp > previous["ts"]:
                candidates_by_id[memory_id] = selected

        candidates = list(candidates_by_id.values())
        if not candidates:
            return None
        candidates.sort(key=lambda item: (item["ts"], item["kind"] == "promise"), reverse=True)
        return candidates[0]

    def evaluate(
        self,
        now=None,
        last_interaction=0,
        busy=False,
        enabled=False,
        app_active=True,
        quiet_hours=False,
        has_relevant_memory=False,
        sent_today=0,
    ):
        """Eligibility check only. The caller marks a check-in after it is saved successfully."""
        current = _finite_number(time.time() if now is None else now)
        if current is None or current < 0:
            return {"eligible": False, "reason": "invalid_time", "idle_seconds": 0.0}

        interaction = _finite_number(last_interaction)
        if interaction is None or interaction < 0 or interaction > current + FUTURE_CLOCK_SKEW_SECONDS:
            return {"eligible": False, "reason": "invalid_activity_time", "idle_seconds": 0.0}
        # Zero means there is no recorded interaction timestamp, not that the user has
        # been away since the Unix epoch. Unknown activity must never trigger a check-in.
        if interaction == 0:
            interaction = current
        idle = max(0.0, current - interaction)

        if not enabled or not app_active or quiet_hours or busy:
            return {"eligible": False, "reason": "policy_blocked", "idle_seconds": idle}
        if idle < self.minimum_idle_seconds:
            return {"eligible": False, "reason": "not_idle_long_enough", "idle_seconds": idle}

        last_sent = _finite_number(self.last_initiative)
        if last_sent is None or last_sent < 0 or last_sent > current + FUTURE_CLOCK_SKEW_SECONDS:
            if self.last_initiative not in (None, 0, 0.0, ""):
                return {"eligible": False, "reason": "invalid_initiative_time", "idle_seconds": idle}
            last_sent = 0.0
        if last_sent > 0 and current - last_sent < self.cooldown_seconds:
            return {"eligible": False, "reason": "cooldown", "idle_seconds": idle}

        try:
            sent_count = max(0, int(sent_today))
        except (TypeError, ValueError, OverflowError):
            return {"eligible": False, "reason": "invalid_daily_count", "idle_seconds": idle}
        if sent_count >= MAX_CHECKINS_PER_DAY:
            return {"eligible": False, "reason": "daily_limit", "idle_seconds": idle}
        if not has_relevant_memory:
            return {"eligible": False, "reason": "nothing_relevant_to_recall", "idle_seconds": idle}

        return {"eligible": True, "reason": "relevant_memory_after_idle", "idle_seconds": idle}

    def mark_sent(self, now=None):
        """Update the in-memory cooldown only after the caller confirms persistence."""
        sent_at = _finite_number(time.time() if now is None else now)
        if sent_at is None or sent_at < 0:
            raise ValueError("initiative timestamp must be a finite non-negative number")
        self.last_initiative = sent_at
        return sent_at


def build_checkin_message(candidate, language="auto", max_topic_chars=130):
    """Create a brief, no-pressure check-in from the exact remembered quote; never invent details."""
    if not isinstance(candidate, dict) or candidate.get("kind") not in InitiativeEngine.CANDIDATE_KINDS:
        return ""

    raw = _clean_memory_text(candidate.get("text"))
    quoted = re.search(r'\bhe said\s+["“](.+?)["”](?:\s*\(a promise\))?$', raw, re.I)
    topic = _clean_memory_text(quoted.group(1)) if quoted else ""
    try:
        limit = max(24, min(180, int(max_topic_chars)))
    except (TypeError, ValueError, OverflowError):
        limit = 130
    topic = topic[:limit].rstrip(" ،,.;:") if topic else ""

    lang = str(language or "").lower()
    if lang not in ("fa", "en"):
        lang = "fa" if re.search(r"[\u0600-\u06ff]", raw) else "en"

    if lang == "fa":
        if not topic:
            return "راستی، درباره‌ی اون موضوعی که قبلاً گفتی خبری شد؟"
        if candidate.get("kind") == "promise":
            return f"راستی، درباره‌ی «{topic}» که گفته بودی خبرش رو می‌دی، خبری شد؟"
        return f"راستی، درباره‌ی «{topic}» که گفتی، آخرش چی شد؟"

    if not topic:
        return "By the way, did you have any update on the thing you mentioned earlier?"
    if candidate.get("kind") == "promise":
        return f"By the way, any update on “{topic}” that you said you'd let me know about?"
    return f"By the way, how did “{topic}” go?"
