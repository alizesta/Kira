"""Kira's model-independent memory: three layers that keep her the same person on every model.

The chat history alone cannot do that: a model that only sees the last few messages copies its own habits.
These layers are stored locally and injected into the system prompt on every request, whichever provider answers:

1. Voice memory   - Kira's own past replies that sound like her (short, in character). Shown as samples so a new
                    model imitates the real rhythm, slang and attitude instead of its default style.
2. Fact memory    - lasting things about the user and the relationship (name, likes, "remember that ..."),
                    extracted locally from what he writes. No extra model call is needed.
3. Digest memory  - a compact digest of what was talked about earlier, beyond the messages sent verbatim.
4. Relationship memory - dated moments he mentioned (exams, trips, promises), lines of hers that made him laugh, preferences he
                    stated, habits OBSERVED from timing (marked as observed, never as something he said), and compressed
                    summaries of old conversations. Everything is local, rule-based (no extra model call), listable, editable
                    and deletable (list_items / update_item / delete_item / forget_all).

Nothing here touches routing; ``build_block()`` returns plain text that personality.build_system_prompt() appends.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
from contextlib import contextmanager
from contextvars import ContextVar
import os
import re
import threading
import time

from . import evidence_memory as _evidence      # facts with provenance + relevance-based recall (this module stays the owner of the editable list)
from .evidence_memory_index import _CORRECTION_RX, _UNCERTAIN_RX, norm as _evidence_norm
from .config import DATA_DIR

FILE_NAME = "kira_persona_memory.json"
MAX_VOICE = 30
MAX_FACTS = 40
VOICE_SHOWN = 5
FACTS_SHOWN = 14
DIGEST_LINES = 8
BLOCK_BUDGET = 4200
MAX_MOMENTS = 30
MOMENTS_SHOWN = 8
MAX_SUMMARIES = 12
SUMMARIES_SHOWN = 3
SUMMARY_CHUNK = 30                 # fold old messages into a summary once this many have aged out of the verbatim window
SUMMARY_KEEP = 40                  # newest messages beyond the context window that are NOT summarised yet (the digest covers them)
HABIT_MIN_MESSAGES = 15            # habits are only reported after this many messages (no conclusions from a handful)
DAY = 86400
TTL = {"event": 45 * DAY, "promise": 30 * DAY, "joke": 120 * DAY}

_lock = threading.Lock()
_log = logging.getLogger(__name__)
_current_character = ContextVar("ai1_persona_memory_character", default="kira")


def _safe_character_id(value):
    value = re.sub(r"[^a-z0-9_-]", "", str(value or "kira").strip().lower())[:32]
    return value or "kira"


@contextmanager
def character_scope(character_id="kira"):
    """Select the isolated long-term memory file for one character in this execution context."""
    token = _current_character.set(_safe_character_id(character_id))
    try:
        yield
    finally:
        _current_character.reset(token)


def current_character_id():
    return _current_character.get()


def set_active_character(character_id):
    """Switch the memory store used by the app for the active character profile."""
    safe_id = _safe_character_id(character_id)
    _current_character.set(safe_id)
    _last_reply[safe_id] = ""
    return safe_id


_TAG = re.compile(r"^\s*\[[^\]\n]{1,30}\]\s*")
_BAD_VOICE = ("http://", "https://", "```", "[نتایج", "language model", "as an ai", "مدل زبانی", "به عنوان یک هوش", "how can i help", "چطور می‌توانم کمک")


def _path():
    character_id = _current_character.get()
    return DATA_DIR / (FILE_NAME if character_id == "kira" else f"kira_persona_memory_{character_id}.json")


def _voice_path():
    """Kira keeps her voice samples in the legacy store; other characters get their own file."""
    character_id = _current_character.get()
    if character_id == "kira":
        return None
    return DATA_DIR / "characters" / character_id / "voice_memory.json"


def _empty() -> dict:
    return {"voice": [], "facts": [], "moments": [], "summaries": [], "habits": {"hours": [0] * 24, "messages": 0, "chars": 0, "first_seen": 0, "days": []}, "summarized": 0}


def _load() -> dict:
    """Load each persisted section independently so one damaged field cannot erase valid memories."""
    data = _empty()
    try:
        raw = json.loads(_path().read_text(encoding="utf-8"))
    except FileNotFoundError:
        raw = {}
    except (OSError, ValueError, TypeError):
        _log.warning("Unable to read persona memory for character %s", _current_character.get(), exc_info=True)
        raw = {}

    if isinstance(raw, dict):
        voice = raw.get("voice")
        if isinstance(voice, list):
            data["voice"] = [value for value in voice if isinstance(value, str)][-MAX_VOICE:]

        for key, limit in (("facts", MAX_FACTS), ("moments", MAX_MOMENTS), ("summaries", MAX_SUMMARIES)):
            values = raw.get(key)
            if isinstance(values, list):
                data[key] = [
                    item for item in values[-limit:]
                    if isinstance(item, dict) and isinstance(item.get("text"), str) and item["text"].strip()
                ]

        habits = raw.get("habits")
        if isinstance(habits, dict):
            hours = habits.get("hours")
            if isinstance(hours, list) and len(hours) == 24:
                def finite_number(value, default=0.0):
                    try:
                        number = float(value)
                        return number if math.isfinite(number) else float(default)
                    except (TypeError, ValueError, OverflowError):
                        return float(default)

                def safe_count(value):
                    return max(0, min(10**9, int(finite_number(value))))

                data["habits"] = {
                    "hours": [safe_count(value) for value in hours],
                    "messages": safe_count(habits.get("messages")),
                    "chars": safe_count(habits.get("chars")),
                    "first_seen": max(0.0, finite_number(habits.get("first_seen"))),
                    "days": [str(day)[:10] for day in habits.get("days", []) if isinstance(day, (str, int, float))][-400:]
                    if isinstance(habits.get("days", []), list) else [],
                }

        try:
            data["summarized"] = max(0, min(10**9, int(raw.get("summarized") or 0)))
        except (TypeError, ValueError, OverflowError):
            data["summarized"] = 0

    voice_path = _voice_path()
    if voice_path is not None:
        try:
            payload = json.loads(voice_path.read_text(encoding="utf-8"))
            samples = payload.get("voice", []) if isinstance(payload, dict) else []
            if isinstance(samples, list):
                data["voice"] = [sample for sample in samples if isinstance(sample, str)][-MAX_VOICE:]
        except FileNotFoundError:
            pass
        except (OSError, ValueError, TypeError):
            _log.warning("Unable to read voice memory for character %s", _current_character.get(), exc_info=True)
    return data


def _save(data: dict):
    path = _path()
    voice_path = _voice_path()
    try:
        if voice_path is not None:
            voice_path.parent.mkdir(parents=True, exist_ok=True)
            voice_path.write_text(json.dumps(
                {"schema": 1, "character_id": _current_character.get(),
                 "voice": list(data.get("voice") or [])[-MAX_VOICE:]},
                ensure_ascii=False, indent=1), encoding="utf-8")
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        _log.warning("Unable to persist persona memory for character %s", _current_character.get(), exc_info=True)


def _id(kind: str, text: str) -> str:
    return hashlib.sha1(f"{kind}|{text}".encode("utf-8")).hexdigest()[:8]


def item_id(kind: str, text: str) -> str:
    """The id an item gets in the memory window (the evidence layer stores it to stay linked with the editable list)."""
    return _id(kind, text)


def clean_reply(raw: str) -> str:
    return _TAG.sub("", str(raw or "")).strip()


# ---------------- layer 1: voice ----------------
def is_voice_sample(text: str) -> bool:
    t = text.strip()
    low = t.lower()
    if not (12 <= len(t) <= 240) or any(b in low for b in _BAD_VOICE):
        return False
    from .style_probe import classify
    return not classify(t)               # a reply that drifted (rude, prim, stiff) must never become the style anchor of the next model


# ---------------- layer 2: facts ----------------
_FACT_RULES = (
    (re.compile(r"(?:یادت\s*باشه|یادت\s*باشد|یادت\s*نره|remember\s+that|remember\s+this[:,]?)\s*[:،,]?\s*(.{3,140})", re.I), "note", 3),
    (re.compile(r"(?:اسم\s*من|اسمم|اسم\s*خودم)\s*(?:رو\s*)?(?:هست\s*|ـه\s*)?[:،]?\s*([^\s.,!؟?،]{2,20})"), "name", 2),
    (re.compile(r"my\s+name\s+is\s+([A-Za-z][\w'-]{1,20})", re.I), "name", 2),
    (re.compile(r"(?:من\s+)?(\d{1,2})\s*سالمه"), "age", 1),
    (re.compile(r"i\s*(?:am|'m)\s+(\d{1,2})\s+years?\s+old", re.I), "age", 1),
    (re.compile(r"(?:دوست\s*دارم|عاشق\s+(.{2,60}?)\s+هستم)\s*(.{0,60})"), "like", 1),
    (re.compile(r"(?:i\s+(?:really\s+)?(?:love|like|enjoy))\s+(.{2,60})", re.I), "like", 1),
    (re.compile(r"(?:ازش\s*متنفرم|متنفرم\s+از|بدم\s+میاد\s+از)\s*(.{2,60})"), "dislike", 1),
    (re.compile(r"i\s+(?:really\s+)?(?:hate|can't stand)\s+(.{2,60})", re.I), "dislike", 1),
    (re.compile(r"(?:شغلم|کارم)\s*(?:رو\s*)?(.{2,40})\s*(?:هست|ـه|است)"), "job", 1),
    (re.compile(r"i\s+work\s+as\s+(?:an?\s+)?(.{2,40})", re.I), "job", 1),
    (re.compile(r"(?:اهل|ساکن)\s+([^\s.,!؟?،]{2,25})\s*(?:هستم|م|ام)"), "place", 1),
    (re.compile(r"i\s+live\s+in\s+([A-Za-z][\w\s'-]{1,25})", re.I), "place", 1),
)
_PREF_RULES = (
    (re.compile(r"(?:کوتاه(?:\s*تر)?|مختصر)\s*(?:جواب|پاسخ)?\s*(?:بده|بگو)|keep\s+(?:it|answers?|replies)\s+short", re.I), "pref_len", "He prefers short answers"),
    (re.compile(r"(?:مفصل|کامل|طولانی)(?:\s*تر)?\s*(?:جواب|پاسخ)?\s*(?:بده|بگو)|more\s+detail", re.I), "pref_len", "He prefers detailed answers"),
    (re.compile(r"(?:صدام\s*کن|بهم\s*بگو|منو\s*صدا\s*کن)\s+([^\s.,!؟?،]{2,20})|call\s+me\s+([A-Za-z][\w'-]{1,20})", re.I), "nick", "He likes to be called {}"),
)
_LABELS = {"pref_len": "{}", "nick": "He likes to be called {}", "name": "His name is {}", "age": "He is {} years old", "like": "He likes {}", "dislike": "He dislikes {}",
           "job": "His work: {}", "place": "He is from/lives in {}", "note": "He asked her to remember: {}"}


_QUESTION_RX = re.compile(
    r"(?:^|\s)(?:چیه|چیست|چی\s*هست|کیه|کجاست|چنده|کجام|کدومه|چند\s*سالمه|یادته|یادت\s*هست|می\s*دونی|میدونی|می\s*دانی|آیا)(?:\s|$)"
    r"|^(?:do|does|did|can|could|would|will|what|what's|who|where|how|why|is|are|am)\b|\bdo\s+you\s+(?:know|remember)\b", re.I)
_NOT_A_NAME = {"چیه", "چیست", "چی", "کیه", "کی", "هست", "است", "رو", "را", "چطوره", "یادت", "یاد", "بذار", "عوض", "تغییر", "بگو", "صدا"}   # "اسمم رو یادت باشه" is a request, not a name
_WISH_VERBS = {"بدونم", "بدانم", "بپرسم", "بفهمم", "ببینم", "بگم", "بگویم", "برم", "بروم", "بیام", "بیایم", "بخونم", "بخوانم", "بخرم", "بنویسم",
               "بکنم", "بکشم", "بمونم", "بشنوم", "بخوابم", "باشم", "بزنم", "بسازم", "بخورم", "بیارم", "ببرم", "بذارم", "بشینم", "بخندم", "بشم",
               "بدم", "بتونم", "بتوانم", "بگیرم", "بفرستم", "بشناسم", "بیاموزم", "یاد بگیرم"}
_ASKING_WORDS = {"چی", "چیه", "چرا", "چطور", "چگونه", "کی", "کجا", "کجاست", "چه", "کدوم", "آیا", "که"}


def _norm_part(text: str) -> str:
    return text.replace("ي", "ی").replace("ك", "ک").replace("\u200c", " ")


def _clean_value(kind: str, value: str) -> str:
    """"" when the captured value cannot be trusted as a fact; otherwise the tidy value."""
    value = value.strip(" ,.:؛،")
    words = _norm_part(value).split()
    if not words:
        return ""
    if kind == "name":
        if value.endswith("ست") and len(value) >= 4:
            value = value[:-2]                                                  # "علیرضاست" -> "علیرضا"
        if value in _NOT_A_NAME:
            return ""
    elif kind == "place" and value in _ASKING_WORDS:
        return ""
    elif kind in ("like", "dislike"):
        low = " ".join(words).lower()
        if any(w in _ASKING_WORDS for w in words) or any(w in _WISH_VERBS for w in words) or "یاد بگیرم" in low:
            return ""                                          # "دوست دارم بدونم این چیه" is a wish/question, not a like
        if re.match(r"(?:to\s+(?:know|ask|understand|see|find)|what|why|how|when|where|who|if|whether)\b", low):
            return ""
    return value


# U+FF1F is the fullwidth question mark; it counts as a question mark like "?" and the Persian "؟" (U+061F).
def extract_facts_detailed(text: str) -> list[dict]:
    """Facts found in one user message, each with the evidence that justifies it:
    {'kind', 'label' (the stored sentence), 'value', 'quote' (the exact words he wrote), 'uncertain' (he hedged), 'correction' (he corrected himself)}.
    Only short statements; questions are ignored."""
    found = []
    for m_part in re.finditer(r"([^\n.!؟?\uff1f]+)([.!؟?\uff1f]*)", str(text or "")):
        part, ending = m_part.group(1).strip(), m_part.group(2)
        if not 4 <= len(part) <= 160 or "?" in ending or "؟" in ending or "\uff1f" in ending:
            continue                                           # questions (the mark is checked BEFORE the text is split) are never facts
        if _QUESTION_RX.search(_norm_part(part)):
            continue                                           # a question written without the mark
        normalized_part = _evidence_norm(part)
        flags = {"uncertain": bool(_UNCERTAIN_RX.search(normalized_part)), "correction": bool(_CORRECTION_RX.search(normalized_part))}
        pref = False
        for rx, kind, template in _PREF_RULES:
            m = rx.search(_norm_part(part))
            if m:
                value = " ".join(g for g in m.groups() if g) if m.groups() else ""
                if kind == "nick" and not value:
                    continue
                label = template.format(value) if "{}" in template else template
                found.append({"kind": kind, "label": label, "value": value or label, "quote": part, **flags})
                pref = True
                break
        if pref:
            continue
        for rx, kind, _weight in _FACT_RULES:
            m = rx.search(part)
            if not m:
                continue
            value = " ".join(g.strip() for g in m.groups() if g and g.strip()).strip(" ,.:؛،")
            value = _clean_value(kind, value) if value else ""
            if value:
                found.append({"kind": kind, "label": _LABELS[kind].format(value), "value": value, "quote": part, **flags})
            break
    return found


def extract_facts(text: str) -> list[tuple[str, str]]:
    """(kind, sentence) pairs found in one user message. Only short statements; questions are ignored."""
    return [(d["kind"], d["label"]) for d in extract_facts_detailed(text)]


def add_fact(kind: str, text: str, now=None):
    now = time.time() if now is None else now
    with _lock:
        data = _load()
        facts = data["facts"]
        single = kind in ("name", "age", "job", "place", "nick", "pref_len")
        facts[:] = [f for f in facts if f["text"] != text and not (single and f.get("kind") == kind)]
        facts.append({"kind": kind, "text": text, "ts": int(now), "id": _id(kind, text)})
        notes = [f for f in facts if f.get("kind") == "note"]
        others = [f for f in facts if f.get("kind") != "note"]
        data["facts"] = (others[-(MAX_FACTS - min(len(notes), 15)):] + notes[-15:])
        _save(data)


def facts() -> list[str]:
    with _lock:
        return [f["text"] for f in _load()["facts"]]


def forget_facts():
    with _lock:
        data = _load()
        data["facts"] = []
        _save(data)


# ---------------- relationship memory: moments, jokes, habits ----------------
_TIME_RX = re.compile(r"امروز|دیروز|دیشب|امشب|فردا|پس\s*فردا|هفته\s*(?:ی\s*)?(?:پیش|بعد|آینده|گذشته)|آخر\s*هفته|\btoday\b|\byesterday\b|\btonight\b|\btomorrow\b|\blast\s+week\b|\bnext\s+week\b", re.I)
_EVENT_RX = re.compile(r"امتحان|مصاحبه|قرار|تولد|سفر|عروسی|جلسه|کنکور|دکتر|پروژه|تحویل|نتیجه|\bexam\b|\binterview\b|\bbirthday\b|\btrip\b|\bwedding\b|\bmeeting\b|\bdoctor\b|\bdeadline\b|\bproject\b", re.I)
_PROMISE_RX = re.compile(r"قول\s*(?:می\s*دم|میدم|دادم)|بهت\s*(?:خبر\s*)?می\s*دم|بعداً?\s*بهت\s*می\s*گم|\bi\s+promise\b", re.I)
_LAUGH_RX = re.compile(r"😂|🤣|هاها|ههه|هه\s*هه|\blol\b|\blmao\b", re.I)
_last_reply = {}


def _sentences(text: str):
    for m in re.finditer(r"([^\n.!؟?\uff1f]+)([.!؟?\uff1f]*)", str(text or "")):
        part, end = m.group(1).strip(), m.group(2)
        if 8 <= len(part) <= 160 and not any(q in end for q in "?؟\uff1f") and not _QUESTION_RX.search(_norm_part(part)):
            yield part


def extract_moments(text: str) -> list[tuple[str, str]]:
    """(kind, sentence) for dated events and promises he states. Conservative: time word + event word, or an explicit promise."""
    out = []
    for part in _sentences(text):
        norm = _norm_part(part)
        if _PROMISE_RX.search(norm):
            out.append(("promise", part))
        elif _TIME_RX.search(norm) and _EVENT_RX.search(norm):
            out.append(("event", part))
    return out[:2]


def add_moment(kind: str, text: str, now=None):
    now = time.time() if now is None else now
    with _lock:
        data = _load()
        if any(m["text"] == text for m in data["moments"]):
            return
        data["moments"].append({"kind": kind, "text": text, "ts": int(now), "id": _id(kind, text)})
        data["moments"] = data["moments"][-MAX_MOMENTS:]
        _save(data)


def _label_moment(kind: str, text: str, now: float) -> str:
    day = time.strftime("%Y-%m-%d", time.localtime(now))
    if kind == "joke":
        return text
    return f"{day}: he said \"{text[:140]}\"" + (" (a promise)" if kind == "promise" else "")


def _note_habits(content: str, now: float):
    with _lock:
        data = _load()
        h = data["habits"]
        h["hours"][time.localtime(now).tm_hour] += 1
        h["messages"] += 1
        h["chars"] += min(len(content), 400)
        h["first_seen"] = h["first_seen"] or now
        day = time.strftime("%Y-%m-%d", time.localtime(now))
        if day not in h["days"]:
            h["days"] = (h["days"] + [day])[-400:]
        _save(data)


def habit_lines(now=None) -> list[str]:
    """Habits measured from timing/length, clearly marked as observed (he never said them). Empty until there is enough data."""
    with _lock:
        h = _load()["habits"]
    lines = []
    if h["first_seen"] and len(h["days"]) >= 2:
        lines.append(f"They have been talking since {time.strftime('%Y-%m-%d', time.localtime(h['first_seen']))}; he has chatted on {len(h['days'])} different days.")
    if h["messages"] >= HABIT_MIN_MESSAGES:
        bands = {"at night (00-06)": sum(h["hours"][0:6]), "in the morning (06-12)": sum(h["hours"][6:12]),
                 "in the afternoon (12-18)": sum(h["hours"][12:18]), "in the evening (18-24)": sum(h["hours"][18:24])}
        name, count = max(bands.items(), key=lambda kv: kv[1])
        if count / h["messages"] >= 0.45:
            lines.append(f"Observed (he never said it): he mostly talks to her {name}.")
        avg = h["chars"] / h["messages"]
        if avg < 35:
            lines.append("Observed: he usually writes short messages.")
        elif avg > 180:
            lines.append("Observed: he usually writes long, detailed messages.")
    return lines


# ---------------- observing the conversation ----------------
def observe(role: str, content: str, now=None):
    """Called for every saved message. Learns only into the active character's local memory file. Never raises."""
    character_id = _current_character.get()
    now = time.time() if now is None else now
    try:
        if role == "assistant":
            text = clean_reply(content)
            _last_reply[character_id] = text
            if is_voice_sample(text):
                with _lock:
                    data = _load()
                    if text not in data["voice"]:
                        data["voice"] = (data["voice"] + [text])[-MAX_VOICE:]
                        _save(data)
        elif role == "user":
            details = extract_facts_detailed(content)
            for d in details:
                add_fact(d["kind"], d["label"], now)
                d["persona_id"] = _id(d["kind"], d["label"])
            moments = extract_moments(content)
            moment_ids = []
            for kind, sentence in moments:
                label = _label_moment(kind, sentence, now)
                add_moment(kind, label, now)
                moment_ids.append((kind, sentence, _id(kind, label)))
            if character_id == "kira":
                _evidence.record_user_message(content, facts=details, moments=moment_ids, now=now)  # Kira's evidence index remains Kira-only
            last_reply = _last_reply.get(character_id, "")
            if last_reply and _LAUGH_RX.search(str(content)) and is_voice_sample(last_reply):
                add_moment("joke", f"A line of {character_id.title()} that made the user laugh: \"{last_reply[:140]}\"", now)
            _note_habits(str(content), now)
    except Exception:                                             # noqa: BLE001
        _log.warning(
            "Persona-memory observation failed for character %s (role=%s)",
            character_id,
            str(role or "")[:24],
            exc_info=True,
        )


