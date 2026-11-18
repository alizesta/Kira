"""Safe, opt-in proactive check-in policy for one character's own remembered moments.

The engine is deterministic and side-effect free apart from its explicit mark_sent()
helper. Scheduling, persistence and presentation remain owned by the desktop runtime.
"""
from __future__ import annotations

import hashlib
import math
import re
import time
from datetime import datetime, time as datetime_time, timedelta


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
    value = value.translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789"))
    return value.replace("ي", "ی").replace("ك", "ک").replace("\u200c", " ").replace("\u200f", " ")


def _after_local_day(created_at, days_after_today):
    """Local midnight after the full date on which the remembered event is expected."""
    try:
        local_created = datetime.fromtimestamp(float(created_at))
        event_day = local_created.date() + timedelta(days=max(0, int(days_after_today)))
        return datetime.combine(event_day + timedelta(days=1), datetime_time.min).timestamp()
    except (OverflowError, OSError, TypeError, ValueError):
        # A failed local-calendar conversion must defer, never make the event due early.
        return float(created_at) + (max(0, int(days_after_today)) + 1) * DAY


def _after_next_month(created_at):
    """First local midnight after the next calendar month has fully elapsed."""
    try:
        local_created = datetime.fromtimestamp(float(created_at))
        following_year = local_created.year
        following_month = local_created.month + 2
        if following_month > 12:
            following_year += (following_month - 1) // 12
            following_month = ((following_month - 1) % 12) + 1
        return datetime(following_year, following_month, 1).timestamp()
    except (OverflowError, OSError, TypeError, ValueError):
        return float(created_at) + 32 * DAY


_NUMBER_WORDS = {
    "one": 1, "a": 1, "یک": 1, "یه": 1,
    "two": 2, "دو": 2, "three": 3, "سه": 3,
    "four": 4, "چهار": 4, "five": 5, "پنج": 5,
    "six": 6, "شش": 6, "seven": 7, "هفت": 7,
    "eight": 8, "هشت": 8, "nine": 9, "نه": 9,
    "ten": 10, "ده": 10, "چند": 7,
}
_NUMBER_TOKEN = r"(?:\d{1,3}|one|a|two|three|four|five|six|seven|eight|nine|ten|یک|یه|دو|سه|چهار|پنج|شش|هفت|هشت|نه|ده|چند)"
_DURATION_UNIT = r"(روز|day|days|هفته|week|weeks|ماه|month|months)"


def _duration_days(amount, unit):
    try:
        count = int(amount) if str(amount).isdigit() else _NUMBER_WORDS[str(amount).lower()]
    except (KeyError, TypeError, ValueError):
        return None
    unit = str(unit).lower()
    multiplier = 7 if unit in ("هفته", "week", "weeks") else 30 if unit in ("ماه", "month", "months") else 1
    return max(1, min(365, count * multiplier))


def _event_not_before(text, created_at):
    """Return the first safe local time to ask, after the entire mentioned date has passed.

    The check-in is deliberately deferred to the next local midnight after the stated
    event day. This prevents a morning message about an evening/tomorrow appointment
    from triggering a premature "how did it go?" check-in.
    """
    value = _normalise(text)
    day_offsets = []

    if re.search(r"پس\s*فردا|day\s+after\s+tomorrow", value):
        day_offsets.append(2)
    elif re.search(r"فردا|\btomorrow\b", value):
        day_offsets.append(1)

    # Events later today (or "tonight") are not due until the date is over.
    if re.search(r"امروز|امشب|امروز\s*(?:عصر|بعدازظهر)|\btoday\b|\btonight\b|\bthis\s+(?:afternoon|evening)\b", value):
        day_offsets.append(0)

    if re.search(r"هفته(?:\s+ی)?\s*(?:بعد|آینده)|\bnext\s+week\b", value):
        day_offsets.append(7)
    if re.search(r"آخر\s*هفته|\bthis\s+weekend\b", value):
        day_offsets.append(7)
    if re.search(r"\bnext\s+weekend\b", value):
        day_offsets.append(14)

    # Parse explicit relative durations such as "in two weeks", "3 days from now",
    # "سه روز دیگه", and "دو هفته بعد". A vague count ("چند") is interpreted
    # conservatively; distant dates naturally age out under the 10-day memory window.
    patterns = (
        rf"\b(?:in|after)\s+({_NUMBER_TOKEN})\s*({_DURATION_UNIT})\b",
        rf"({_NUMBER_TOKEN})\s*({_DURATION_UNIT})(?:\s+ی)?\s*(?:from\s+now|later|away|دیگه|دیگر|بعد|آینده)",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, value, re.I):
            days = _duration_days(match.group(1), match.group(2))
            if days is not None:
                day_offsets.append(days)

    due_times = [_after_local_day(created_at, days) for days in day_offsets]

    if re.search(r"ماه(?:\s+ی)?\s*(?:بعد|آینده)|\bnext\s+month\b", value):
        due_times.append(_after_next_month(created_at))

    return max(due_times, default=float(created_at))


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


