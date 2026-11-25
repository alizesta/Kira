"""Pure Persian-aware indexing primitives; independent of SQLite and embedding providers."""
from __future__ import annotations
import math
import re
from collections import Counter

BM25_K1, BM25_B = 1.4, 0.75
MIN_BM25_RATIO = 0.35
_CHAR_MAP = str.maketrans({"ي": "ی", "ك": "ک", "ۀ": "ه", "ة": "ه", "أ": "ا", "إ": "ا", "ٱ": "ا", "ؤ": "و", "ئ": "ی"})
_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_MARKS = re.compile("[ً-ٰٟـ‍‎‏]")
_WORD = re.compile(r"\w+", re.U)
_STOP = frozenset("""و در به از که را این آن با برای من تو او ما شما هم یا اما اگر هست است بود می رو ها های یه یک تا بر
the a an is are was were to of and in on for it i you he she my me that this be do does did""".split())
_SMALLTALK = re.compile(
    r"^(?:سلام|درود|هی|های|صبح\s*بخیر|شب\s*بخیر|خوبی|چطوری|چه\s*خبر|ممنون|مرسی|مچکر|باشه|اوکی|آره|اره|نه|خب|خوب|عالی|بای|خداحافظ|"
    r"hi|hello|hey|thanks|thank\s*you|ok|okay|yes|yeah|no|nope|bye|good\s*(?:morning|night)|how\s*are\s*you)[\s.!?؟،,]*$", re.I)
_UNCERTAIN_RX = re.compile(r"شاید|فکر\s*کنم|احتمالا|احتمالاً|مطمئن\s*نیستم|یادم\s*نیست|\bmaybe\b|\bperhaps\b|i\s+think\b|not\s+sure|\bprobably\b", re.I)
_CORRECTION_RX = re.compile(r"^(?:نه|نخیر|اشتباه|در\s*واقع|راستش|ببخشید|درستش|correction|actually|no)\b|اشتباه\s*گفتم|منظورم\s*این\s*بود|\bi\s+meant\b", re.I)
_EXPLICIT_MEANING_RX = re.compile(r"(?P<term>[^\s،,؛.!؟?\n]+(?:\s+[^\s،,؛.!؟?\n]+)?)\s+یعنی\s+(?P<meaning>[^،,؛.!؟?\n]{2,60})")
_MEANING_QUESTION_RX = re.compile(r"^(?:چی|چیه|چیست|چه|چطور|چگونه|what|why|how)\b", re.I)
_MEANING_TERM_STOP = frozenset({
    "من", "تو", "او", "ما", "شما", "اونا", "این", "اون", "آن", "همین", "همون", "که", "پس", "خب", "حالا", "ولی",
    "اگه", "اگر", "وقتی", "یعنی", "هم", "همه", "هیچی", "اینکه", "آیا", "i", "you", "it", "this", "that",
})
_MEANING_TERM_COND = frozenset({"اگه", "اگر", "وقتی", "هر", "تا", "چون", "if", "when", "because"})
_QUERY_SYNONYMS = {
    "امتحان": ("آزمون",), "آزمون": ("امتحان",), "سفر": ("مسافرت",), "مسافرت": ("سفر",),
    "دکتر": ("پزشک",), "پزشک": ("دکتر",), "نگرانی": ("اضطراب",), "اضطراب": ("نگرانی", "استرس"),
    "استرس": ("اضطراب", "نگرانی"), "گرافیک": ("gpu",), "gpu": ("گرافیک",),
}

def is_definition(term: str, meaning: str, tail: str) -> bool:
    words = term.split()
    if not words or any(word.lower() in _MEANING_TERM_STOP for word in words[-1:]) or words[0].lower() in _MEANING_TERM_COND:
        return False
    return not _MEANING_QUESTION_RX.match(meaning) and not tail.lstrip().startswith(("؟", "?"))

def norm(text) -> str:
    value = str(text or "").lower().translate(_CHAR_MAP).translate(_DIGITS).replace("‌", " ")
    return " ".join(_MARKS.sub("", value).split())

def tokens(text) -> list[str]:
    words = [word for word in _WORD.findall(norm(text)) if word not in _STOP and (len(word) >= 2 or word.isdigit())]
    features = list(words)
    for word in words:
        if len(word) >= 4:
            features.extend("#" + word[index:index + 3] for index in range(len(word) - 2))
    return features

def quote_in(quote, source) -> bool:
    normalized = norm(quote)
    return len(normalized) >= 3 and normalized in norm(source)

def needs_recall(text) -> bool:
    value = " ".join(str(text or "").split())
    if not value or _SMALLTALK.match(value):
        return False
    return len([word for word in _WORD.findall(norm(value)) if word not in _STOP]) >= 1 and len(value) >= 4

def query_terms(text) -> list[str]:
    words = [word for word in _WORD.findall(norm(text)) if word not in _STOP and (len(word) >= 2 or word.isdigit())]
    expanded, seen = list(words), set(words)
    for word in words:
        for synonym in _QUERY_SYNONYMS.get(word, ()):
            if synonym not in seen:
                seen.add(synonym)
                expanded.append(synonym)
    return expanded

def query_tokens(text) -> list[str]:
    expanded, seen = [], set()
    for term in query_terms(text):
        for feature in tokens(term):
            if feature not in seen:
                seen.add(feature)
                expanded.append(feature)
    return expanded

def bm25(docs: dict[str, list[str]], query: list[str]) -> dict[str, float]:
    count = len(docs)
    if not count or not query:
        return {}
    average_length = sum(len(values) for values in docs.values()) / count or 1.0
    document_frequency = Counter()
    for values in docs.values():
        document_frequency.update(set(values))
    scores = {}
    for fact_id, values in docs.items():
        term_frequency, length, score = Counter(values), len(values), 0.0
        for term in set(query):
            frequency = term_frequency.get(term)
            if frequency:
                inverse_frequency = math.log(1 + (count - document_frequency[term] + 0.5) / (document_frequency[term] + 0.5))
                score += inverse_frequency * frequency * (BM25_K1 + 1) / (
                    frequency + BM25_K1 * (1 - BM25_B + BM25_B * length / average_length)
                )
        if score > 0:
            scores[fact_id] = score
    return scores

def rank_texts(texts, query, min_ratio=MIN_BM25_RATIO):
    """Return indices ranked by Persian-aware BM25 relevance to one query."""
    if not needs_recall(query):
        return []
    features = query_tokens(query)
    if not features:
        return []
    docs = {str(index): tokens(text) for index, text in enumerate(texts or [])}
    if not docs:
        return []
    scores = bm25(docs, features)
    if not scores:
        return []
    best = max(scores.values())
    threshold = best * max(0.0, min(1.0, float(min_ratio)))
    return sorted((int(index) for index, score in scores.items() if score >= threshold),
                  key=lambda index: (-scores[str(index)], index))

class EvidenceIndexer:
    """Owns disposable document-token cache; source facts are never stored in this cache."""
    def __init__(self, cache=None):
        self.cache = cache if cache is not None else {}

    def document_tokens(self, row, evidence_quote="") -> list[str]:
        fact_id = row["id"]
        cached = self.cache.get(fact_id)
        updated_at = row["updated_at"]
        if cached and cached[0] == updated_at:
            return cached[1]
        features = tokens(f"{row['text']} {row['value']} {evidence_quote}")
        self.cache[fact_id] = (updated_at, features)
        return features

    def invalidate(self, fact_id) -> None:
        self.cache.pop(str(fact_id), None)

    def clear(self) -> None:
        self.cache.clear()