def forget_conversation():
    """Chat history was cleared: drop the voice samples and the summaries made from it (facts, moments and habits stay until forgotten explicitly)."""
    _last_reply[_current_character.get()] = ""
    with _lock:
        data = _load()
        data["voice"] = []
        data["summaries"] = []
        data["summarized"] = 0
        _save(data)


def forget_all():
    """Forget persona and evidence memory; evidence deletion must succeed before the persona store is cleared."""
    character_id = _current_character.get()
    if character_id == "kira":
        _evidence.forget_all()
    with _lock:
        _save(_empty())
    _last_reply[character_id] = ""


# ---------------- view / edit ----------------
def _expired(item: dict, now: float) -> bool:
    ttl = TTL.get(item.get("kind"))
    return bool(ttl and item.get("ts") and item["ts"] + ttl < now)


def list_items(now=None) -> list[dict]:
    """Everything editable, newest last: [{'id','group','kind','text','ts'}]. group = fact | moment | summary."""
    now = time.time() if now is None else now
    with _lock:
        data = _load()
    out = []
    for group, key in (("fact", "facts"), ("moment", "moments"), ("summary", "summaries")):
        for it in data[key]:
            if group == "moment" and _expired(it, now):
                continue
            kind = it.get("kind", "summary" if group == "summary" else "fact")
            out.append({"id": it.get("id") or _id(kind, it["text"]), "group": group, "kind": kind, "text": it["text"], "ts": it.get("ts", 0)})
    if _current_character.get() == "kira":
        out.extend(_evidence.list_extra_items({i["id"] for i in out}))    # evidence-backed facts belong to Kira only
    return out