def initiative_history_state(
    history,
    recent_events=(),
    last_memory_id="",
    last_sent_at=0,
    now=None,
    retention_seconds=DEFAULT_MEMORY_MAX_AGE_SECONDS,
):
    """Return validated sent history, recently used IDs, and a local-calendar daily count.

    The settings record is authoritative; EmotionalRuntime's recent event ring and last
    sent marker are independent recovery evidence. Identical IDs are counted only once.
    """
    current = _finite_number(time.time() if now is None else now)
    if current is None or current < 0:
        return {"history": [], "excluded_ids": set(), "sent_today": 0}

    retention = _bounded_seconds(retention_seconds, DEFAULT_MEMORY_MAX_AGE_SECONDS)
    now_local = time.localtime(current)
    today_key = (now_local.tm_year, now_local.tm_yday)

    def accepted_stamp(value):
        stamp = _finite_number(value)
        if stamp is None or stamp <= 0 or stamp > current + FUTURE_CLOCK_SKEW_SECONDS:
            return None
        if current - stamp > retention:
            return None
        return stamp

    def day_key(stamp):
        local = time.localtime(stamp)
        return local.tm_year, local.tm_yday

    valid_history = []
    excluded = set()
    today_ids = set()

    for entry in history if isinstance(history, list) else ():
        if not isinstance(entry, dict):
            continue
        stamp = accepted_stamp(entry.get("at"))
        if stamp is None:
            continue
        memory_id = str(entry.get("memory_id") or "").strip()[:64]
        valid_history.append({"at": stamp, "memory_id": memory_id})
        if memory_id:
            excluded.add(memory_id)
        if day_key(stamp) == today_key:
            today_ids.add(memory_id or f"at:{int(stamp)}")

    for event in recent_events or ():
        if not isinstance(event, dict) or event.get("name") != "proactive_check_in":
            continue
        stamp = accepted_stamp(event.get("at"))
        if stamp is None:
            continue
        memory_id = str(event.get("detail") or "").strip()[:64]
        if memory_id:
            excluded.add(memory_id)
        if day_key(stamp) == today_key:
            today_ids.add(memory_id or f"at:{int(stamp)}")

    last_stamp = accepted_stamp(last_sent_at)
    last_id = str(last_memory_id or "").strip()[:64]
    if last_stamp is not None:
        if last_id:
            excluded.add(last_id)
        if day_key(last_stamp) == today_key:
            today_ids.add(last_id or f"at:{int(last_stamp)}")

    return {
        "history": valid_history,
        "excluded_ids": excluded,
        "sent_today": len(today_ids),
    }


def build_checkin_message(candidate, language="auto", max_topic_chars=130):
    """Create a brief, no-pressure check-in from the exact remembered quote; never invent details."""
    if not isinstance(candidate, dict) or candidate.get("kind") not in InitiativeEngine.CANDIDATE_KINDS:
        return ""

    raw = _clean_memory_text(candidate.get("text"))
    quoted = re.search(r'\\bhe said\\s+["“](.+)["”](?:\\s*\\(a promise\\))?$', raw, re.I)
    topic = _clean_memory_text(quoted.group(1)) if quoted else ""
    try:
        limit = max(24, min(180, int(max_topic_chars)))
    except (TypeError, ValueError, OverflowError):
        limit = 130
    if len(topic) > limit:
        clipped = topic[:limit]
        # Prefer a complete final word over a mid-word cut. Keep the bounded
        # hard slice when a single token itself is longer than the limit.
        if " " in clipped:
            clipped = clipped.rsplit(" ", 1)[0]
        topic = clipped
    topic = topic.rstrip(" ،,.;:\\u200c") if topic else ""

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
