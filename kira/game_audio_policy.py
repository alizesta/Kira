"""Pure text policy for detecting high-signal game-audio transcripts."""
from __future__ import annotations

import re


IMPORTANT_GAME_AUDIO = re.compile(
    r"\b(low\s+health|critical\s+health|health\s+low|low\s+hp|"
    r"mission\s+complete|quest\s+complete|objective\s+complete|"
    r"mission\s+failed|objective\s+failed|achievement\s+unlocked|"
    r"victory|you\s+win|you\s+have\s+been\s+defeated|game\s+over|"
    r"boss\s+(?:fight|battle|incoming)|incoming\s+(?:enemy|attack)|"
    r"warning|danger|critical\s+damage|enemy\s+spotted)\b|"
    r"سلامتی.{0,12}(?:کم|پایین)|خونت\s+کم|جونت\s+کم|"
    r"مرحله\s+(?:تموم|تمام)|ماموریت\s+(?:تموم|تمام|شکست)|"
    r"هدف\s+(?:انجام|تکمیل)|موفق\s+شد[یی]|شکست\s+خورد[یی]|"
    r"دشمن\s+(?:نزدیک|پیدا)|حمله\s+(?:شد|در\s+راه)|"
    r"خطر|هشدار|باس\s+(?:اومد|آمد)|دستاورد",
    re.I,
)


def is_important_game_audio(text: str) -> bool:
    """Conservative local keyword filter; ordinary dialogue stays silent."""
    return bool(IMPORTANT_GAME_AUDIO.search(str(text or "").strip()))