def delete_item(item_id: str) -> bool:
    if str(item_id).startswith("ev:"):
        return _evidence.delete_extra(item_id) if _current_character.get() == "kira" else False

    character_id = _current_character.get()
    with _lock:
        data = _load()
        item = next(
            (
                (key, entry)
                for key in ("facts", "moments", "summaries")
                for entry in data[key]
                if (entry.get("id") or _id(entry.get("kind", "summary"), entry["text"])) == item_id
            ),
            None,
        )
    if item is None:
        return False

    # Remove the searchable copy first. A database failure leaves the editable
    # persona item intact instead of silently orphaning stale evidence.
    if character_id == "kira":
        _evidence.delete_by_persona_id(item_id)
    return _delete_persona_item(item_id)


def _delete_persona_item(item_id: str) -> bool:
    with _lock:
        data = _load()
        for key in ("facts", "moments", "summaries"):
            for it in data[key]:
                if (it.get("id") or _id(it.get("kind", "summary"), it["text"])) == item_id:
                    data[key].remove(it)
                    _save(data)
                    return True
    return False


def update_item(item_id: str, text: str) -> bool:
    text = " ".join(str(text or "").split())[:200]
    if len(text) < 2:
        return False
    character_id = _current_character.get()
    if str(item_id).startswith("ev:"):
        return _evidence.update_extra(item_id, text) if character_id == "kira" else False

    selected = None
    with _lock:
        data = _load()
        for key in ("facts", "moments", "summaries"):
            for it in data[key]:
                current_id = it.get("id") or _id(it.get("kind", "summary"), it["text"])
                if current_id == item_id:
                    selected = (key, it.get("kind", "summary"), it["text"])
                    break
            if selected:
                break
    if selected is None:
        return False

    key, kind, old_text = selected
    new_id = _id(kind, text)
    sync_evidence = key == "facts" and character_id == "kira"
    if sync_evidence and _evidence.enabled():
        # Complete the evidence-index mutation before changing the editable
        # persona item. Storage failures therefore leave the original item intact.
        if not _evidence.update_by_persona_id(item_id, new_id, text):
            raise RuntimeError("Persona-memory edit was not synchronized to evidence memory")

    try:
        with _lock:
            data = _load()
            target = next(
                (
                    entry
                    for group in ("facts", "moments", "summaries")
                    for entry in data[group]
                    if (entry.get("id") or _id(entry.get("kind", "summary"), entry["text"])) == item_id
                ),
                None,
            )
            if target is None:
                raise RuntimeError("Persona-memory item changed while it was being edited")
            target["text"] = text
            target["id"] = new_id
            _save(data)
    except Exception:
        if sync_evidence and _evidence.enabled():
            try:
                _evidence.update_by_persona_id(new_id, item_id, old_text)
            except Exception:
                _log.exception("Could not roll back evidence after persona-memory edit failed")
        raise
    return True


