"""Shared, controlled Windows PowerShell runner for Windows Control modules (Bluetooth, Audio, later wallpaper / tray / system).

What it is: ONE place that starts Windows PowerShell 5.1 with a FIXED script and returns the parsed JSON the script printed.

What it is not: a shell. Rules that are enforced here (not just promised):
  * Only a `FixedScript` object can be run. Its text is created once, at import time, by the module that owns it. A plain `str` is refused (TypeError),
    so nobody can pass user / model text as a script by accident.
  * Variable data never becomes part of the script. A module passes it as environment variables named `KIRA_*` (the script reads `$env:KIRA_...`
    as DATA and parses it itself). Names and sizes are checked here; the module validates the values.
  * The script is sent with -EncodedCommand (base64 UTF-16LE): no quoting problem, no command line to inject into. `shell=False` always.
  * `powershell.exe` is taken from the Windows System32 folder when it exists (not from whatever comes first on PATH).

Return value of run_fixed(): the JSON object the script printed, or {'ok': False, 'error': <real reason>, 'fatal': True} when PowerShell itself failed
(not found, timed out, no / invalid output).
"""
from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import sys

IS_WIN = sys.platform == "win32"
NO_WINDOW = 0x08000000 if IS_WIN else 0
_ENV_NAME_RX = re.compile(r"^KIRA_[A-Z0-9_]{1,40}$")
MAX_ENV_CHARS = 8000
_FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


class FixedScript:
    """A PowerShell script written by us, in source code. Create it once at module level; never build one from user or model text."""
    __slots__ = ("name", "text")

    def __init__(self, name: str, text: str):
        self.name = str(name)
        self.text = str(text)


def powershell_path() -> str:
    root = os.environ.get("SystemRoot") or os.environ.get("WINDIR") or r"C:\Windows"
    candidate = os.path.join(root, "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
    return candidate if os.path.isfile(candidate) else "powershell.exe"


def run_fixed(script: FixedScript, env: dict | None = None, timeout: int = 45, api_name: str = "ویندوز") -> dict:
    """Run a FixedScript. `env` = {'KIRA_NAME': 'value'} data for the script. -> parsed JSON dict, or a fatal error dict (see module doc)."""
    if not isinstance(script, FixedScript):
        raise TypeError("فقط FixedScript اجرا می‌شود؛ متن آزاد به‌عنوان اسکریپت پذیرفته نمی‌شود.")
    child_env = None
    if env:
        child_env = dict(os.environ)
        for key, value in env.items():
            if not _ENV_NAME_RX.match(str(key)):
                raise ValueError(f"نام متغیر محیطی «{key}» مجاز نیست (باید با KIRA_ شروع شود).")
            value = str(value)
            if len(value) > MAX_ENV_CHARS:
                raise ValueError(f"مقدار «{key}» بیش از حد بزرگ است.")
            child_env[str(key)] = value
    encoded = base64.b64encode(script.text.encode("utf-16-le")).decode("ascii")
    try:
        r = subprocess.run([powershell_path(), "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
                           capture_output=True, timeout=timeout, creationflags=NO_WINDOW, env=child_env)
    except FileNotFoundError:
        return {"ok": False, "error": "Windows PowerShell (powershell.exe) پیدا نشد", "fatal": True}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"پاسخ API {api_name} بیش از {str(timeout).translate(_FA_DIGITS)} ثانیه طول کشید", "fatal": True}
    except OSError as e:
        return {"ok": False, "error": f"اجرای PowerShell ممکن نشد: {e}", "fatal": True}
    text = r.stdout.decode("utf-8", "ignore").strip()
    try:
        data = json.loads(text[text.index("{"):]) if "{" in text else {}
    except ValueError:
        data = {}
    if not isinstance(data, dict) or not data:
        err = r.stderr.decode("utf-8", "ignore").strip()[:300] or f"خروجی نامعتبر (کد {r.returncode})"
        return {"ok": False, "error": err, "fatal": True}
    return data
