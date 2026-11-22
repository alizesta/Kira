"""Deterministic, high-confidence command parsing for Kira's internal fast path.

This module is an allow-list only. It recognises one-step, low-risk requests and
returns ordinary ToolRegistry calls; it never executes OS operations itself.
Anything ambiguous stays on Kira's existing model / agent path.
"""
from __future__ import annotations

import re


_ALLOWED = {
    "get_datetime", "open_app", "bluetooth_status", "bluetooth_on", "bluetooth_off",
    "audio_set_volume", "audio_change_volume", "audio_mute", "audio_unmute",
}
_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_LETTERS = str.maketrans({
    "ي": "ی", "ك": "ک", "ۀ": "ه", "ة": "ه", "ـ": "",
    "\u200c": " ", "\u200d": " ", "\u200f": "", "\u200e": "",
})
_SPACE = re.compile(r"\s+")


def normalize(text: str) -> str:
    """Normalize Persian/Arabic orthography and digits without changing app names."""
    value = str(text or "").lower().translate(_LETTERS).translate(_DIGITS)
    value = _SPACE.sub(" ", value).strip()
    return value.strip(" \t\r\n.!؟?،,؛;:")


def _call(tool: str, category: str, **args) -> dict | None:
    if tool not in _ALLOWED:
        return None
    return {"tool": tool, "args": args, "category": category}


def _datetime(text: str) -> bool:
    patterns = (
        r"(?:الان )?ساعت(?: الان)? چنده",
        r"الان ساعت چنده",
        r"ساعت چند(?:ه| است)?",
        r"(?:تاریخ امروز|امروز تاریخ)(?: چیه| چیست| چندمه| چندم)?",
        r"امروز چندمه",
        r"امروز چه روزیه",
        r"تاریخ امروز چیه",
        r"(?:what time is it(?: now)?|what(?:'s| is) the time(?: now)?|tell me the time|current time)",
        r"(?:what(?:'s| is) the date(?: today)?|what date is it(?: today)?|today'?s date|current date|date today)",
        r"(?:date and time|time and date)",
    )
    return any(re.fullmatch(pattern, text, re.I) for pattern in patterns)


_BT = r"(?:بلوتوث|بلو توث|بلو توس|bluetooth)"


def _bluetooth(text: str) -> dict | None:
    if (
        re.fullmatch(rf"(?:وضعیت )?{_BT}(?: رو)? (?:چک کن|بررسی کن|وضعیتش چیه|چه وضعیه|چیه|چیست)", text)
        or re.fullmatch(rf"وضعیت {_BT}(?: چیه| چیست)?", text)
        or re.fullmatch(rf"{_BT} وضعیت(?:ش)?(?: چیه| چیست)?", text)
    ):
        return _call("bluetooth_status", "bluetooth")
    if re.fullmatch(rf"{_BT} (?:روشنه|خاموشه|فعاله|غیرفعاله)", text):
        return _call("bluetooth_status", "bluetooth")
    if re.fullmatch(r"(?:bluetooth status|check bluetooth|is bluetooth (?:on|off|enabled|disabled))", text):
        return _call("bluetooth_status", "bluetooth")
    if re.fullmatch(rf"(?:لطفا )?{_BT}(?: رو| را)? (?:روشن|فعال)(?: کن)?", text) or re.fullmatch(
        r"(?:please )?(?:turn|switch) bluetooth on|(?:please )?enable bluetooth|bluetooth on", text
    ):
        return _call("bluetooth_on", "bluetooth")
    if re.fullmatch(rf"(?:لطفا )?{_BT}(?: رو| را)? (?:خاموش|غیرفعال|غیر فعال)(?: کن)?", text) or re.fullmatch(
        r"(?:please )?(?:turn|switch) bluetooth off|(?:please )?disable bluetooth|bluetooth off", text
    ):
        return _call("bluetooth_off", "bluetooth")
    return None


_AUDIO = r"(?:صدای سیستم|صدا|ولوم|ولیوم|volume|system volume|sound|audio|speakers?)"