def add_note(text: str, now=None) -> bool:
    text = " ".join(str(text or "").split())[:200]
    if len(text) < 3:
        return False
    label = _LABELS["note"].format(text)
    character_id = _current_character.get()
    persona_id = _id("note", label)
    if character_id == "kira" and _evidence.enabled():
        if not _evidence.add_manual(label, now, persona_id=persona_id):
            raise RuntimeError("Manual note could not be synchronized to evidence memory")
    try:
        add_fact("note", label, now)
    except Exception:
        if character_id == "kira" and _evidence.enabled():
            try:
                _evidence.delete_by_persona_id(persona_id)
            except Exception:
                _log.exception("Could not roll back evidence after adding a persona-memory note failed")
        raise
    return True


# ---------------- summaries of old conversations ----------------
def summarize(chunk: list[dict]) -> str:
    """Compact, extractive summary of old messages (no model call): the most informative distinct lines he wrote + counts of how he felt."""
    from .services import mood_service
    users = []
    for item in chunk:
        if item.get("role") != "user":
            continue
        t = re.split(r"\n\n\[فایل ضمیمه|---\s*فایل ضمیمه", str(item.get("content") or ""))[0]
        t = " ".join(t.split())
        if len(t) >= 12:
            users.append(t)
    picked, seen = [], []
    for t in sorted(users, key=lambda x: -min(len(x), 120)):
        words = set(_norm_part(t).lower().split())
        if any(len(words & w) / max(1, len(words | w)) > 0.5 for w in seen):
            continue
        picked.append(t)
        seen.append(words)
        if len(picked) == 5:
            break
    picked.sort(key=users.index)
    feelings = {}
    for t in users:
        for name in mood_service.detect_user_states(t):
            if name in ("down", "stressed", "frustrated", "excited", "praise", "flirt"):
                feelings[name] = feelings.get(name, 0) + 1
    text = f"{len(users)} of his messages. Things he brought up: " + "; ".join(x[:90] + ("…" if len(x) > 90 else "") for x in picked)
    if feelings:
        text += ". He sounded: " + ", ".join(f"{k} x{v}" for k, v in sorted(feelings.items(), key=lambda kv: -kv[1]))
    return text[:700]


