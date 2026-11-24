"""Desktop Interaction (T5-B): windows, keyboard, mouse, clipboard and UI controls - with the target window checked BEFORE every input.

Layers
  Win32Backend   the only code that touches Windows (ctypes user32 / SendInput; UI Automation through ONE fixed PowerShell script whose
                 inputs are passed as JSON in an environment variable, never pasted into code). No new dependency.
  DesktopTools   the policy: which window may receive input, which keys are allowed, what needs a confirmation, and how results are verified.
  DesktopModule  declares the capabilities for the Windows Control Layer (domain "desktop").

Rules enforced here (in code, not in the prompt)
  * Input goes only to a window that is resolved from the user's words, is not Kira itself, not a terminal / shell / Run dialog / credential /
    UAC / password-manager window, and is verified to be the FOREGROUND window right before (and, while typing, during) the input.
  * Keys are a closed whitelist (editing shortcuts, navigation, Enter, Esc, Tab ...). No Win key, no Alt+F4 (use window_close), no Ctrl+Alt+Del.
  * Controls whose name sounds destructive / irreversible / a login or payment can only be used through the confirmed twin tool.
  * Password fields are never read or filled; typed text that looks like a key or password is refused.
  * Results are real: closing re-checks that the window is gone; typing / clicking say that the effect itself cannot be verified.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time

from .registry import Param, ToolError, READ, ACTION, SENSITIVE, DENIED, redact_secrets
from .wincontrol import Capability, WinModule
from .winrunner import FixedScript, run_fixed

IS_WIN = sys.platform == "win32"
TYPE_MAX = 2000
TYPE_CHUNK = 40
UIA_TIMEOUT = 20
UIA_MAX_CONTROLS = 80
BROWSERS = {"chrome", "msedge", "firefox", "brave", "opera", "vivaldi", "iexplore", "arc"}
ALIASES = {"browser": BROWSERS, "مرورگر": BROWSERS, "word": {"winword"}, "ورد": {"winword"}, "excel": {"excel"}, "اکسل": {"excel"},
           "notepad": {"notepad"}, "نوت پد": {"notepad"}, "نوتپد": {"notepad"}, "explorer": {"explorer"}, "فایل اکسپلورر": {"explorer"},
           "powerpoint": {"powerpnt"}, "پاورپوینت": {"powerpnt"}, "calculator": {"calculatorapp", "calc", "calculator"}, "ماشین حساب": {"calculatorapp", "calc"}}
# input is never sent to these (a shell / script host / admin console would turn typing into arbitrary command execution)
BLOCKED_PROCESSES = {"cmd", "powershell", "powershell_ise", "pwsh", "windowsterminal", "wt", "conhost", "openconsole", "bash", "wsl", "wslhost", "mshta",
                     "wscript", "cscript", "regedit", "mmc", "taskmgr", "secpol", "gpedit", "consent", "securityhealthui", "lockapp", "logonui",
                     "credentialuibroker", "keepass", "keepassxc", "1password", "bitwarden", "lastpass", "dashlane", "putty", "mstsc"}
BLOCKED_TITLE_RX = re.compile(r"(?i)(password|passcode|credential|sign[\s-]*in|log[\s-]*in|authenticat|user account control|windows security|"
                              r"پسورد|رمز|ورود به|احراز\s*هویت|کنترل\s*حساب\s*کاربری|امنیت\s*ویندوز)")
RUN_DIALOG_TITLES = {"run", "اجرا"}
DANGEROUS_CONTROL_RX = re.compile(r"(?i)(delete|remove|erase|uninstall|format|reset|wipe|clear all|pay|purchase|buy|checkout|order|send|submit|publish|post\b|transfer|"
                                  r"sign[\s-]*in|log[\s-]*in|install|allow|grant|accept|agree|permanently|empty recycle|"
                                  r"حذف|پاک|نصب|پرداخت|خرید|سفارش|ارسال|انتشار|فرمت|ریست|بازنشانی|انتقال|ورود|اجازه|موافقم|می‌پذیرم|می پذیرم)")
VK = {
    "enter": 0x0D, "return": 0x0D, "tab": 0x09, "esc": 0x1B, "escape": 0x1B,
    "backspace": 0x08, "delete": 0x2E, "del": 0x2E, "insert": 0x2D, "space": 0x20,
    "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27, "home": 0x24, "end": 0x23,
    "pageup": 0x21, "pagedown": 0x22, "printscreen": 0x2C, "pause": 0x13,
    "capslock": 0x14, "numlock": 0x90, "scrolllock": 0x91,
    "ctrl": 0x11, "shift": 0x10, "alt": 0x12, "win": 0x5B,
    **{chr(c).lower(): c for c in range(ord("A"), ord("Z") + 1)},
    **{str(d): 0x30 + d for d in range(10)},
    **{f"f{n}": 0x6F + n for n in range(1, 25)},
    **dict(zip(("semicolon", "equals", "comma", "minus", "period", "slash", "grave",
                "leftbracket", "backslash", "rightbracket", "apostrophe"),
               (0xBA, 0xBB, 0xBC, 0xBD, 0xBE, 0xBF, 0xC0, 0xDB, 0xDC, 0xDD, 0xDE))),
}
SAFE_PLAIN = {"enter", "return", "tab", "esc", "escape", "backspace", "delete", "del", "insert", "space",
              "up", "down", "left", "right", "home", "end", "pageup", "pagedown", "printscreen", "pause",
              "capslock", "numlock", "scrolllock", *{f"f{n}" for n in range(1, 25)}}
SAFE_CTRL = set("ACXVZYSFNOPWTLDRBIU") | {"enter", "tab", "home", "end", "left", "right", "up", "down",
              "backspace", "delete", "insert", "pageup", "pagedown"}
# Modifier combinations stay deliberately narrow: navigation/selection only.
# Letter combinations can trigger app-specific destructive or security-sensitive commands.
SAFE_CTRL_SHIFT = {"left", "right", "up", "down", "home", "end", "tab"}
SAFE_SHIFT = SAFE_PLAIN - {"f1"}
SAFE_ALT = {"left", "right", "tab", "home", "space"}
SAFE_WIN = {"a", "d", "e", "g", "i", "s", "t", "v", "x", "tab", "up", "down", "left", "right",
            "1", "2", "3", "4", "5", "6", "7", "8", "9", "0", "period"}
SAFE_WIN_CTRL = {"d", "left", "right", "f4", "o"}


def _fa(text) -> str:
    return re.sub(r"\s+", " ", str(text or "").lower().replace("ي", "ی").replace("ك", "ک").replace("‌", " ").replace("‏", " ")).strip()


def parse_combo(combo: str):
    """Parse one bounded, allow-listed Windows virtual-key combination."""
    parts = [p.strip().lower() for p in re.split(r"\s*\+\s*", str(combo or "").strip()) if p.strip()]
    if not parts or len(parts) > 4:
        raise ToolError("کلید نامعتبر است؛ نمونه: alt+tab، win+e، win+ctrl+left، ctrl+shift+left.")
    mods, key = parts[:-1], parts[-1]
    allowed_mods = {"ctrl", "shift", "alt", "win"}
    if any(m not in allowed_mods for m in mods) or len(set(mods)) != len(mods):
        raise ToolError("ترکیب modifierها نامعتبر است.", DENIED)
    if key not in VK or key in allowed_mods:
        raise ToolError(f"کلید «{key}» پشتیبانی نمی‌شود.")
    mset = frozenset(mods)
    up = key.upper() if len(key) == 1 else key
    punctuation = {"semicolon", "equals", "comma", "minus", "period", "slash", "grave",
                   "leftbracket", "backslash", "rightbracket", "apostrophe"}
    if not mset:
        allowed = key in SAFE_PLAIN or len(key) == 1 or key in punctuation
    elif mset == {"ctrl"}:
        allowed = up in SAFE_CTRL
    elif mset == {"shift"}:
        allowed = key in SAFE_SHIFT
    elif mset == {"alt"}:
        allowed = key in SAFE_ALT
    elif mset == {"ctrl", "shift"}:
        allowed = up in SAFE_CTRL_SHIFT or key in SAFE_CTRL_SHIFT
    elif mset == {"win"}:
        allowed = key in SAFE_WIN
    elif mset == {"win", "ctrl"}:
        allowed = key in SAFE_WIN_CTRL
    elif mset == {"win", "shift"}:
        allowed = key in {"left", "right"}
    else:
        allowed = False
    if (key == "f4" and "alt" in mset) or (mset == {"win"} and key in {"r", "l"}):
        allowed = False
    if not allowed:
        raise ToolError(f"ترکیب «{'+'.join(parts)}» در فهرست مجاز نیست.", DENIED)
    return [VK[m] for m in mods] + [VK[key]], "+".join(parts)


# =============================================================================================== Win32 backend
UIA_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes
$a = $env:KIRA_UIA | ConvertFrom-Json
$root = [System.Windows.Automation.AutomationElement]::FromHandle([IntPtr][int64]$a.hwnd)
$types = 'Button','Edit','MenuItem','CheckBox','RadioButton','ComboBox','ListItem','TabItem','Hyperlink','SplitButton','Document'
function Info($e) {
  $r = $e.Current.BoundingRectangle
  $pw = $false; try { $pw = [bool]$e.Current.IsPassword } catch {}
  [pscustomobject]@{ name = [string]$e.Current.Name; type = $e.Current.ControlType.ProgrammaticName.Replace('ControlType.',''); id = [string]$e.Current.AutomationId;
    enabled = [bool]$e.Current.IsEnabled; password = $pw; x = [int]($r.X + $r.Width/2); y = [int]($r.Y + $r.Height/2); w = [int]$r.Width; h = [int]$r.Height }
}
function Find-All {
  $ct = [System.Windows.Automation.ControlType]
  $conds = [System.Windows.Automation.Condition[]]@($types | ForEach-Object { [System.Windows.Automation.PropertyCondition]::new([System.Windows.Automation.AutomationElement]::ControlTypeProperty, $ct.GetProperty($_).GetValue($null)) })
  $cond = [System.Windows.Automation.OrCondition]::new($conds)
  $root.FindAll([System.Windows.Automation.TreeScope]::Descendants, $cond)
}
function Pick($list, $name, $type) {
  $m = @(); foreach ($e in $list) { if ($e.Current.IsOffscreen) { continue }
    $n = [string]$e.Current.Name; if ($n -eq '' -and $a.mode -ne 'settext') { continue }
    $t = $e.Current.ControlType.ProgrammaticName.Replace('ControlType.','')
    if ($type -and $t -ne $type) { continue }
    if ($name -and $n -ne $name -and -not $n.ToLower().Contains(([string]$name).ToLower())) { continue }
    $m += $e }
  $m
}
$out = @{ ok = $true }
if ($a.mode -eq 'list') {
  $items = @(); foreach ($e in (Find-All)) { if ($e.Current.IsOffscreen -or [string]$e.Current.Name -eq '') { continue }; $items += Info $e; if ($items.Count -ge [int]$a.limit) { break } }
  $out.items = $items
} else {
  $m = @(Pick (Find-All) $a.name $a.type)
  $exact = @($m | Where-Object { [string]$_.Current.Name -eq [string]$a.name })
  if ($exact.Count -ge 1) { $m = $exact }
  if ($m.Count -eq 0) { $out.ok = $false; $out.error = 'not_found' }
  elseif ($m.Count -gt 1) { $out.ok = $false; $out.error = 'ambiguous'; $out.items = @($m | Select-Object -First 6 | ForEach-Object { Info $_ }) }
  else {
    $e = $m[0]; $out.target = Info $e
    if ($out.target.password) { $out.ok = $false; $out.error = 'password' }
    elseif (-not $out.target.enabled) { $out.ok = $false; $out.error = 'disabled' }
    elseif ($a.mode -eq 'invoke') {
      $p = $null
      if ($e.TryGetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern, [ref]$p)) { $p.Invoke(); $out.how = 'invoke' }
      elseif ($e.TryGetCurrentPattern([System.Windows.Automation.TogglePattern]::Pattern, [ref]$p)) { $p.Toggle(); $out.how = 'toggle' }
      elseif ($e.TryGetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern, [ref]$p)) { $p.Select(); $out.how = 'select' }
      elseif ($e.TryGetCurrentPattern([System.Windows.Automation.ExpandCollapsePattern]::Pattern, [ref]$p)) { $p.Expand(); $out.how = 'expand' }
      else { $out.ok = $false; $out.error = 'no_pattern' }
    } elseif ($a.mode -eq 'settext') {
      $p = $null
      if ($e.TryGetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern, [ref]$p) -and -not $p.Current.IsReadOnly) {
        $p.SetValue([string]$a.text); $out.how = 'value'; $out.value_after = [string]$p.Current.Value
      } else { $out.ok = $false; $out.error = 'no_value_pattern' }
    }
  }
}
$out | ConvertTo-Json -Depth 5 -Compress
"""
UIA_FIXED = FixedScript("uia", UIA_SCRIPT)


