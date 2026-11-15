import os
import subprocess
import webbrowser

ACTIONS = {
    "notepad": ("Notepad", ["notepad.exe"]),
    "calculator": ("Calculator", ["calc.exe"]),
    "paint": ("Paint", ["mspaint.exe"]),
    "explorer": ("File Explorer", ["explorer.exe"]),
    "clock": ("Clock", ["explorer.exe", "ms-clock:"]),
}

def run_safe_action(text, allow_desktop=True):
    if not allow_desktop:
        return "در حالت Competitive Safe اجرای میانبرهای دسکتاپ غیرفعال است."
    t = text.strip().lower()
    aliases = {
        "نوت پد": "notepad", "نوت‌پد": "notepad", "notepad": "notepad",
        "ماشین حساب": "calculator", "ماشین‌حساب": "calculator", "calculator": "calculator",
        "پینت": "paint", "paint": "paint",
        "فایل اکسپلورر": "explorer", "اکسپلورر": "explorer", "فایل منیجر": "explorer",
        "ساعت": "clock", "clock": "clock",
        "مرورگر": "browser", "مرورگر رو باز کن": "browser", "browser": "browser",
    }
    for phrase, key in aliases.items():
        if phrase in t:
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
                except Exception as e:
                    return f"نتونستم {label} رو باز کنم: {e}"
    return None