def needs_summary(total: int, window: int) -> bool:
    """Cheap pre-check (no chat-store read): is a summary due for a chat with ``total`` messages?"""
    with _lock:
        done = _load()["summarized"]
    return done > total or (total - int(window) - SUMMARY_KEEP) - done >= SUMMARY_CHUNK


def maintain(rows: list[dict], window: int, now=None) -> bool:
    """Fold messages that aged out of the context window into a summary. rows = the WHOLE chat, oldest first. True if a summary was added."""
    now = time.time() if now is None else now
    eligible = len(rows) - int(window) - SUMMARY_KEEP
    with _lock:
        data = _load()
        if data["summarized"] > len(rows):
            data["summarized"] = 0                                    # the chat store was replaced/restored: start counting again
            data["summaries"] = []
            _save(data)
        if eligible - data["summarized"] < SUMMARY_CHUNK:
            return False
        chunk = rows[data["summarized"]:eligible][:150]
        text = summarize(chunk)
        data["summaries"].append({"kind": "summary", "text": f"(summary written {time.strftime('%Y-%m-%d', time.localtime(now))}) {text}", "ts": int(now),
                                  "count": len(chunk), "id": _id("summary", text)})
        data["summarized"] += len(chunk)
        if len(data["summaries"]) > MAX_SUMMARIES:                    # merge the two oldest instead of dropping history
            a, b = data["summaries"][:2]
            data["summaries"] = [{"kind": "summary", "text": (a["text"] + " | " + b["text"])[:700], "ts": b["ts"], "count": a.get("count", 0) + b.get("count", 0),
                                  "id": _id("summary", a["text"] + b["text"])}] + data["summaries"][2:]
        _save(data)
        return True


