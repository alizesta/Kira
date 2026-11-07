"""Text side of speech recognition (pure functions, no Qt / numpy).

- normalize_fa: tidy what Whisper / Google return for spoken (colloquial) Persian.
- is_hallucination: phrases Whisper invents on noise or silence ("Thanks for watching", Persian subtitle credits...).
- grace_for / merge_text: how long to wait after a sentence before treating the speech as finished, and joining
  the pieces when the person only paused to think.
- initial_prompt: a short colloquial sample that nudges Whisper towards how people really talk.
"""
from __future__ import annotations

import re

ZWNJ = "\u200c"
_CHAR_FIX = str.maketrans({"ي": "ی", "ى": "ی", "ك": "ک", "ة": "ه", "\u0640": "", "\u200f": "", "\u200e": ""})
_DIACRITICS = re.compile("[\u064B-\u065F\u0670]")
_MI_PREFIX = re.compile(r"(?<![\w\u200c])(ن?می)[ \u00a0]+(?=[\u0600-\u06FF])")      # "می خوام" -> "می‌خوام", "نمی دونم" -> "نمی‌دونم"
_REPEAT_PUNCT = re.compile(r"([.!؟?،,])\1{2,}")

HALLUCINATIONS = re.compile(
    r"زیرنویس|ترجمه\s*(?:و|ی)?\s*زیرنویس|امارا|amara\.org|subtitles?\s+by|thanks?\s+for\s+watching|thank\s+you\s+for\s+watching|"
    r"please\s+subscribe|like\s+and\s+subscribe|www\.|\.com\b|در\s+ویدیو\s+بعدی|ویدئو\s+بعدی|لطفا?\s+مشترک|مشترک\s+شوید|"
    r"♪|\[music\]|\[موسیقی\]", re.I)

CONNECTORS = {"و", "که", "اما", "ولی", "چون", "یعنی", "تا", "با", "برای", "از", "به", "در", "اگه", "اگر", "یا", "پس", "بعدش", "بعد",
              "اینکه", "آخه", "خب", "ببین", "مثلا", "مثلاً", "هم", "این", "اون", "یه", "یک", "and", "but", "so", "because", "to", "the",
              "a", "of", "or", "if", "then"}

SENTENCE_END = ".!?؟…"
SOFT_END = ",،؛:;"


def normalize_fa(text: str) -> str:
    """Arabic letter variants -> Persian, remove diacritics/tatweel, 'می خوام' -> 'می‌خوام', collapse spaces and repeated marks."""
    text = str(text or "").translate(_CHAR_FIX)
    text = _DIACRITICS.sub("", text)
    text = _MI_PREFIX.sub(lambda m: m.group(1) + ZWNJ, text)
    text = _REPEAT_PUNCT.sub(r"\1", text)
    return re.sub(r"\s+", " ", text).strip()


def is_hallucination(text: str) -> bool:
    """True for text that is almost certainly not something the person said (noise/silence artefacts)."""
    t = str(text or "").strip()
    if not t:
        return True
    if not re.search(r"\w", t):
        return True                                            # only punctuation / symbols
    if len(t) <= 90 and HALLUCINATIONS.search(t):
        return True
    words = re.findall(r"\w+", t.lower())
    if len(words) >= 4 and len(set(words)) == 1:
        return True                                            # "بله بله بله بله": a looping decoder, not speech
    return False


def grace_for(text: str) -> float:
    """Seconds to wait for more speech after this text before handing it to Kira.

    A finished sentence is handed over quickly; a trailing comma, a connecting word ("و", "که", "ولی"...) or a very short
    fragment means the person is probably still thinking, so wait longer."""
    t = str(text or "").strip()
    if not t:
        return 0.0
    words = t.split()
    last = t[-1]
    tail = words[-1].strip(SENTENCE_END + SOFT_END + "'\"").lower() if words else ""
    if last in SENTENCE_END:
        grace = 0.45
    elif last in SOFT_END:
        grace = 1.3
    else:
        grace = 0.85                                           # Whisper often omits the final full stop
    if tail in CONNECTORS:
        grace = max(grace, 1.5)
    if len(words) <= 2 and last not in SENTENCE_END:
        grace = max(grace, 1.0)
    return grace


def merge_text(first: str, second: str) -> str:
    first, second = str(first or "").strip(), str(second or "").strip()
    return f"{first} {second}".strip() if first and second else (first or second)


def clean_transcript(text: str, language=None, fixes=None) -> str:
    """Final text for the chat: normalised, the user's word fixes applied, and empty when it is just a recognizer artefact."""
    text = normalize_fa(text) if language in (None, "fa") else re.sub(r"\s+", " ", str(text or "")).strip()
    if fixes is not None:
        text = fixes.apply(text)
    return "" if is_hallucination(text) else text


def initial_prompt(language, hotwords: str = "") -> str:
    """Whisper `initial_prompt`: wake word first, then a few colloquial lines so it spells spoken Persian the way people say it.
    `hotwords` (from the user's dictionary) are appended so those words are expected."""
    wake = "کیرا، سلام کیرا، Kira."
    if language == "fa":
        base = wake + " چطوری؟ می‌خوام یه چیزی ازت بپرسم. نمی‌دونم چیکار کنم، یه کم کمکم می‌کنی؟ آره، اینو بگو ببینم چی میشه."
    elif language in (None, ""):
        base = wake + " Hey Kira. می‌خوام یه چیزی بپرسم، نمی‌دونم."
    else:
        base = "Kira, hey Kira."
    return f"{base} {hotwords}".strip() if hotwords else base
