import os
import re
import subprocess
import webbrowser

ACTIONS = {
    "notepad": ("Notepad", ["notepad.exe"]),
    "calculator": ("Calculator", ["calc.exe"]),
    "paint": ("Paint", ["mspaint.exe"]),
    "explorer": ("File Explorer", ["explorer.exe"]),
    "clock": ("Clock", ["explorer.exe", "ms-clock:"]),
}

ALIASES = {
    "نوت پد": "notepad", "نوت‌پد": "notepad", "notepad": "notepad",
    "ماشین حساب": "calculator", "ماشین‌حساب": "calculator", "calculator": "calculator",
    "پینت": "paint", "paint": "paint",
    "فایل اکسپلورر": "explorer", "اکسپلورر": "explorer", "فایل منیجر": "explorer",
    "ساعت": "clock", "clock": "clock",
    "مرورگر": "browser", "مرورگر رو باز کن": "browser", "browser": "browser",
}


def match_safe_action(text):
    """Return a fixed shortcut only for an explicit, non-negated launch request."""
    normalized = re.sub(r"\s+", " ", str(text or "").replace("\u200c", " ").strip().lower())
    if not normalized:
        return None
    if re.search(
        r"\b(?:don't|do not|never|not)\b|\bno\b|"
        r"نمی\s*(?:خوام|خواهم)|نخواه|باز\s+نکن|اجرا\s+نکن|"
        r"لغو|بی\s*خیال|بیخیال",
        normalized,
    ):
        return None
    key = next((value for phrase, value in ALIASES.items() if phrase in normalized), None)
    if key is None:
        return None
    explicit_intent = bool(re.search(
        r"\b(?:open|launch|run|start|bring\s+up)\b|باز\s*کن|اجرا\s*کن|روشن\s*کن",
        normalized,
    ))
    return key if explicit_intent or normalized in ALIASES else None


def run_safe_action(text, allow_desktop=True):
    if not allow_desktop:
        return "در حالت Competitive Safe اجرای میانبرهای دسکتاپ غیرفعال است."
    key = match_safe_action(text)
    if key == "browser":
        webbrowser.open("https://www.google.com")
        return "مرورگر پیش‌فرض رو باز کردم."
    if key in ACTIONS:
        label, command = ACTIONS[key]
        try:
            if key == "clock":
                os.startfile(command[1])
            else:
                subprocess.Popen(command, shell=False)
            return f"{label} رو باز کردم."
        except Exception as exc:
            return f"نتونستم {label} رو باز کنم: {exc}"
    return None