# ---------------- layer 3: digest ----------------
def _memory_item_timestamp(item: dict) -> float:
    try:
        value = float(item.get("ts") or item.get("created_at") or 0)
        return value if math.isfinite(value) else 0.0
    except (TypeError, ValueError, OverflowError):
        return 0.0


def _rank_relevant_items(items: list[dict], query: str | None, limit: int) -> list[dict]:
    """Rank character-local saved items using the shared Persian-aware BM25 API."""
    items = [
        item for item in items
        if isinstance(item, dict) and str(item.get("text") or "").strip()
    ]
    if not items or not query or not _evidence.needs_recall(query) or limit <= 0:
        return []
    try:
        indices = _evidence.rank_texts(
            [str(item.get("text") or "") for item in items],
            query,
            min_ratio=_evidence.MIN_BM25_RATIO,
        )
        return [items[index] for index in indices[:max(0, int(limit))] if 0 <= index < len(items)]
    except Exception:  # noqa: BLE001 - recall is optional; the stored memory remains intact
        _log.debug("Persona-memory relevance ranking failed", exc_info=True)
        return []


def _select_persona_facts(facts: list[dict], query: str | None) -> list[dict]:
    """Keep identity facts available, but retrieve all other facts by current-topic relevance."""
    if not query:
        return list(facts[-FACTS_SHOWN:])
    pinned = sorted(
        (item for item in facts if item.get("kind") in ("name", "nick", "pref_len")),
        key=_memory_item_timestamp,
        reverse=True,
    )[:3]
    pinned_objects = {id(item) for item in pinned}
    remaining = [item for item in facts if id(item) not in pinned_objects]
    recalled = _rank_relevant_items(remaining, query, FACTS_SHOWN - len(pinned))
    return pinned + recalled