def _audio(text: str) -> dict | None:
    # Unmute before mute: the words overlap in common Persian phrases.
    if (
        re.fullmatch(
            rf"(?:لطفا )?(?:{_AUDIO} رو )?(?:از حالت )?(?:میوت|mute|سایلنت|بی صدا)(?: رو)? (?:بردار|در بیار|دربیار|خارج کن|لغو کن)",
            text,
        )
        or re.fullmatch(rf"(?:لطفا )?{_AUDIO} رو از حالت (?:میوت|سایلنت|بی صدا) دربیار", text)
        or re.fullmatch(
            rf"(?:please )?(?:unmute|unsilence)(?: the)? (?:system )?(?:volume|sound|audio|speakers?)", text, re.I
        )
        or re.fullmatch(r"(?:unmute|unsilence)(?: the)? speakers?", text, re.I)
    ):
        return _call("audio_unmute", "audio")
    if (
        re.fullmatch(rf"(?:لطفا )?{_AUDIO}(?: رو| را)? (?:قطع|خاموش|میوت|سایلنت|بی صدا)(?: کن)?", text)
        or re.fullmatch(rf"(?:لطفا )?(?:میوت|سایلنت|بی صدا)(?: کن)?(?: {_AUDIO})?", text)
        or re.fullmatch(
            rf"(?:please )?(?:mute|silence)(?: the)? (?:system )?(?:volume|sound|audio|speakers?)", text, re.I
        )
    ):
        return _call("audio_mute", "audio")

    set_patterns = (
        rf"(?:لطفا )?{_AUDIO}(?: رو| را)? (?:روی|به|تا)? ?(\d{{1,3}})\s*(?:درصد|٪|%)?(?: (?:بذار|بزار|بگذار|تنظیم کن|کن|بکن))?",
        rf"(?:لطفا )?{_AUDIO}(?: رو| را)? (?:ببر|برسون|برسان) (?:روی|به )?(\d{{1,3}})\s*(?:درصد|٪|%)?",
        r"(?:please )?(?:set )?(?:the )?(?:system )?(?:volume|sound|audio) (?:to|at) (\d{1,3})\s*(?:%|percent|per cent)?",
    )
    for pattern in set_patterns:
        match = re.fullmatch(pattern, text, re.I)
        if match:
            value = int(match.group(1))
            if 0 <= value <= 100:
                return _call("audio_set_volume", "audio", percent=value)
            return None

    up_fa = rf"(?:لطفا )?{_AUDIO}(?: رو| را)? (?:زیادتر|زیاد|بیشتر|بلندتر|بالا)(?: کن| بکن| کنید)?"
    down_fa = rf"(?:لطفا )?{_AUDIO}(?: رو| را)? (?:کمتر|کم|آرومتر|آروم تر|آرام تر|پایین)(?: کن| بکن| کنید)?"
    up_en = r"(?:please )?(?:(?:turn|make) (?:the )?)?(?:volume|sound|audio) up|(?:increase|raise|boost) (?:the )?(?:system )?(?:volume|sound|audio)"
    down_en = r"(?:please )?(?:(?:turn|make) (?:the )?)?(?:volume|sound|audio) down|(?:decrease|lower|reduce) (?:the )?(?:system )?(?:volume|sound|audio)"
    if re.fullmatch(up_fa, text) or re.fullmatch(up_en, text, re.I):
        return _call("audio_change_volume", "audio", direction="up", amount=10)
    if re.fullmatch(down_fa, text) or re.fullmatch(down_en, text, re.I):
        return _call("audio_change_volume", "audio", direction="down", amount=10)
    return None


def _app(text: str) -> dict | None:
    patterns = (
        r"(?:لطفا )?(?:(?:برنامه|اپلیکیشن|اپ) )?(.+?) (?:(?:رو|را) )?(?:باز کن|اجرا کن|بالا بیار|راه بنداز)",
        r"(?:لطفا )?(?:باز کن|اجرا کن) (?:(?:برنامه|اپلیکیشن|اپ) )?(.+)",
        r"(?:please )?(?:open|launch|run|start) (?:the )?(?:app )?(.+)",
    )
    name = None
    for pattern in patterns:
        match = re.fullmatch(pattern, text, re.I)
        if match:
            name = match.group(1).strip().strip("\"'“”‘’")
            break
    if not name or len(name) > 64 or len(name.split()) > 5:
        return None
    # Keep URLs, paths, files and compound/multi-action requests on the normal path.
    if any(token in name for token in ("/", "\\", "://", "؟", "?", "و ", " and ", " then ")) or "." in name:
        return None
    if re.search(r"\b(?:file|folder|directory|website|site|url|link|document|pdf|exe|command|terminal|powershell|cmd)\b", name, re.I):
        return None
    if re.search(r"(?:فایل|پوشه|فولدر|لینک|سایت|آدرس|دستور|ترمینال|پاورشل|و بعد|بعدش)", name):
        return None
    return _call("open_app", "apps", name=name)


def parse_fast_command(text: str) -> dict | None:
    """Return one exact ToolRegistry call, or None when the request is not safely deterministic."""
    value = normalize(text)
    if not value or len(value) > 180:
        return None
    if _datetime(value):
        return _call("get_datetime", "time")
    command = _bluetooth(value)
    if command:
        return command
    command = _audio(value)
    if command:
        return command
    return _app(value)
