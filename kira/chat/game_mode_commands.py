"""Deterministic parsing for explicit Game Mode chat controls."""
from __future__ import annotations

import re
import unicodedata


_MODE_REFERENCE = re.compile(r"(?:game\s*mode|گیم\s*مود)", re.I)
_ENABLE = re.compile(
    r"(?:روشن|فعال)\s*(?:کن|بکن|کنید|بکنید)|"
    r"\b(?:turn\s+on|enable)\s+(?:the\s+)?game\s*mode\b|"
    r"\bgame\s*mode\s+on\b",
    re.I,
)
_DISABLE = re.compile(
    r"(?:خاموش|غیرفعال)\s*(?:کن|بکن|کنید|بکنید)|"
    r"\b(?:turn\s+off|disable)\s+(?:the\s+)?game\s*mode\b|"
    r"\bgame\s*mode\s+off\b",
    re.I,
)
_STATUS = re.compile(
    r"(?:وضعیت|روشنه|خاموشه|فعاله|غیرفعاله|روشن\s+است|فعال\s+است|"
    r"کار\s+می\s+کنه|is\s+game\s*mode\s+(?:on|enabled)|"
    r"game\s*mode\s+status)",
    re.I,
)


def _normalize(text: str) -> str:
    value = unicodedata.normalize("NFKC", str(text or "")).casefold()
    value = value.replace("ي", "ی").replace("ك", "ک").replace("\u200c", " ")
    value = re.sub(r"[\u064b-\u065f\u0670]", "", value)
    return re.sub(r"\s+", " ", value).strip()


def parse_game_mode_command(text: str) -> str | None:
    """Return enable/disable/status only for clear Game Mode control requests."""
    value = _normalize(text)
    if not _MODE_REFERENCE.search(value):
        return None
    # Status questions must win over words such as "game mode on".
    if _STATUS.search(value):
        return "status"
    if _DISABLE.search(value):
        return "disable"
    if _ENABLE.search(value):
        return "enable"
    return None