class Win32Backend:
    """Windows-only calls. Everything returns plain data; nothing here decides policy."""

    def _need(self):
        if not IS_WIN:
            raise ToolError("کنترل دسکتاپ فقط روی ویندوز ممکن است.")
        import ctypes
        return ctypes.windll.user32

    def windows(self) -> list:
        from . import sysinfo
        user32 = self._need()
        out = []
        for w in sysinfo.visible_windows():
            h = w["hwnd"]
            out.append({**w, "minimized": bool(user32.IsIconic(h)), "maximized": bool(user32.IsZoomed(h))})
        return out

    def foreground(self) -> int:
        return int(self._need().GetForegroundWindow() or 0)

    def is_window(self, hwnd: int) -> bool:
        return bool(self._need().IsWindow(int(hwnd)))

    def activate(self, hwnd: int):
        from . import sysinfo
        return sysinfo.activate_window(hwnd)

    def close(self, hwnd: int) -> None:
        self._need().PostMessageW(int(hwnd), 0x0010, 0, 0)                     # WM_CLOSE: the app may ask to save, like clicking X

    def show(self, hwnd: int, state: str) -> None:
        code = {"minimize": 6, "maximize": 3, "restore": 9}[state]
        self._need().ShowWindow(int(hwnd), code)

    # ---- input ----
    def _send(self, items):
        import ctypes
        from ctypes import wintypes
        user32 = self._need()

        class KEYBDINPUT(ctypes.Structure):
            _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]

        class MOUSEINPUT(ctypes.Structure):
            _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                        ("dwExtraInfo", ctypes.c_size_t)]

        class UNION(ctypes.Union):
            _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT)]

        class INPUT(ctypes.Structure):
            _fields_ = [("type", wintypes.DWORD), ("u", UNION)]

        arr = (INPUT * len(items))()
        for i, (kind, a, b, flags) in enumerate(items):
            arr[i].type = 1 if kind == "k" else 0
            if kind == "k":
                arr[i].u.ki = KEYBDINPUT(a, b, flags, 0, 0)
            else:
                arr[i].u.mi = MOUSEINPUT(0, 0, 0, flags, 0, 0)
        sent = user32.SendInput(len(items), arr, ctypes.sizeof(INPUT))
        if sent != len(items):
            raise ToolError("ویندوز ورودی را نپذیرفت (شاید برنامه‌ی مقصد با دسترسی Administrator اجرا شده است).")

    def type_text(self, text: str) -> None:
        items = []
        for ch in text:
            if ch == "\n":
                items += [("k", 0x0D, 0, 0), ("k", 0x0D, 0, 2)]
            elif ch == "\t":
                items += [("k", 0x09, 0, 0), ("k", 0x09, 0, 2)]
            elif ch == "\r":
                continue
            else:
                data = ch.encode("utf-16-le")
                for i in range(0, len(data), 2):
                    unit = int.from_bytes(data[i:i + 2], "little")
                    items += [("k", 0, unit, 4), ("k", 0, unit, 4 | 2)]            # KEYEVENTF_UNICODE down / up
        self._send(items)

    def press(self, vks: list) -> None:
        self._send([("k", v, 0, 0) for v in vks] + [("k", v, 0, 2) for v in reversed(vks)])

    def click(self, x: int, y: int) -> None:
        user32 = self._need()
        user32.SetCursorPos(int(x), int(y))
        self._send([("m", 0, 0, 2), ("m", 0, 0, 4)])

    def window_rect(self, hwnd: int):
        import ctypes
        from ctypes import wintypes
        rect = wintypes.RECT()
        if not self._need().GetWindowRect(int(hwnd), ctypes.byref(rect)):
            raise ToolError("اندازه‌ی پنجره خوانده نشد.")
        return rect.left, rect.top, rect.right, rect.bottom

    # ---- clipboard ----
    def clipboard_get(self) -> str:
        import ctypes
        user32, k32 = self._need(), ctypes.windll.kernel32
        user32.GetClipboardData.restype = ctypes.c_void_p
        k32.GlobalLock.restype = ctypes.c_void_p
        k32.GlobalLock.argtypes = [ctypes.c_void_p]
        k32.GlobalUnlock.argtypes = [ctypes.c_void_p]
        if not user32.OpenClipboard(None):
            raise ToolError("کلیپ‌بورد در دسترس نیست (برنامه‌ی دیگری آن را باز کرده است).")
        try:
            handle = user32.GetClipboardData(13)                                    # CF_UNICODETEXT
            if not handle:
                return ""
            ptr = k32.GlobalLock(handle)
            try:
                return ctypes.wstring_at(ptr)
            finally:
                k32.GlobalUnlock(handle)
        finally:
            user32.CloseClipboard()

    def clipboard_set(self, text: str) -> None:
        import ctypes
        user32, k32 = self._need(), ctypes.windll.kernel32
        k32.GlobalAlloc.restype = ctypes.c_void_p
        k32.GlobalLock.restype = ctypes.c_void_p
        k32.GlobalLock.argtypes = [ctypes.c_void_p]
        k32.GlobalUnlock.argtypes = [ctypes.c_void_p]
        user32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
        data = (text + "\0").encode("utf-16-le")
        if not user32.OpenClipboard(None):
            raise ToolError("کلیپ‌بورد در دسترس نیست (برنامه‌ی دیگری آن را باز کرده است).")
        try:
            user32.EmptyClipboard()
            handle = k32.GlobalAlloc(0x0002, len(data))                             # GMEM_MOVEABLE
            ptr = k32.GlobalLock(handle)
            ctypes.memmove(ptr, data, len(data))
            k32.GlobalUnlock(handle)
            if not user32.SetClipboardData(13, handle):
                raise ToolError("نوشتن در کلیپ‌بورد ناموفق بود.")
        finally:
            user32.CloseClipboard()

    # ---- UI Automation (one fixed script; inputs travel as JSON in an environment variable) ----
    def uia(self, args: dict) -> dict:
        if not IS_WIN:
            raise ToolError("UI Automation فقط روی ویندوز ممکن است.")
        # the shared controlled runner: a FixedScript, inputs travel as JSON in the KIRA_UIA environment variable, no -ExecutionPolicy Bypass needed
        data = run_fixed(UIA_FIXED, env={"KIRA_UIA": json.dumps(args, ensure_ascii=False)}, timeout=UIA_TIMEOUT, api_name="UI Automation")
        if data.get("fatal"):
            raise ToolError("خواندن کنترل‌های پنجره ممکن نشد: " + redact_secrets(str(data.get("error") or ""))[:200])
        return data