def _fit_memory_block(header: str, parts: list[str], budget: int) -> str:
    """Fit complete lines and continue to later sections when one section is oversized."""
    try:
        budget = max(0, int(budget))
    except (TypeError, ValueError, OverflowError):
        return ""
    if budget <= 0 or not header or len(header) > budget:
        return ""
    selected = [header]
    used = len(header)
    for part in parts:
        part = str(part or "").strip()
        if not part:
            continue
        separator = 2
        if used + separator + len(part) <= budget:
            selected.append(part)
            used += separator + len(part)
            continue

        lines = part.splitlines()
        if not lines:
            continue
        heading = lines[0]
        if used + separator + len(heading) > budget:
            continue
        fitting = [heading]
        for line in lines[1:]:
            candidate = "\n".join(fitting + [line])
            if used + separator + len(candidate) <= budget:
                fitting.append(line)
        # Never emit a bare section heading without at least one complete item.
        if len(fitting) > 1:
            fragment = "\n".join(fitting)
            selected.append(fragment)
            used += separator + len(fragment)
    return "\n\n".join(selected)


def _compact_digest_line(text: str, max_chars: int = 240, query: str | None = None) -> str:
    text = " ".join(str(text or "").split())
    if len(text) <= max_chars:
        return text

    start = 0
    if query:
        normalized = _evidence.norm(text)
        query_words = [word for word in _evidence.query_terms(query) if len(word) >= 3]
        positions = [normalized.find(word) for word in query_words]
        positions = [position for position in positions if position >= 0]
        if positions:
            # Center the excerpt around the matched subject instead of always
            # keeping the beginning of a long message.
            start = max(0, min(positions) - max_chars // 3)
            start = min(start, max(0, len(text) - max_chars))

    excerpt = text[start:start + max_chars]
    # Prefer a complete sentence; otherwise stop at a word boundary.
    boundary = max(excerpt.rfind(mark) for mark in (". ", "! ", "? ", "؟ ", "。"))
    if boundary >= int(max_chars * 0.55):
        excerpt = excerpt[:boundary + 1]
    else:
        boundary = excerpt.rfind(" ")
        if boundary >= int(max_chars * 0.65):
            excerpt = excerpt[:boundary]
    prefix = "…" if start > 0 else ""
    suffix = "…" if start + len(excerpt) < len(text) else ""
    return prefix + excerpt.rstrip() + suffix


def digest(older: list[dict], query: str | None = None) -> list[str]:
    """Retrieve from full older user messages; compact only after relevance ranking."""
    source_lines = []
    for item in older:
        if not isinstance(item, dict) or item.get("role") != "user":
            continue
        text = " ".join(str(item.get("content") or "").split())
        text = re.sub(r"---\s*فایل ضمیمه.*", "[attached a file]", text)
        if len(text) >= 8:
            # Keep enough source text for topic matching, but cap pathological history rows.
            source_lines.append(text[:2000])
    if query:
        ranked = _rank_relevant_items(
            [{"text": line, "ts": index} for index, line in enumerate(source_lines)],
            query,
            DIGEST_LINES,
        )
        return [_compact_digest_line(item["text"], query=query) for item in ranked]
    return [_compact_digest_line(line) for line in source_lines[-DIGEST_LINES:]]


# ---------------- the block that goes into the system prompt ----------------
HEADER = ("Kira's own memory (real, stored on this computer; it stays the same whichever model is writing the reply). "
          "Use it naturally and sparingly; never recite it or mention that it is a list. It is everything she knows about him: "
          "anything not listed here she does not know, and she must not pretend to.")


HEADER_RELEVANT = ("Kira's own memory (real, stored on this computer; it stays the same whichever model is writing the reply). "
                   "Use it naturally and sparingly; never recite it or mention that it is a list. The facts below are only the ones that fit this "
                   "message; if he asks about something that is not listed, she does not remember it and must say so instead of guessing.")


def build_block(older: list[dict] | None = None, voice_samples: bool = True, now=None, query: str | None = None, budget: int | None = None) -> str:
    """Build a compact memory block ordered by relevance and importance."""
    now = time.time() if now is None else now
    budget = BLOCK_BUDGET if budget is None else int(budget)
    if budget <= 0:
        return ""

    character_id = _current_character.get()
    character_name = character_id.title()
    relevant = None
    if query is not None and character_id == "kira":
        try:
            relevant = _evidence.build_block(query, budget=max(300, int(budget * 0.45)))
        except Exception:  # noqa: BLE001 - evidence recall must never block chat
            _log.debug("Evidence-memory lookup failed; using persona fallback", exc_info=True)
            relevant = None

    with _lock:
        data = _load()

    parts = []
    # An empty ready index is not proof that the editable legacy store has no match.
    if relevant:
        parts.append(relevant)
    else:
        selected_facts = _select_persona_facts(data["facts"], query)
        if selected_facts:
            heading = "What she knows about him:" if character_id == "kira" else f"What {character_name} knows about the user:"
            parts.append(heading + "\n" + "\n".join(f"- {item['text']}" for item in selected_facts))

    moments = [
        item for item in data["moments"]
        if not _expired(item, now) and (voice_samples or item.get("kind") != "joke")
    ]
    moments = (
        _rank_relevant_items(moments, query, MOMENTS_SHOWN)
        if query is not None else moments[-MOMENTS_SHOWN:]
    )
    if moments:
        heading = "Moments and things he told her" if character_id == "kira" else f"Moments {character_name} remembers"
        parts.append(
            heading + " (dated; they may be over by now, so ask rather than assume):\n"
            + "\n".join(f"- {item['text']}" for item in moments)
        )

    summaries = data["summaries"]
    summaries = (
        _rank_relevant_items(summaries, query, SUMMARIES_SHOWN)
        if query is not None else summaries[-SUMMARIES_SHOWN:]
    )
    if summaries:
        parts.append(
            "Older conversations (compressed summaries; may be incomplete):\n"
            + "\n".join(f"- {item['text']}" for item in summaries)
        )

    # Legacy chat rows have no character id; never attribute their digest to another character.
    older_lines = digest(older or [], query=query) if character_id == "kira" else []
    if older_lines:
        heading = "Earlier topics he raised" if character_id == "kira" else f"Earlier topics the user raised with {character_name}"
        parts.append(heading + " (older than the messages below):\n" + "\n".join(f"- {line}" for line in older_lines))

    # Style samples and observational habits have lower priority than facts and events.
    if voice_samples:
        voice = data["voice"][-10:][::-1][::2][:VOICE_SHOWN]
        if voice:
            samples = "\n".join(f"- {value}" for value in reversed(voice))
            voice_name = "Kira" if character_id == "kira" else character_name
            parts.append(
                f"How {voice_name} really sounds (their own recent lines). Match this rhythm, slang, attitude and length in "
                "your reply; do not copy the sentences:\n" + samples
            )

    habits = habit_lines(now)
    if query is not None:
        habits = [
            item["text"] for item in _rank_relevant_items(
                [{"text": line} for line in habits], query, 2
            )
        ]
    if habits:
        heading = "The relationship and his habits:" if character_id == "kira" else "The user's observed habits:"
        parts.append(heading + "\n" + "\n".join(f"- {line}" for line in habits))

    if not parts:
        return ""
    if character_id == "kira":
        header = HEADER if relevant is None else HEADER_RELEVANT
    else:
        header = (
            f"{character_name}'s own memory (real, stored on this computer and isolated from other characters). "
            "Use it naturally and sparingly; never recite it or mention that it is a list. It contains only what this character knows about the user; "
            "anything not listed here is not remembered and must not be guessed."
        )
    return _fit_memory_block(header, parts, budget)
