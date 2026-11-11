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
from contextlib import contextmanager
from contextvars import ContextVar
import os
import re
import threading
import time

from . import evidence_memory as _evidence      # facts with provenance + relevance-based recall (this module stays the owner of the editable list)
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


_TAG = re.compile(r"^\s*\[[^\]\n]{1,30}\]\s*")
_BAD_VOICE = ("http://", "https://", "```", "[نتایج", "language model", "as an ai", "مدل زبانی", "به عنوان یک هوش", "how can i help", "چطور می‌توانم کمک")


def _path():
    character_id = _current_character.get()
    return DATA_DIR / (FILE_NAME if character_id == "kira" else f"kira_persona_memory_{character_id}.json")


def _empty() -> dict:
    return {"voice": [], "facts": [], "moments": [], "summaries": [], "habits": {"hours": [0] * 24, "messages": 0, "chars": 0, "first_seen": 0, "days": []}, "summarized": 0}


def _load() -> dict:
    data = _empty()
    try:
        raw = json.loads(_path().read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            data["voice"] = [str(x) for x in raw.get("voice", []) if isinstance(x, str)]
            for key in ("facts", "moments", "summaries"):
                data[key] = [f for f in raw.get(key, []) if isinstance(f, dict) and f.get("text")]
            h = raw.get("habits")
            if isinstance(h, dict) and isinstance(h.get("hours"), list) and len(h["hours"]) == 24:
                data["habits"] = {"hours": [int(x) for x in h["hours"]], "messages": int(h.get("messages") or 0), "chars": int(h.get("chars") or 0),
                                  "first_seen": float(h.get("first_seen") or 0), "days": [str(d) for d in h.get("days", [])][-400:]}
            data["summarized"] = int(raw.get("summarized") or 0)
    except (OSError, ValueError, TypeError):
        pass
    return data


def _save(data: dict):
    path = _path()
    tmp = path.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        pass                                                      # memory is a bonus; never break the chat


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
        flags = {"uncertain": bool(_evidence._UNCERTAIN_RX.search(_evidence.norm(part))), "correction": bool(_evidence._CORRECTION_RX.search(_evidence.norm(part)))}
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
        pass


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
    """Everything Kira stored about him and the relationship (not the chat history itself)."""
    _last_reply[_current_character.get()] = ""
    with _lock:
        _save(_empty())
    if _current_character.get() == "kira":
        _evidence.forget_all()


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
    removed = _delete_persona_item(item_id)
    if _current_character.get() == "kira":
        _evidence.delete_by_persona_id(item_id)                          # the evidence of what he deleted goes too
    return removed


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
    if str(item_id).startswith("ev:"):
        return (_evidence.delete_extra(item_id) and _evidence.add_manual(text)) if _current_character.get() == "kira" else False
    sync = None
    with _lock:
        data = _load()
        for key in ("facts", "moments", "summaries"):
            for it in data[key]:
                if (it.get("id") or _id(it.get("kind", "summary"), it["text"])) == item_id:
                    it["text"] = text
                    new_id = _id(it.get("kind", "summary"), text)
                    it["id"] = new_id
                    _save(data)
                    sync = (key, new_id)
                    break
            if sync:
                break
    if sync is None:
        return False
    if sync[0] == "facts" and _current_character.get() == "kira":      # outside the lock: the two stores never wait for each other
        _evidence.update_by_persona_id(item_id, sync[1], text)          # his own wording replaces the stored fact
    return True


def add_note(text: str, now=None) -> bool:
    text = " ".join(str(text or "").split())[:200]
    if len(text) < 3:
        return False
    label = _LABELS["note"].format(text)
    add_fact("note", label, now)
    if _current_character.get() == "kira":
        _evidence.add_manual(label, now, persona_id=_id("note", label))
    return True


# ---------------- summaries of old conversations ----------------
def summarize(chunk: list[dict]) -> str:
    """Compact, extractive summary of old messages (no model call): the most informative distinct lines he wrote + counts of how he felt."""
    from . import mood
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
        for name in mood.detect_user_states(t):
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
def digest(older: list[dict]) -> list[str]:
    """Short lines describing what the user brought up in messages older than the verbatim window."""
    lines = []
    for item in older:
        if item.get("role") != "user":
            continue
        text = " ".join(str(item.get("content") or "").split())
        text = re.sub(r"---\s*فایل ضمیمه.*", "[attached a file]", text)
        if len(text) >= 8:
            lines.append(text[:100] + ("…" if len(text) > 100 else ""))
    return lines[-DIGEST_LINES:]


# ---------------- the block that goes into the system prompt ----------------
HEADER = ("Kira's own memory (real, stored on this computer; it stays the same whichever model is writing the reply). "
          "Use it naturally and sparingly; never recite it or mention that it is a list. It is everything she knows about him: "
          "anything not listed here she does not know, and she must not pretend to.")


HEADER_RELEVANT = ("Kira's own memory (real, stored on this computer; it stays the same whichever model is writing the reply). "
                   "Use it naturally and sparingly; never recite it or mention that it is a list. The facts below are only the ones that fit this "
                   "message; if he asks about something that is not listed, she does not remember it and must say so instead of guessing.")


def build_block(older: list[dict] | None = None, voice_samples: bool = True, now=None, query: str | None = None, budget: int | None = None) -> str:
    """``query`` = the user's current message: with it, facts are chosen by relevance (evidence memory); without it (or when the evidence
    layer is unavailable) the older "last facts" list is used exactly as before. ``budget`` = characters this block may use."""
    now = time.time() if now is None else now
    budget = int(budget or BLOCK_BUDGET)
    relevant = None
    if query is not None and _current_character.get() == "kira":
        try:
            relevant = _evidence.build_block(query, budget=max(300, int(budget * 0.45)))
        except Exception:                                              # noqa: BLE001 - never let the index break the prompt
            relevant = None
    with _lock:
        data = _load()
    parts = []
    voice = data["voice"][-10:][::-1][::2][:VOICE_SHOWN]
    if voice and voice_samples:                  # her own recent banter is a style anchor: left out when the turn is a practical request
        samples = "\n".join(f"- {v}" for v in reversed(voice))
        voice_name = "Kira" if _current_character.get() == "kira" else _current_character.get().title()
        parts.append(f"How {voice_name} really sounds (her own recent lines). Match this rhythm, slang, attitude and length in "
                     "your reply; do not copy the sentences:\n" + samples)
    character_id = _current_character.get()
    character_name = character_id.title()
    if relevant is None:
        fact_lines = [f["text"] for f in data["facts"]]
        notes = [t for t in fact_lines if t.startswith("He asked her")]
        rest = [t for t in fact_lines if not t.startswith("He asked her")]
        shown = (rest[-(FACTS_SHOWN - min(len(notes), 6)):] + notes[-6:])
        if shown:
            heading = "What she knows about him:" if character_id == "kira" else f"What {character_name} knows about the user:"
            parts.append(heading + "\n" + "\n".join(f"- {t}" for t in shown))
    elif relevant:
        parts.append(relevant)
    rel = habit_lines(now)
    if rel:
        parts.append(("The relationship and his habits:\n" if character_id == "kira" else "The user's observed habits:\n")
                     + "\n".join(f"- {t}" for t in rel))
    moments = [m for m in data["moments"] if not _expired(m, now) and (voice_samples or m.get("kind") != "joke")]
    if moments:
        heading = ("Moments and things he told her" if character_id == "kira" else f"Moments {character_name} remembers")
        parts.append(heading + " (dated; they may be over by now, so ask rather than assume):\n"
                     + "\n".join(f"- {m['text']}" for m in moments[-MOMENTS_SHOWN:]))
    if data["summaries"]:
        parts.append("Older conversations (compressed summaries; may be incomplete):\n"
                     + "\n".join(f"- {m['text']}" for m in data["summaries"][-SUMMARIES_SHOWN:]))
    older_lines = digest(older or [])
    if older_lines:
        heading = "Earlier topics he raised" if character_id == "kira" else f"Earlier topics the user raised with {character_name}"
        parts.append(heading + " (older than the messages below):\n" + "\n".join(f"- {t}" for t in older_lines))
    if not parts:
        return ""
    if character_id == "kira":
        header = HEADER if relevant is None else HEADER_RELEVANT
    else:
        header = (f"{character_name}'s own memory (real, stored on this computer and isolated from other characters). "
                  "Use it naturally and sparingly; never recite it or mention that it is a list. It contains only what this character knows about the user; "
                  "anything not listed here is not remembered and must not be guessed.")
    block = header + "\n\n" + "\n\n".join(parts)
    return block[:budget]
