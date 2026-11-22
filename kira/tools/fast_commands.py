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
    "get_system_info", "get_resource_usage", "get_disks", "get_network_info",
    "list_running_apps", "get_active_window",
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
        r"(?:what time is it(?: (?:right )?now)?|what(?:'s| is) the time(?: (?:right )?now)?|tell me the time(?: (?:right )?now)?|(?:the )?current time)",
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


_AUDIO = r"(?:صدای سیستم|صدا|ولوم|ولیوم|اسپیکر(?:ها)?|بلندگو(?:ها)?|volume|system volume|sound|audio|speakers?)"


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


_GENERIC_APP_WORDS = frozenset({
    "برنامه", "برنامه ها", "اپ", "اپلیکیشن", "نرم", "افزار", "نرم افزار", "رو", "را", "این", "اون", "آن",
    "یه", "یک", "ی", "همون", "همین", "هر", "برنامه‌ای", "app", "apps", "application", "program",
    "software", "the", "a", "an", "it", "that", "this", "one", "some", "any", "my", "your",
})


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
    # A bare generic word ("the app", "برنامه رو") is not an application name; the
    # model path must ask which app is meant instead of guessing one.
    if _GENERIC_APP_WORDS.issuperset(name.lower().split()):
        return None
    # Keep URLs, paths, files and compound/multi-action requests on the normal path.
    if any(token in name for token in ("/", "\\", "://", "؟", "?", "و ", " and ", " then ")) or "." in name:
        return None
    if re.search(r"\b(?:file|folder|directory|website|site|url|link|document|pdf|exe|command|terminal|powershell|cmd)\b", name, re.I):
        return None
    if re.search(r"(?:فایل|پوشه|فولدر|لینک|سایت|آدرس|دستور|ترمینال|پاورشل|و بعد|بعدش)", name):
        return None
    return _call("open_app", "apps", name=name)



def _system_info(text: str) -> dict | None:
    patterns = (
        r"(?:مشخصات|اطلاعات) (?:این )?(?:سیستم|کامپیوتر|لپ تاپ)(?: چیه| چیست| رو بگو| را بگو)?",
        r"(?:سیستم|کامپیوتر|لپ تاپ) (?:چه مشخصاتی داره|مشخصاتش چیه|اطلاعاتش چیه)",
        r"(?:system|pc|computer) (?:specs|specifications|info|information)",
        r"(?:show|tell me) (?:the )?(?:system|pc|computer) (?:specs|specifications|info|information)",
        r"what are (?:the )?(?:system|pc|computer) specs",
    )
    return _call("get_system_info", "system") if any(re.fullmatch(p, text, re.I) for p in patterns) else None


def _resource_usage(text: str) -> dict | None:
    # Specific metrics must be named; a bare "check my system" is not deterministic.
    all_patterns = (
        r"(?:مصرف منابع|منابع سیستم)(?: چقدره| چقدر است| چیه| چیست)?",
        r"(?:system resource usage|system performance|overall resource usage)",
        r"(?:وضعیت|مصرف) منابع (?:کامپیوتر|سیستم)",
    )
    if any(re.fullmatch(p, text, re.I) for p in all_patterns):
        return _call("get_resource_usage", "system", part="all")

    metrics = (
        ("ram", r"(?:حافظه رم|رم|ram|memory)"),
        ("cpu", r"(?:سی پی یو|پردازنده|cpu|processor)"),
        ("gpu", r"(?:کارت گرافیک|گرافیک|gpu)"),
        ("battery", r"(?:باتری|شارژ باتری|battery)"),
    )
    for part, term in metrics:
        patterns = (
            rf"چقدر (?:از )?{term} (?:مصرف شده|مصرف میشه|استفاده شده|استفاده میشه|درگیره|در حال استفاده است)",
            rf"(?:مصرف|استفاده) {term} (?:چقدره|چقدر است|چه قدر است|چند درصده)",
            rf"(?:میزان|وضعیت|مصرف) {term} (?:چیه|چیست|چقدره|چقدر است)?",
            rf"{term} (?:چقدر|چه قدر) (?:مصرف شده|استفاده شده|درگیره|مصرف میشه)",
            rf"{term} (?:usage|use|consumption|status|level|percentage)(?: now)?",
            rf"(?:show|check|what is) (?:the )?{term} (?:usage|use|consumption|status|level|percentage)",
            rf"how much (?:of the )?{term} (?:is )?(?:being used|used|available)",
        )
        if any(re.fullmatch(p, text, re.I) for p in patterns):
            return _call("get_resource_usage", "system", part=part)
    battery_patterns = (
        r"(?:وضعیت|درصد|مقدار) باتری(?: چیه| چقدره| چقدر است)?",
        r"باتری (?:چقدره|چه وضعیه|وضعیتش چیه|چند درصده)",
        r"(?:battery status|battery level|battery percentage|check battery)",
        r"how much battery (?:is )?left",
    )
    if any(re.fullmatch(p, text, re.I) for p in battery_patterns):
        return _call("get_resource_usage", "system", part="battery")
    return None


