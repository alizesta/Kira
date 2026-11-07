"""User dictionary for speech recognition: words Whisper should lean towards, and fixes for words it keeps mishearing.

File: <Kira data folder>/speech_fixes.json (created with an example the first time you open it from the Voice tab):
    {"hotwords": ["کیرا", "اهواز"], "replace": {"چطورین": "چطورید", "نمیتونم": "نمی‌تونم"}}
The file is re-read automatically when it changes, so edits apply to the next sentence without restarting the microphone.
"""
from __future__ import annotations

import json
import re

from .config import DATA_DIR
from .speech_text import normalize_fa

FILE = DATA_DIR / "speech_fixes.json"
MAX_HOTWORDS = 40
EXAMPLE = {
    "_help": "hotwords: کلمه‌هایی که Whisper باید بهشون متمایل باشه (اسم آدم‌ها، شهرها، اصطلاح‌های لهجه‌ی خودت). "
             "replace: «اشتباهی»: «درست» - بعد از تشخیص، کلمه‌ی کامل جایگزین می‌شود. بعد از ذخیره‌ی فایل لازم نیست چیزی را دوباره راه‌اندازی کنی.",
    "hotwords": ["کیرا"],
    "replace": {"چطورین": "چطورید"},
}


class SpeechFixes:
    def __init__(self, path=None):
        self.path = path or FILE
        self.hotwords, self.rules, self.error = [], [], ""
        self._mtime = None

    def ensure_file(self):
        """Create the example file if there is none (an existing file is never touched). Returns the path."""
        if not self.path.exists():
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(EXAMPLE, ensure_ascii=False, indent=2), encoding="utf-8")
        return self.path

    def refresh(self):
        """Re-read the file when it changed. A broken file keeps the last good content and sets `error`."""
        try:
            mtime = self.path.stat().st_mtime
        except OSError:
            self.hotwords, self.rules, self._mtime, self.error = [], [], None, ""
            return
        if mtime == self._mtime:
            return
        self._mtime = mtime
        try:
            data = json.loads(self.path.read_text(encoding="utf-8-sig"))
            if not isinstance(data, dict):
                raise ValueError("ساختار فایل باید یک شیء JSON باشد.")
            hot = [normalize_fa(w) for w in (data.get("hotwords") or []) if isinstance(w, str) and w.strip()]
            pairs = {normalize_fa(k): normalize_fa(v) for k, v in (data.get("replace") or {}).items()
                     if isinstance(k, str) and isinstance(v, str) and k.strip()}
        except Exception as exc:                                  # noqa: BLE001 - a typo in the file must never stop the microphone
            self.error = f"speech_fixes.json خوانده نشد: {exc}"
            return
        self.error = ""
        self.hotwords = hot[:MAX_HOTWORDS]
        self.rules = [(re.compile(r"(?<![\w\u200c])" + re.escape(k) + r"(?![\w\u200c])"), v)
                      for k, v in sorted(pairs.items(), key=lambda kv: -len(kv[0]))]       # longest phrase first

    def hotwords_text(self):
        return " ".join(self.hotwords)

    def apply(self, text):
        for pattern, repl in self.rules:
            text = pattern.sub(repl, text)
        return text
