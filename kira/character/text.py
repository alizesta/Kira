"""Shared normalization for deterministic Persian/Arabic text detection."""
from __future__ import annotations
import re
import unicodedata
_DIACRITICS = re.compile(r"[\u064B-\u065F\u0670\u0640]")
def normalize_detection_text(value) -> str:
    """Normalize orthographic variants and spacing without altering source messages."""
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = (text.replace("\u200c", " ").replace("\u200d", "")
            .replace("ي", "ی").replace("ى", "ی").replace("ك", "ک").replace("ۀ", "ه"))
    text = _DIACRITICS.sub("", text).casefold()
    return " ".join(text.split())