# =============================================================================================== policy
class DesktopTools:
    def __init__(self, backend=None, own_pid: int | None = None, sleep=time.sleep):
        self.b = backend or Win32Backend()
        self.own_pid = own_pid if own_pid is not None else os.getpid()
        self._sleep = sleep

    # ---- window resolution ----
    @staticmethod
    def _stem(w: dict) -> str:
        return os.path.splitext(str(w.get("process") or "").lower())[0].replace(" ", "")

    def resolve(self, ref: str, wins: list | None = None) -> dict:
        wins = wins if wins is not None else self.b.windows()
        text = _fa(ref)
        if not text:
            raise ToolError("نام یا عنوان پنجره را بده (window_list را ببین).")
        m = re.fullmatch(r"hwnd:?\s*(\d+)", text)
        if m:
            found = [w for w in wins if w["hwnd"] == int(m.group(1))]
        else:
            stems = ALIASES.get(text)
            found = [w for w in wins if stems and self._stem(w) in stems]
            found = found or [w for w in wins if self._stem(w) == text.replace(" ", "")]
            found = found or [w for w in wins if text in _fa(w["title"])]
            found = found or [w for w in wins if len(text) >= 3 and text.replace(" ", "") in self._stem(w)]
        found = [w for w in found if w["pid"] != self.own_pid or m]
        if not found:
            raise ToolError(f"پنجره‌ای با «{ref}» پیدا نشد. window_list پنجره‌های باز را نشان می‌دهد.")
        if len(found) > 1:
            names = "؛ ".join(f"hwnd:{w['hwnd']} «{w['title'][:40]}» ({self._stem(w)})" for w in found[:5])
            raise ToolError(f"چند پنجره با «{ref}» هست؛ دقیق‌تر بگو یا با hwnd انتخاب کن: {names}")
        return found[0]

    def _guard_input(self, w: dict) -> None:
        """Windows that must never receive typing / keys / clicks."""
        stem = self._stem(w)
        if w["pid"] == self.own_pid:
            raise ToolError("این پنجره‌ی خود Kira است.", DENIED)
        if stem in BLOCKED_PROCESSES:
            raise ToolError(f"ورودی به «{stem}» فرستاده نمی‌شود (ترمینال، کنسول مدیریتی، اسکریپت یا برنامه‌ی رمز).", DENIED)
        title = w["title"].strip()
        if _fa(title) in RUN_DIALOG_TITLES or BLOCKED_TITLE_RX.search(title):
            raise ToolError(f"پنجره‌ی «{title[:40]}» مربوط به ورود/رمز/تأیید امنیتی یا اجرای فرمان است؛ ورودی نمی‌فرستم.", DENIED)

    def _focus(self, w: dict) -> None:
        if self.b.foreground() != w["hwnd"]:
            ok, note = self.b.activate(w["hwnd"])
            self._sleep(0.15)
            if not ok and self.b.foreground() != w["hwnd"]:
                raise ToolError(f"پنجره‌ی «{w['title'][:40]}» جلو نیامد؛ چیزی تایپ/کلیک نشد. {note}")

    def _still_target(self, w: dict) -> None:
        if self.b.foreground() != w["hwnd"] or not self.b.is_window(w["hwnd"]):
            raise ToolError("وسط کار پنجره‌ی فعال عوض شد؛ برای امنیت متوقف شدم.")

    # ---- windows ----
    def window_list(self, a: dict) -> str:
        wins = [w for w in self.b.windows() if w["pid"] != self.own_pid]
        fg = self.b.foreground()
        if not wins:
            return "پنجره‌ی بازی دیده نشد."
        lines = [f"{len(wins)} پنجره‌ی باز (بالاترین اول):"]
        for w in wins[:25]:
            state = "فعال" if w["hwnd"] == fg else "کوچک‌شده" if w.get("minimized") else "بزرگ" if w.get("maximized") else ""
            lines.append(f"- hwnd:{w['hwnd']} «{w['title'][:60]}» ({self._stem(w)})" + (f" [{state}]" if state else ""))
        return "\n".join(lines)

    def window_active(self, a: dict) -> str:
        fg = self.b.foreground()
        w = next((x for x in self.b.windows() if x["hwnd"] == fg), None)
        return f"پنجره‌ی فعال: «{w['title'][:60]}» ({self._stem(w)})" if w else "پنجره‌ی فعال شناخته نشد (یا دسکتاپ/خود Kira است)."

    def window_focus(self, a: dict) -> str:
        w = self.resolve(a["window"])
        ok, note = self.b.activate(w["hwnd"])
        self._sleep(0.15)
        if self.b.foreground() != w["hwnd"]:
            raise ToolError(f"پنجره‌ی «{w['title'][:40]}» جلو نیامد. {note}")
        return f"پنجره‌ی «{w['title'][:60]}» الان فعال است."

    def window_close(self, a: dict) -> str:
        w = self.resolve(a["window"])
        if w["pid"] == self.own_pid or "user account control" in w["title"].lower():
            raise ToolError("این پنجره بسته نمی‌شود.", DENIED)
        self.b.close(w["hwnd"])
        for _ in range(10):
            self._sleep(0.25)
            if not self.b.is_window(w["hwnd"]) or not any(x["hwnd"] == w["hwnd"] for x in self.b.windows()):
                return f"پنجره‌ی «{w['title'][:60]}» بسته شد."
        return (f"درخواست بستن «{w['title'][:60]}» فرستاده شد ولی پنجره هنوز باز است (احتمالاً می‌پرسد ذخیره شود یا نه). "
                "به کاربر بگو خودش پاسخ بدهد؛ بسته‌شدن را اعلام نکن.")

    def window_set_state(self, a: dict) -> str:
        w = self.resolve(a["window"])
        self.b.show(w["hwnd"], a["state"])
        self._sleep(0.3)
        now = next((x for x in self.b.windows() if x["hwnd"] == w["hwnd"]), None)
        got = ("minimize" if now and now.get("minimized") else "maximize" if now and now.get("maximized") else "restore") if now else "minimize"
        if got != a["state"]:
            raise ToolError(f"وضعیت پنجره عوض نشد (الان: {got}).")
        return f"پنجره‌ی «{w['title'][:60]}» الان {({'minimize': 'کوچک‌شده', 'maximize': 'بزرگ‌شده', 'restore': 'در حالت عادی'})[a['state']]} است."

    # ---- keyboard ----
    def type_text(self, a: dict) -> str:
        text = str(a["text"])
        if not text or len(text) > TYPE_MAX:
            raise ToolError(f"متن خالی است یا بیش از {TYPE_MAX} نویسه است.")
        if redact_secrets(text) != text:
            raise ToolError("متن شبیه کلید/رمز است؛ تایپ نمی‌شود.", DENIED)
        w = self.resolve(a["window"])
        self._guard_input(w)
        self._focus(w)
        typed = 0
        for i in range(0, len(text), TYPE_CHUNK):
            self._still_target(w)                                           # re-checked before EVERY chunk
            self.b.type_text(text[i:i + TYPE_CHUNK])
            typed += len(text[i:i + TYPE_CHUNK])
        return (f"{typed} نویسه در پنجره‌ی «{w['title'][:50]}» تایپ شد. (محتوای داخل برنامه از اینجا قابل بررسی نیست؛ "
                "اگر لازم است از کاربر بخواه نگاه کند.)")

    def press_keys(self, a: dict) -> str:
        vks, label = parse_combo(a["keys"])
        w = self.resolve(a["window"])
        self._guard_input(w)
        self._focus(w)
        self._still_target(w)
        self.b.press(vks)
        return f"کلید {label} در «{w['title'][:50]}» زده شد. (اثر آن قابل بررسی خودکار نیست.)"

    # ---- clipboard ----
    def clipboard_set(self, a: dict) -> str:
        text = str(a["text"])
        if not text or len(text) > TYPE_MAX * 5 or redact_secrets(text) != text:
            raise ToolError("متن خالی/خیلی بلند است یا شبیه کلید و رمز است.", DENIED)
        self.b.clipboard_set(text)
        if self.b.clipboard_get() != text:
            raise ToolError("متن در کلیپ‌بورد قرار نگرفت.")
        return f"{len(text)} نویسه در کلیپ‌بورد گذاشته شد."

    def confirm_clipboard_get(self, a: dict) -> str:
        return "محتوای متنی فعلی کلیپ‌بورد خوانده می‌شود و در اختیار Kira (و مدل) قرار می‌گیرد؛ ممکن است چیز خصوصی در آن باشد."

    def clipboard_get(self, a: dict) -> str:
        text = redact_secrets(self.b.clipboard_get())
        return "[کلیپ‌بورد خالی است یا متن نیست]" if not text else f"محتوای کلیپ‌بورد ({len(text)} نویسه):\n{text[:3000]}"

    # ---- mouse / controls ----
    def ui_list(self, a: dict) -> str:
        w = self.resolve(a["window"])
        res = self.b.uia({"mode": "list", "hwnd": w["hwnd"], "limit": UIA_MAX_CONTROLS})
        items = res.get("items") or []
        if isinstance(items, dict):
            items = [items]
        lines = [f"کنترل‌های «{w['title'][:50]}» ({len(items)}):"]
        for it in items:
            flag = " [فیلد رمز: دست نمی‌زنم]" if it.get("password") else "" if it.get("enabled", True) else " [غیرفعال]"
            lines.append(f"- {it.get('type')}: «{str(it.get('name'))[:50]}»{flag}")
        return "\n".join(lines)

    def _check_control(self, a: dict, *, dangerous_ok: bool) -> dict:
        w = self.resolve(a["window"])
        self._guard_input(w)
        name = str(a["control"]).strip()
        if not name:
            raise ToolError("نام کنترل خالی است (ui_list_controls را ببین).")
        if DANGEROUS_CONTROL_RX.search(name) is not None and not dangerous_ok:
            raise ToolError(f"«{name}» کنترل حساس/برگشت‌ناپذیر به نظر می‌رسد (حذف، ارسال، پرداخت، ورود، نصب ...). فقط با ابزار تأییدی ui_click_confirmed و تأیید صریح کاربر.", DENIED)
        return w

    def _uia_action(self, w: dict, mode: str, a: dict, extra: dict | None = None) -> dict:
        self._focus(w)
        res = self.b.uia({"mode": mode, "hwnd": w["hwnd"], "name": str(a["control"]).strip(), "type": a.get("type") or "", **(extra or {})})
        err = res.get("error")
        if err == "not_found":
            raise ToolError(f"کنترل «{a['control']}» در این پنجره پیدا نشد (ui_list_controls را ببین).")
        if err == "ambiguous":
            names = "؛ ".join(f"{i.get('type')}:«{str(i.get('name'))[:30]}»" for i in (res.get("items") or []))
            raise ToolError(f"چند کنترل با این نام هست: {names}. نام دقیق‌تر یا type بده.")
        if err == "password":
            raise ToolError("این فیلد رمز است؛ به آن دست نمی‌زنم.", DENIED)
        if err == "disabled":
            raise ToolError("این کنترل غیرفعال است.")
        if err in ("no_pattern", "no_value_pattern"):
            raise ToolError("این کنترل از کلیک/نوشتن مستقیم پشتیبانی نمی‌کند.")
        if not res.get("ok"):
            raise ToolError("عملیات روی کنترل انجام نشد.")
        return res

    def ui_click(self, a: dict, *, confirmed_tool: bool = False) -> str:
        w = self._check_control(a, dangerous_ok=confirmed_tool)
        res = self._uia_action(w, "invoke", a)
        return f"روی «{res['target']['name'][:50]}» ({res.get('how')}) در «{w['title'][:40]}» اجرا شد. (نتیجه‌ی داخل برنامه قابل بررسی خودکار نیست.)"

    def ui_click_confirmed(self, a: dict) -> str:
        return self.ui_click(a, confirmed_tool=True)

    def confirm_ui_click(self, a: dict) -> str:
        return f"در پنجره‌ی «{a['window']}» روی کنترل «{a['control']}» کلیک می‌شود. این کنترل ممکن است چیزی را حذف/ارسال/نصب کند یا وارد حسابی شود."

    def ui_set_text(self, a: dict) -> str:
        text = str(a["text"])
        if len(text) > TYPE_MAX or redact_secrets(text) != text:
            raise ToolError("متن خیلی بلند است یا شبیه کلید/رمز است.", DENIED)
        w = self._check_control(a, dangerous_ok=True)
        res = self._uia_action(w, "settext", a, {"text": text})
        if str(res.get("value_after", "")) != text:
            raise ToolError("بعد از نوشتن، مقدار فیلد با متن مورد نظر برابر نبود.")
        return f"فیلد «{res['target']['name'][:40]}» در «{w['title'][:40]}» پر شد و مقدار آن دوباره خوانده و تأیید شد."

    def mouse_click(self, a: dict) -> str:
        w = self.resolve(a["window"])
        self._guard_input(w)
        l, t, r, b = self.b.window_rect(w["hwnd"])
        x, y = int(a["x"]), int(a["y"])
        if not (0 <= x < r - l and 0 <= y < b - t):
            raise ToolError(f"مختصات باید داخل پنجره باشد (عرض {r - l}، ارتفاع {b - t}؛ نسبت به گوشه‌ی بالا-چپ پنجره).")
        self._focus(w)
        self._still_target(w)
        self.b.click(l + x, t + y)
        return f"کلیک در نقطه‌ی ({x}, {y}) پنجره‌ی «{w['title'][:40]}» انجام شد. (اثر آن قابل بررسی خودکار نیست.)"

    def confirm_mouse_click(self, a: dict) -> str:
        return f"در پنجره‌ی «{a['window']}» روی نقطه‌ی ({a['x']}, {a['y']}) کلیک می‌شود (نقطه‌ی خام، بدون دانستن اینکه چه چیزی آنجاست)."


