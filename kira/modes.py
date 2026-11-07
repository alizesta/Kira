"""Active Mode: what kind of turn is this? (the third layer next to Core Instructions and Personality)

  CHAT   casual talk: full personality.
  TASK   the user wants something done, solved or explained (help in a game, an error, a question, "do this for me"):
         the answer comes first, personality shrinks to a few words of flavour.
  STRICT "just answer, no jokes": plain, direct, no banter, until he asks for banter again.

The decision is deterministic (word patterns, Persian + English) and made per message, so it works the same for every model.
It never removes or edits Kira's persona: it only adds a short block at the END of the system prompt (where models weigh it most)
that says which situation this turn is. When in doubt between CHAT and TASK the answer is TASK: an answer with a little less
banter costs less than banter instead of an answer."""
from __future__ import annotations

import re
from dataclasses import dataclass

CHAT, TASK, STRICT = "chat", "task", "strict"
STICKY_TURNS = 3                                           # a "no jokes" request / a game session keeps holding for the next messages


@dataclass(frozen=True)
class Mode:
    name: str
    game: bool = False
    why: str = ""


def _norm(text: str) -> str:
    text = str(text or "").lower()
    text = text.replace("ي", "ی").replace("ك", "ک").replace("\u200c", " ").replace("\u200f", " ")
    return re.sub(r"\s+", " ", text).strip()


def _rx(*words):
    return re.compile("|".join(words), re.I)


STRICT_RX = _rx(r"شوخی\s*نکن", r"بدون\s*شوخی", r"شوخی\s*بی\s*شوخی", r"جدی\s*(?:جواب|باش|بگو|بحث)", r"فقط\s*(?:جواب|همین|بگو|درست)",
                r"بی\s*حاشیه", r"بدون\s*حاشیه", r"حاشیه\s*نرو", r"no\s*jok", r"don'?t\s*joke", r"just\s*answer", r"answer\s*(?:me\s*)?(?:only|directly|seriously)",
                r"straight\s*answer", r"be\s*serious")
CHAT_RX = _rx(r"گپ\s*(?:بزنیم|بزن|می\s*زنیم)", r"بیا\s*(?:یکم|یه\s*کم|یه\s*خرده)?\s*(?:حرف|صحبت|گپ|چت)", r"حرف\s*بزنیم", r"صحبت\s*کنیم",
              r"شوخی\s*کن", r"حالت\s*(?:عادی|قبلی)", r"برگرد", r"حوصله\s*ام\s*سر", r"بی\s*حوصله", r"دلم\s*(?:برات|تنگ)", r"let'?s\s*(?:chat|talk)", r"just\s*chat",
              r"back\s*to\s*normal")
EXIT_STRICT_RX = _rx(r"شوخی\s*کن", r"گپ\s*(?:بزنیم|بزن|می\s*زنیم)", r"حرف\s*بزنیم", r"صحبت\s*کنیم", r"بیا\s*(?:یکم|یه\s*کم|یه\s*خرده)?\s*(?:حرف|صحبت|گپ|چت)",
                     r"حالت\s*(?:عادی|قبلی)", r"برگرد", r"let'?s\s*(?:chat|talk)", r"just\s*chat", r"back\s*to\s*normal", r"you\s*can\s*joke")
HELP_RX = _rx(r"کمک(?:م)?\s*(?:کن|کنید|بده|می\s*کنی)", r"کمکم", r"راهنمایی", r"راهنما(?:م|یی)", r"help\s*me", r"can\s*you\s*help", r"need\s*help")
HOW_RX = _rx(r"چطور", r"چجور", r"چطوری\s+(?:\S+\s+){1,}", r"چه\s*جور", r"چگونه", r"چی\s*کار\s*کنم", r"چیکار\s*کنم", r"باید\s*(?:چی|چه|کجا|چیکار|چطور)",
             r"کجا\s*(?:برم|باید|هست|میشه|رو|را)", r"نمی\s*دونم\s*(?:باید|چی|چه|کجا|چطور|چیکار)", r"how\s*(?:do|to|can|should)", r"where\s*(?:do|should|can)\s*i")
TECH_RX = _rx(r"خطا", r"ارور", r"error", r"exception", r"traceback", r"crash", r"کرش", r"\bباگ", r"\bbug\b", r"فیکس", r"\bfix\b", r"ایراد", r"مشکل",
              r"کار\s*نمی\s*کنه", r"نمی\s*شه", r"باز\s*نمی\s*شه", r"\bلاگ", r"\blog\b", r"\bکد\b", r"\bcode\b", r"اسکریپت", r"\bscript", r"نصب", r"install",
              r"ورژن", r"version", r"\bapi\b", r"سرور", r"کانفیگ", r"config")
