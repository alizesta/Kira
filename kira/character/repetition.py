"""Local, zero-latency repetition guard (pure Python, no model call, no Qt).

Models told "don't repeat yourself" in the system prompt still reuse openers and catchphrases. This keeps the last few replies per
character in memory and, before the next request, names the openers and phrases that are already worn out so the prompt can say
exactly what to avoid. Cost: a few string operations on <= 6 short texts.
"""
from __future__ import annotations

import re
import threading
from collections import Counter, deque

KEEP = 6
_WORD = re.compile(r"[\w؀-ۿ]+", re.UNICODE)
_recent: dict[str, deque] = {}
_lock = threading.Lock()


def _words(text: str) -> list[str]:
    return [w.casefold() for w in _WORD.findall(str(text or ""))]


def too_similar(a: str, b: str, threshold: float = 0.7) -> bool:
    """Word-set overlap (Jaccard) of two short texts; used to drop near-duplicate spontaneous remarks."""
    wa, wb = set(_words(a)), set(_words(b))
    if len(wa) < 3 or len(wb) < 3:
        return " ".join(_words(a)) == " ".join(_words(b)) and bool(wa)
    return len(wa & wb) / len(wa | wb) >= threshold


def record(character_id: str, text: str) -> None:
    if len(_words(text)) < 2:
        return
    with _lock:
        _recent.setdefault(str(character_id or "kira"), deque(maxlen=KEEP)).append(str(text))


def reset(character_id: str | None = None) -> None:
    with _lock:
        if character_id is None:
            _recent.clear()
        else:
            _recent.pop(str(character_id), None)


def note(character_id: str, *, max_chars: int = 320) -> str:
    """Prompt text naming recently overused openers/phrases and near-duplicate replies; '' when there is nothing to say."""
    with _lock:
        replies = list(_recent.get(str(character_id or "kira"), ()))
    if len(replies) < 2:
        return ""
    tokens = [_words(r) for r in replies]
    parts: list[str] = []
    openers = Counter(" ".join(t[:2]) for t in tokens[-5:] if len(t) >= 2)
    worn = [o for o, n in openers.most_common(3) if n >= 2]
    if worn:
        parts.append("openers already used recently: " + ", ".join(f"«{o}»" for o in worn))
    grams: Counter = Counter()
    for t in tokens[-5:]:
        grams.update({" ".join(t[i:i + 3]) for i in range(len(t) - 2)})
    phrases = [g for g, n in grams.most_common(12) if n >= 2 and g.split()[0] not in {x.split()[0] for x in worn}][:3]
    if phrases:
        parts.append("phrases repeated across recent replies: " + ", ".join(f"«{p}»" for p in phrases))
    similar = len(replies) >= 2 and too_similar(replies[-1], replies[-2])
    if not parts and not similar:
        return ""
    text = "Repetition guard (local check): " + "; ".join(parts) + ("; the last two replies were almost identical in wording" if similar else "")
    return (text + ". Say it differently this time: new opening, new phrasing.")[:max_chars]