# =============================================================================================== declarations
_V = lambda *w: re.compile("|".join(w), re.I)       # noqa: E731
FOCUS_RX = _V(r"فعال", r"جلو", r"بیار", r"برو", r"سوییچ", r"سویچ", r"focus", r"switch", r"activate", r"bring", r"show")
CLOSE_RX = _V(r"ببند", r"بسته", r"ببندش", r"کلوز", r"close", r"quit", r"exit")
STATE_RX = _V(r"کوچک", r"مینی", r"بزرگ", r"ماکسی", r"تمام\s*صفحه", r"برگردون", r"minimi", r"maximi", r"restore", r"full\s*screen")
TYPE_RX = _V(r"تایپ", r"بنویس", r"بنویسش", r"بزن", r"وارد\s*کن", r"پر\s*کن", r"paste", r"type", r"write", r"enter", r"fill")
KEYS_RX = _V(r"کلید", r"بزن", r"فشار", r"ذخیره", r"کپی", r"پیست", r"انتخاب", r"ctrl", r"کنترل", r"alt", r"win", r"windows", r"ویندوز", r"press", r"hit", r"save", r"copy", r"paste", r"select", r"undo", r"enter", r"tab")
CLICK_RX = _V(r"کلیک", r"بزن", r"فشار", r"انتخاب", r"click", r"press", r"select", r"choose", r"tap", r"باز", r"open", r"تیک", r"check")
CLIP_RX = _V(r"کلیپ\s*بورد", r"clipboard", r"کپی", r"copy")


