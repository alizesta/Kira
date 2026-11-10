"""Conservative, explicit feedback detection for Kira's long-term personality learning.

Only direct user feedback about Kira's style is considered. Ordinary sentiment,
praise of unrelated things, and ambiguous wording are ignored.
"""
from __future__ import annotations

import re


_RULES = (
    ("disliked_teasing", (
        r"شوخی\s*نکن", r"این\s*شوخی\s*(?:رو|را)\s*دوست\s*ندارم",
        r"زیادی\s*شوخی", r"مسخره\s*نکن", r"کل\s*کل\s*نکن",
        r"stop\s+joking", r"don't\s+joke",
    )),
    ("liked_teasing", (
        r"این\s*شوخی\s*(?:خیلی\s*)?(?:خوب|باحال)", r"خوب\s*کل\s*کل\s*کردی",
        r"همین\s*طوری\s*باش", r"همینطوری\s*باش",
        r"(?:این|همین)\s*لحن(?:\s+\S{1,12})?\s*(?:رو|را)?\s*دوست\s*دارم",
        r"good\s+joke", r"keep\s+that\s+playful\s+tone",
    )),
    ("liked_support", (
        r"خوب\s*درکم\s*کردی", r"ممنون\s*که\s*گوش\s*دادی",
        r"خوب\s*حمایتم\s*کردی", r"کمکم\s*کردی\s*و\s*درکم",
        r"that\s+helped", r"thanks\s+for\s+understanding",
    )),
    ("disliked_formality", (
        r"زیادی\s*رسمی", r"اینقدر\s*رسمی\s*نباش", r"خشک\s*جواب\s*نده",
        r"مثل\s*ربات\s*جواب\s*نده", r"too\s+formal", r"don't\s+sound\s+so\s+formal",
    )),
    ("liked_curiosity", (
        r"سوال(?:ت|هات)\s*(?:خوب|جالب)", r"خوب\s*پرسیدی",
        r"خوشم\s*میاد\s*سوال\s*میپرسی", r"good\s+question",
    )),
    ("accuracy_correction", (
        r"اشتباه\s*گفتی", r"این\s*(?:جواب|اطلاعات)\s*غلطه",
        r"دوباره\s*اشتباه", r"اطلاعاتت\s*درست\s*نیست",
        r"that's\s+incorrect", r"you\s+got\s+that\s+wrong",
    )),
)


def _normalize(text):
    return str(text or "").replace("ي", "ی").replace("ك", "ک").replace("\u200c", " ").lower()


def detect_feedback(text):
    """Return zero or one conservative feedback category for a single user message."""
    value = _normalize(text)
    for category, patterns in _RULES:
        if any(re.search(pattern, value, re.I) for pattern in patterns):
            return category
    return None