def _disks(text: str) -> dict | None:
    patterns = (
        r"(?:فضای خالی|فضای آزاد) (?:درایوها|دیسک ها|ذخیره سازی)(?: چقدره| چقدر است)?",
        r"(?:چقدر )?(?:فضای خالی|فضای آزاد) (?:روی )?(?:دیسک|درایوها)(?: دارم| باقی مونده| باقی مانده)?",
        r"(?:فضای ذخیره سازی|فضای دیسک|فضای درایوها)(?: چقدره| چقدر خالیه| چقدر است)?",
        r"(?:disk space|free disk space|available disk space|storage space|drive space)",
        r"how much (?:disk|storage) space (?:is )?(?:free|available)",
    )
    return _call("get_disks", "system") if any(re.fullmatch(p, text, re.I) for p in patterns) else None


def _network(text: str) -> dict | None:
    patterns = (
        r"(?:وضعیت|اتصال) (?:اینترنت|شبکه|وای فای)(?: چیه| چطوره| چیست)?",
        r"(?:اطلاعات|وضعیت) شبکه(?: چیه| چیست)?",
        r"آی پی (?:من )?(?:چیه|چیست|چنده)",
        r"(?:network information|network info|internet status|internet connection|my ip address)",
        r"what is my ip(?: address)?",
        r"am i connected to the internet",
    )
    return _call("get_network_info", "system") if any(re.fullmatch(p, text, re.I) for p in patterns) else None


def _running_apps(text: str) -> dict | None:
    patterns = (
        r"(?:چه|کدوم) (?:برنامه|اپلیکیشن|اپ)(?: ها| هایی)? (?:الان )?(?:باز|در حال اجرا)(?: هستند|ن| هستن)?",
        r"(?:برنامه|اپلیکیشن|اپ) های (?:باز|در حال اجرا)(?: کدوما| چیا)?",
        r"(?:لیست|فهرست) (?:برنامه|اپلیکیشن|اپ) های (?:باز|در حال اجرا)",
        r"(?:برنامه های باز|اپ های باز) چیا هستن",
        r"(?:list|show) (?:the )?(?:open|running) apps",
        r"what apps are (?:open|running)",
        r"which apps are (?:open|running)",
    )
    return _call("list_running_apps", "apps") if any(re.fullmatch(p, text, re.I) for p in patterns) else None


def _active_window(text: str) -> dict | None:
    patterns = (
        r"(?:پنجره فعال|پنجره فعلی)(?: چیه| چیست)?",
        r"(?:الان )?(?:چه برنامه ای|کدوم برنامه) (?:فعاله|در حال استفاده است|رو دارم استفاده می کنم)",
        r"(?:الان )?من توی چه برنامه ای هستم",
        r"(?:what|which) (?:app|program|window) (?:am i using|is active|is in the foreground)",
        r"what is the active window",
        r"what app am i currently using",
    )
    return _call("get_active_window", "apps") if any(re.fullmatch(p, text, re.I) for p in patterns) else None


def parse_fast_command(text: str) -> dict | None:
    """Return one exact ToolRegistry call, or None when the request is not safely deterministic."""
    value = normalize(text)
    if not value or len(value) > 180:
        return None
    if _datetime(value):
        return _call("get_datetime", "time")
    for parser in (_system_info, _resource_usage, _disks, _network, _running_apps, _active_window):
        command = parser(value)
        if command:
            return command
    command = _bluetooth(value)
    if command:
        return command
    command = _audio(value)
    if command:
        return command
    return _app(value)