class DesktopModule(WinModule):
    domain = "desktop"

    def __init__(self, tools: DesktopTools | None = None):
        self.t = tools or DesktopTools()

    def capabilities(self) -> list[Capability]:
        t, cat = self.t, ("desktop",)
        win = Param("window", "string", "window as the user said it (title part, app name, 'browser') or hwnd:NUMBER from window_list", True)
        ctl = Param("control", "string", "control name exactly as shown by ui_list_controls", True)
        ctype = Param("type", "string", "optional control type: Button, Edit, MenuItem, CheckBox, ...")
        caps = [
            Capability("window_list", "desktop", "list the open windows (title, app, state) with hwnd ids (changes nothing)", t.window_list, READ, (), cat,
                       external=True),
            Capability("window_active", "desktop", "which window is in front right now (changes nothing)", t.window_active, READ, (), cat,
                       external=True),
            Capability("window_focus", "desktop", "bring ONE window to the front; ONLY when the user asks to go to / show / switch to it", t.window_focus, ACTION, (win,), cat,
                       intent_rx=FOCUS_RX, verifies_result=True, changes_system=True, external=True),
            Capability("window_close", "desktop", "close ONE window politely (like the X button; the app may ask to save). ONLY when the user explicitly asks to close it",
                       t.window_close, ACTION, (win,), cat, intent_rx=CLOSE_RX, memo=lambda a, x: f"window_close → {a.get('window')}", verifies_result=True, changes_system=True, external=True),
            Capability("window_set_state", "desktop", "minimize, maximize or restore ONE window, then re-check. ONLY on explicit request",
                       t.window_set_state, ACTION, (win, Param("state", "string", "minimize | maximize | restore", True, None, ("minimize", "maximize", "restore"))), cat,
                       intent_rx=STATE_RX, verifies_result=True, changes_system=True, external=True),
            Capability("type_text", "desktop", "type text into a window (the window is brought to the front and verified before and during typing; never into terminals, "
                       "password or security windows). ONLY when the user asks to type/write something",
                       t.type_text, ACTION, (win, Param("text", "string", "the exact text to type (max 2000 characters)", True)), cat,
                       intent_rx=TYPE_RX, memo=lambda a, x: f"type_text → {a.get('window')}", changes_system=True, external=True),
            Capability("press_keys", "desktop", "press an allow-listed Windows virtual key or shortcut in a window (Alt+Tab, Win+E, Win+D, Win+Tab, Win+Ctrl+Arrow, Ctrl/Shift/Alt shortcuts, F1-F24, navigation and punctuation); dangerous system shortcuts such as Win+R, Win+L and Alt+F4 remain blocked. ONLY on explicit request",
                       t.press_keys, ACTION, (win, Param("keys", "string", "e.g. alt+tab, win+e, win+ctrl+left, ctrl+s, ctrl+shift+left", True)), cat,
                       intent_rx=KEYS_RX, memo=lambda a, x: f"press_keys → {a.get('keys')}", changes_system=True, external=True),
            Capability("clipboard_set", "desktop", "put text on the clipboard (so the user can paste it). ONLY when the user asks", t.clipboard_set, ACTION,
                       (Param("text", "string", "text to copy", True),), cat, intent_rx=CLIP_RX, verifies_result=True, changes_system=True),
            Capability("clipboard_get", "desktop", "read the text currently on the clipboard (it may be private, so the user confirms first)", t.clipboard_get, SENSITIVE, (), cat,
                       confirm_summary=t.confirm_clipboard_get, external=True),
            Capability("ui_list_controls", "desktop", "list the buttons, menus, fields and checkboxes of a window by name (UI Automation; changes nothing)",
                       t.ui_list, READ, (win,), cat, external=True),
            Capability("ui_click", "desktop", "click / invoke ONE named control of a window (button, menu item, checkbox, tab ...). Controls that look destructive, a login, a "
                       "payment or an install are refused here (use ui_click_confirmed). ONLY on explicit request",
                       t.ui_click, ACTION, (win, ctl, ctype), cat, intent_rx=CLICK_RX, memo=lambda a, x: f"ui_click → {a.get('control')}", changes_system=True, external=True),
            Capability("ui_click_confirmed", "desktop", "like ui_click but for destructive / irreversible / login / payment / install controls; the user must confirm first",
                       t.ui_click_confirmed, SENSITIVE, (win, ctl, ctype), cat, confirm_summary=t.confirm_ui_click, changes_system=True, external=True),
            Capability("ui_set_text", "desktop", "write text into ONE named text field (never a password field), then read the value back. ONLY on explicit request",
                       t.ui_set_text, ACTION, (win, ctl, Param("text", "string", "text to put in the field", True)), cat, intent_rx=TYPE_RX,
                       memo=lambda a, x: f"ui_set_text → {a.get('control')}", verifies_result=True, changes_system=True, external=True),
            Capability("mouse_click", "desktop", "click a raw point inside a window (x, y from its top-left corner) when no named control exists; the user confirms first",
                       t.mouse_click, SENSITIVE, (win, Param("x", "integer", "pixels from the left edge of the window", True), Param("y", "integer", "pixels from the top edge", True)),
                       cat, confirm_summary=t.confirm_mouse_click, changes_system=True, external=True),
        ]
        for c in caps:                                          # the backend that really does the work (shown in the access table / journal)
            c.backend = "uia" if c.name.startswith("ui_") else "sendinput" if c.name in ("type_text", "press_keys", "mouse_click") else "win32"
        return caps