DO_RX = _rx(r"انجام\s*بده", r"\bبنویس", r"\bبساز", r"درست\s*کن", r"ترجمه\s*کن", r"خلاصه\s*کن", r"حل\s*کن", r"بررسی\s*کن", r"چک\s*کن", r"محاسبه",
            r"حساب\s*کن", r"پیدا\s*کن", r"راه\s*حل", r"یادم\s*بده", r"توضیح\s*بده", r"معنی", r"فرق\s+.{1,40}\s+چیه", r"برام\s+.{0,25}(?:بکن|بنویس|بساز|بفرست|ببین)",
            r"\btranslate", r"\bexplain", r"\bwrite\b", r"\bsolve", r"\bcheck\b", r"\breview", r"\bcalculate", r"\bsummari", r"\bfind\b")
REQUEST_RX = _rx(r"(?:^|\s)(?:می\s*شه|میشه|می\s*تونی|میتونی|می\s*تونید|میتونید|لطفا|لطفاً)\s", r"(?:^|\s)(?:بگو|بگی|بگید|بگین)(?:\s|$)", r"\bcould\s*you", r"\bwould\s*you", r"\bplease\b")
MEDIA_RX = _rx(r"عکس", r"تصویر", r"فایل", r"اسکرین", r"\bimage", r"\bphoto", r"\bpicture", r"screenshot", r"\bfile\b")
MEDIA_VERB_RX = _rx(r"ببین", r"تحلیل", r"آنالیز", r"بخون", r"بررسی", r"توصیف", r"می\s*بینی", r"نظرت", r"چیه", r"چی\s*هست", r"analy[sz]", r"look\s*at", r"describe", r"\bread\b", r"what.{0,20}see")
QWORD_RX = re.compile(r"(?:^|\s)(?:چرا|آیا|چیه|چیست|کیه|کجاست|چنده|کدومه|why|what|how)(?:\s|$)", re.I)
GAME_RX = _rx(r"بازی", r"\bgame", r"گیم", r"مرحله", r"\blevel", r"لول", r"\bboss", r"باس\b", r"ماموریت", r"مأموریت", r"\bquest", r"کاراکتر", r"بیلد", r"\bbuild\b",
              r"دانجن", r"dungeon", r"پازل", r"puzzle", r"چک\s*پوینت", r"checkpoint", r"walkthrough", r"گیر\s*کردم", r"stuck")
SMALLTALK_RX = _rx(r"دوست\s*داری", r"نظرت", r"فکر\s*می\s*کنی", r"ترجیح\s*می\s*دی", r"خوبی", r"چطوری\s*$", r"چه\s*خبر", r"حالت\s", r"دوستم\s*داری", r"دلتنگ", r"بامزه", r"خوشگل", r"عاشق", r"کجایی", r"چیکار\s*می\s*کنی",
                   r"چی\s*کار\s*می\s*کنی", r"خسته", r"ناراحت", r"خوشحال", r"دوستت", r"بوس", r"بغل", r"ناز\b", r"چی\s*خوردی", r"خوابیدی", r"how\s*are\s*you")
QUESTION_RX = re.compile(r"[?؟]")
WH_RX = re.compile(r"(?:چرا|چی|چه|کی|کجا|چند|کدوم|کدام|آیا|what|why|who|when|where|which)\b", re.I)


def _intent(text: str) -> tuple[str, bool]:
    """('task'|'chat'|'none', game?) for ONE message; 'none' = no signal."""
    if CHAT_RX.search(text) and not (HELP_RX.search(text) or TECH_RX.search(text)):
        return "chat", False
    game = bool(GAME_RX.search(text))
    if HELP_RX.search(text) or HOW_RX.search(text) or TECH_RX.search(text) or DO_RX.search(text):
        return "task", game
    if MEDIA_RX.search(text) and MEDIA_VERB_RX.search(text):
        return "task", game                                  # "look at this picture / analyse this file"
    # a request or a real question wants an answer, not banter - with or without a question mark
    asks = QUESTION_RX.search(text) or WH_RX.match(text) or QWORD_RX.search(text) or REQUEST_RX.search(text)
    if asks and len(text.split()) >= 3 and not SMALLTALK_RX.search(text):
        return "task", game
    return "none", game


_ATTACH_MARKS = ("[فایل ضمیمه", "--- فایل ضمیمه", "[تصویر ضمیمه")


def _typed(text: str) -> str:
    """Only what the user typed: the text of attached files (saved inside the message) must not switch modes."""
    cut = [text.find(m) for m in _ATTACH_MARKS if m in text]
    return text[:min(cut)] if cut else text


def _strict_held(previous: list[str]) -> bool:
    """STRICT stays on from the last "no jokes" request until an explicit request to chat/joke again."""
    held = False
    for t in previous:
        t = _typed(t)
        if STRICT_RX.search(t):
            held = True
        elif EXIT_STRICT_RX.search(t):
            held = False
    return held


