"""Reads the emotion metadata the model writes and separates it from the visible reply.

Preferred (structured) format, on its own line before the reply:   [smug:70]   [shy+affectionate:55]
Also accepted: [smug 70] [smug|70] [emotion=smug, intensity=70] [smug] and the old mood tags [happy].
Only if the model wrote no usable tag does a weak keyword fallback look at the text.
"""
import re

_TOKEN = re.compile(r"\[([^\[\]\n]{1,60})\]")
_SPLIT = re.compile(r"\s*[+&/,]\s*|\s+and\s+", re.I)
_JUNK_FIRST_LINE = re.compile(r"^\s*\[[A-Za-z_+&/:|=, 0-9%.-]{1,50}\]\s*$")
_BARE_MOOD = re.compile(r"(?im)^\s*(neutral|happy|excited|sad|bored|angry|shy|surprised|thinking|sleepy)\s*[.!,:;]?\s*$")
# U+60C5 U+7EEA is the Chinese word for "emotion"; U+FF1A is the fullwidth colon. Both are matched on purpose because some models answer in Chinese.
_MOOD_LINE = re.compile(r"(?im)^\s*(?:mood|emotion|\u60c5\u7eea|حالت)\s*[:\uff1a=].*$")


class ReplyMeta:
    """Visible text plus the emotion metadata detected for it."""
    __slots__ = ("text", "emotions", "intensity", "source")

    def __init__(self, text, emotions=(), intensity=None, source="none"):
        self.text, self.emotions, self.intensity, self.source = text, list(emotions), intensity, source

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
        return ReplyMeta(text, found[0], found[1], "tag")
    guess = detect_from_text(text, library, rules)
    if guess:
        return ReplyMeta(text, [guess[0]], guess[1], "keywords")
    return ReplyMeta(text, [], None, "none")


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
