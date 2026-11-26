"""Reads the emotion metadata the model writes and separates it from the visible reply.

Preferred (structured) format, on its own line before the reply:   [smug:70]   [shy+affectionate:55]
Also accepted: [smug 70] [smug|70] [emotion=smug, intensity=70] [smug] and the old mood tags [happy].
Only if the model wrote no usable tag does a weak keyword fallback look at the text.
"""
import re

from .. import body as _body

# [user:down] - the model's reading of the USER's state (optional second line); removed from the visible text everywhere.
USER_STATE_TAGS = ("down", "stressed", "hostile", "frustrated", "praise", "flirt", "thanks", "excited", "joke", "apology",
                   "goodbye", "jealous")
_USER_TAG = re.compile(r"\[\s*user\s*[:=]\s*([A-Za-z_+&/, ]{1,60}?)\s*\]", re.I)
_USER_OPEN = re.compile(r"\[\s*u(?:s(?:e(?:r)?)?)?\s*(?:[:=][^\[\]\n]{0,60})?$", re.I)        # "[us" / "[user:do" still being typed


def extract_user_states(raw):
    """(text without user tags, [valid states in order, no repeats]). Pure: safe on every streamed chunk."""
    text = str(raw or "")
    states = []
    for m in _USER_TAG.finditer(text):
        for part in re.split(r"\s*[+&/,]\s*", m.group(1).strip().lower()):
            if part in USER_STATE_TAGS and part not in states:
                states.append(part)
    text = _USER_TAG.sub("", text)
    tail = _USER_OPEN.search(text)
    if tail:
        text = text[:tail.start()]
    return text, states[:2]


_TOKEN = re.compile(r"\[([^\[\]\n]{1,60})\]")
_SPLIT = re.compile(r"\s*[+&/,]\s*|\s+and\s+", re.I)
_JUNK_FIRST_LINE = re.compile(r"^\s*\[[A-Za-z_+&/:|=, 0-9%.-]{1,50}\]\s*$")
_BARE_MOOD = re.compile(r"(?im)^\s*(neutral|happy|excited|sad|bored|angry|shy|surprised|thinking|sleepy)\s*[.!,:;]?\s*$")
# U+60C5 U+7EEA is the Chinese word for "emotion"; U+FF1A is the fullwidth colon. Both are matched on purpose because some models answer in Chinese.
_MOOD_LINE = re.compile(r"(?im)^\s*(?:mood|emotion|\u60c5\u7eea|حالت)\s*[:\uff1a=].*$")


class ReplyMeta:
    """Visible text plus the emotion metadata detected for it."""
    __slots__ = ("text", "emotions", "intensity", "source", "body", "user_states")

    def __init__(self, text, emotions=(), intensity=None, source="none", body=(), user_states=()):
        self.text, self.emotions, self.intensity, self.source = text, list(emotions), intensity, source
        self.user_states = list(user_states)                    # states the model read from the user's message ([user:...] tag)
        self.body = list(body)                                 # body commands the model wrote as [body:...] tags (kira/body.py)

    def __repr__(self):
        return f"ReplyMeta({self.emotions}, {self.intensity}, {self.source!r}, text={self.text[:30]!r})"


def parse_token(content, library):
    """('ids', intensity) for tag content like 'smug:70' or 'shy+affectionate', else None."""
    s = str(content).strip().lower()
    s = re.sub(r"^emotion\s*[:=]\s*", "", s)
    intensity = None
    m = re.search(r"(?:[:|,=\s]\s*(?:intensity\s*[:=]?\s*)?)(\d{1,3})\s*%?\s*$", s)
    if m:
        intensity = max(0, min(100, int(m.group(1))))
        s = s[:m.start()]
    s = re.sub(r"[,\s]*intensity\s*[:=]?\s*$", "", s).strip(" :|,=-")
    if not s:
        return None
    ids = []
    for part in _SPLIT.split(s):
        eid = library.resolve_name(part)
        if eid is None:
            return None
        if eid not in ids:
            ids.append(eid)
    return (ids, intensity) if ids else None


def parse_reply(reply, library, rules=None):
    raw = re.sub(r"<think>.*?(</think>|$)", "", str(reply or ""), flags=re.S)
    raw, user_states = extract_user_states(raw)
    raw, body_cmds = _body.extract(raw)                      # [body:raise_right_hand] tags: removed from the text, returned separately
    found, strip_spans = None, []
    for m in _TOKEN.finditer(raw):
        parsed = parse_token(m.group(1), library)
        if parsed:
            strip_spans.append(m.span())
            if found is None:
                found = parsed
    text = raw
    for a, b in reversed(strip_spans):
        text = text[:a] + text[b:]
    first = text.lstrip().split("\n", 1)[0] if text.strip() else ""
    if _JUNK_FIRST_LINE.match(first):                       # an unknown tag-looking first line is not part of the reply
        text = text.lstrip().split("\n", 1)[1] if "\n" in text.lstrip() else ""
    legacy = _BARE_MOOD.findall(text)
    if found is None and legacy:
        eid = library.resolve_name(legacy[0])
        found = ([eid], None) if eid else None
    text = _BARE_MOOD.sub("", text)
    text = _MOOD_LINE.sub("", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip(" \t\r\n-:")
    if found:
        return ReplyMeta(text, found[0], found[1], "tag", body_cmds, user_states)
    guess = detect_from_text(text, library, rules)
    if guess:
        return ReplyMeta(text, [guess[0]], guess[1], "keywords", body_cmds, user_states)
    return ReplyMeta(text, [], None, "none", body_cmds, user_states)


def detect_from_text(text, library, rules=None):
    """Weak fallback: keyword hits from the library. Returns (emotion_id, intensity) or None."""
    cfg = (rules or library.rules).get("keyword_intensity", {})
    low = str(text or "").lower()
    best, best_hits = None, 0
    for emo in library.emotions.values():
        if emo.id == "neutral":
            continue
        hits = sum(1 for k in emo.keywords if k and k in low)
        if hits > best_hits or (hits == best_hits and hits and best and emo.priority > best.priority):
            best, best_hits = emo, hits
    if best is None or best_hits < int(cfg.get("min_hits", 1)):
        return None
    level = min(int(cfg.get("max", 55)), int(cfg.get("base", 30)) + int(cfg.get("per_hit", 8)) * (best_hits - 1))
    return best.id, level