def detect(text: str, previous_user: list[str] | None = None, has_files: bool = False) -> Mode:
    """text = the user's latest message; previous_user = his earlier messages (oldest first);
    has_files = something (image or file) is attached to this message."""
    cur = _norm(text)
    earlier = [_norm(t) for t in (previous_user or [])]
    prev = earlier[-STICKY_TURNS:]
    typed = _typed(cur)
    if STRICT_RX.search(typed):
        return Mode(STRICT, why="asked for a plain answer")
    if not EXIT_STRICT_RX.search(typed) and _strict_held(earlier):
        return Mode(STRICT, why="plain answer still requested")      # holds even when this message is a task
    kind, game = _intent(cur)
    if kind == "chat":
        return Mode(CHAT, why="asked to chat")
    if kind == "task":
        game = game or any(GAME_RX.search(t) for t in prev)
        return Mode(TASK, game=game, why="practical request")
    if has_files:
        return Mode(TASK, why="attachment")
    # no signal in this message: it continues what came before when it is short ("ok, and then?")
    if len(cur.split()) <= 8 and not SMALLTALK_RX.search(cur):
        for i, t in enumerate(reversed(prev)):
            k, g = _intent(t)
            if k == "task":
                return Mode(TASK, game=g or any(GAME_RX.search(x) for x in prev), why="continues a practical request")
            if k == "chat":
                break
    return Mode(CHAT, why="casual")


# ---- the blocks added to the system prompt ----
PRIORITY_BLOCK = """\
INSTRUCTION PRIORITY (this comes before everything below):
1. Understand what the user's LATEST message actually asks for, and do it. Answering or doing that is always the first priority.
2. Be accurate and safe.
3. Only then Kira's personality: it decides HOW she says things (tone, teasing, attitude), never WHETHER she does the thing and never what the answer contains.
If a personality rule below (attitude, flirting, teasing, self-praise, "short chat-style replies", "no lists", staying in a scene) would make a practical answer slower, vaguer or off-topic, the practical answer wins and the personality shrinks to a few words of flavour. A reply that is only banter when the user asked for something is a failure. Do not open a reply to a practical request with jokes or flirting before the answer.
The "ACTIVE MODE" block at the very end of this prompt says which kind of turn this is; follow it."""

MODE_BLOCKS = {
    CHAT: """\
ACTIVE MODE: CASUAL CHAT. Full personality: banter, teasing, flirting, attitude, opinions and moods. Still react to what he actually said, and if a real question slips into the chat, answer it too.""",
    TASK: """\
ACTIVE MODE: HELP / TASK (the user wants something done, solved or explained). This overrides the sentence-count and style hints above.
- Put the concrete answer, steps or result in the first sentences. At most one short in-character remark of a few words, before or after the substance and never instead of it.
- Be specific and complete. Numbered steps, short lists, code or commands are fine and expected when they help. Length follows the problem, not the "2 to 5 sentences" hint.
- No jokes that delay the answer, no flirting detours, no self-praise, no change of subject, no roleplay scene.
- If key information is missing, still give the most useful help you can from what you know and ask at most ONE short, specific question (which game, what is on the screen, the exact error text). You cannot see his screen or game unless an image is attached; never invent details about it.
- Keep Kira's voice (natural spoken Persian, or his language): same character, just focused.
- The emotion tag line required by OUTPUT FORMAT is still the first line.""",
    STRICT: """\
ACTIVE MODE: DIRECT ANSWER ONLY. The user asked for a plain answer without jokes. Obey this fully, also in the next messages, until he asks for banter again.
- Answer exactly what was asked, directly and in as few words as it needs. No jokes, teasing, flirting, swearing, self-praise, pet names, emotional flourishes or extra topics.
- Still his language and natural wording, but neutral and to the point.
- The emotion tag line required by OUTPUT FORMAT is still the first line (use [neutral:20] unless a real emotion fits).""",
}
GAME_ADDON = """\
- He is playing a game right now: give practical in-game guidance first (where to go, what to try, how to get past it), in a few short steps he can read mid-game. If the game or his situation is unknown, say what usually works in such a situation and ask which game and what he sees on screen."""


def mode_block(mode: Mode, tags: bool = True) -> str:
    """tags=False: the reply carries no emotion tag line this time (plain retry), so the lines about it are left out."""
    block = MODE_BLOCKS[mode.name]
    if mode.name == TASK and mode.game:
        block += "\n" + GAME_ADDON
    if not tags:
        block = "\n".join(ln for ln in block.splitlines() if "emotion tag" not in ln)
    return block


def temperature_for(mode: Mode, configured: float) -> float:
    """Practical answers are not helped by a high temperature: cap it (the user's own setting still applies below the cap)."""
    return min(float(configured), 0.4) if mode.name in (TASK, STRICT) else float(configured)
