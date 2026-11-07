"""Computer Awareness: read-only facts about this Windows PC, taken live from the system.

Every function returns short Persian text for the model. psutil is used when it is installed; every reader has a plain
ctypes / winreg / standard-library fallback, so a missing package only reduces detail and never breaks Kira.
Nothing here changes anything on the computer, and no command line comes from the model: the few external programs that are
run (nvidia-smi, tasklist) always have fixed arguments.
"""
from __future__ import annotations

import os
import platform
import shutil
import socket
import subprocess
import sys
import time
from datetime import datetime


IS_WIN = sys.platform == "win32"
NO_WINDOW = 0x08000000 if IS_WIN else 0                       # CREATE_NO_WINDOW: no console flash when a helper program runs

try:                                                          # optional: more detail and speed, never required
    import psutil
except Exception:                                             # noqa: BLE001
    psutil = None

PERSIAN_MONTHS = ("فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور", "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند")
PERSIAN_WEEKDAYS = ("دوشنبه", "سه‌شنبه", "چهارشنبه", "پنجشنبه", "جمعه", "شنبه", "یکشنبه")      # datetime.weekday(): Monday = 0


def gb(n) -> str:
    return f"{n / 1024 ** 3:.1f} GB"


def _run(args, timeout=4) -> str:
    """Run one FIXED helper program (never a model-supplied command) and return its stdout ('' on any failure)."""
    try:
        done = subprocess.run(args, capture_output=True, text=True, timeout=timeout, creationflags=NO_WINDOW,
                              encoding="utf-8", errors="replace", shell=False)
        return done.stdout or ""
    except Exception:                                         # noqa: BLE001
        return ""


# ------------------------------------------------------------------ date and time
def gregorian_to_jalali(gy: int, gm: int, gd: int):
    g_d_m = (0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334)
    if gy > 1600:
        jy, gy = 979, gy - 1600
    else:
        jy, gy = 0, gy - 621
    gy2 = gy + 1 if gm > 2 else gy
    days = 365 * gy + (gy2 + 3) // 4 - (gy2 + 99) // 100 + (gy2 + 399) // 400 - 80 + gd + g_d_m[gm - 1]
    jy += 33 * (days // 12053)
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    if days < 186:
        jm, jd = 1 + days // 31, 1 + days % 31
    else:
        jm, jd = 7 + (days - 186) // 30, 1 + (days - 186) % 30
    return jy, jm, jd


def datetime_text() -> str:
    now = datetime.now().astimezone()
    off = now.utcoffset()
    minutes = int(off.total_seconds() // 60) if off else 0
    sign = "+" if minutes >= 0 else "-"
    offset = f"UTC{sign}{abs(minutes) // 60:02d}:{abs(minutes) % 60:02d}"
    jy, jm, jd = gregorian_to_jalali(now.year, now.month, now.day)
    dst = " (ساعت تابستانی فعال)" if now.dst() else ""
    return "\n".join([
        f"ساعت سیستم: {now:%H:%M:%S}",
        f"تاریخ میلادی: {now:%Y-%m-%d} ({now:%A})",
        f"تاریخ شمسی: {PERSIAN_WEEKDAYS[now.weekday()]} {jd} {PERSIAN_MONTHS[jm - 1]} {jy}",
        f"منطقه‌ی زمانی: {now.tzname()} · {offset}{dst}",
    ])


# ------------------------------------------------------------------ system language / windows version
def _locale_name(ui: bool) -> str:
    if IS_WIN:
        try:
            import ctypes
            buf = ctypes.create_unicode_buffer(85)
            k32 = ctypes.windll.kernel32
            if ui:
                lcid = k32.GetUserDefaultUILanguage()
                if k32.LCIDToLocaleName(lcid, buf, 85, 0):
                    return buf.value
            elif k32.GetUserDefaultLocaleName(buf, 85):
                return buf.value
        except Exception:                                     # noqa: BLE001
            pass
    try:
        import locale
        return locale.getlocale()[0] or ""
    except Exception:                                         # noqa: BLE001
        return ""


def windows_text() -> str:
    if not IS_WIN:
        return f"سیستم‌عامل: {platform.platform()}"
    build, product, display, ubr = 0, "", "", ""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion") as key:
            def val(name):
                try:
                    return winreg.QueryValueEx(key, name)[0]
                except OSError:
                    return ""
            product, display, ubr = str(val("ProductName")), str(val("DisplayVersion") or val("ReleaseId")), str(val("UBR"))
            build = int(str(val("CurrentBuild") or val("CurrentBuildNumber") or 0))
    except Exception:                                         # noqa: BLE001
        build = getattr(sys.getwindowsversion(), "build", 0) if hasattr(sys, "getwindowsversion") else 0
    name = "Windows 11" if build >= 22000 else (product or "Windows")
    if build >= 22000 and product and "Windows 10" in product:
        product = product.replace("Windows 10", "Windows 11")        # the registry keeps the old "Windows 10" name on Windows 11
    edition = (product or name).replace("Windows 11", "").replace("Windows 10", "").strip()
    line = f"ویندوز: {name}" + (f" {edition}" if edition and edition not in name else "")
    extra = ", ".join(x for x in (f"نسخه {display}" if display else "", f"Build {build}" + (f".{ubr}" if ubr else "") if build else "",
                                  platform.machine()) if x)
    return line + (f" ({extra})" if extra else "")


# ------------------------------------------------------------------ cpu / gpu / ram
def cpu_model() -> str:
    if IS_WIN:
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as key:
                return " ".join(str(winreg.QueryValueEx(key, "ProcessorNameString")[0]).split())
        except Exception:                                     # noqa: BLE001
            pass
    return platform.processor() or "نامشخص"


def cpu_counts():
    logical = os.cpu_count() or 0
    physical = None
    if psutil is not None:
        try:
            physical = psutil.cpu_count(logical=False)
        except Exception:                                     # noqa: BLE001
            physical = None
    return physical, logical


def _system_times():
    import ctypes
    from ctypes import wintypes

    class FILETIME(ctypes.Structure):
        _fields_ = [("lo", wintypes.DWORD), ("hi", wintypes.DWORD)]

    idle, kern, user = FILETIME(), FILETIME(), FILETIME()
    if not ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kern), ctypes.byref(user)):
        raise OSError("GetSystemTimes failed")
    val = lambda f: (f.hi << 32) | f.lo                       # noqa: E731
    return val(idle), val(kern), val(user)


def cpu_percent():
    """Overall CPU use in % measured over ~0.5 s (None if it cannot be read)."""
    if psutil is not None:
        try:
            return float(psutil.cpu_percent(interval=0.5))
        except Exception:                                     # noqa: BLE001
            pass
    if IS_WIN:
        try:
            i1, k1, u1 = _system_times()
            time.sleep(0.5)
            i2, k2, u2 = _system_times()
            total = (k2 - k1) + (u2 - u1)                     # kernel time already includes idle time
            return max(0.0, min(100.0, 100.0 * (total - (i2 - i1)) / total)) if total else None
        except Exception:                                     # noqa: BLE001
            return None
    return None


def memory_status():
    """(total, available) bytes, or None."""
    if psutil is not None:
        try:
            vm = psutil.virtual_memory()
            return int(vm.total), int(vm.available)
        except Exception:                                     # noqa: BLE001
            pass
    if IS_WIN:
        try:
            import ctypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong), ("ullTotalPhys", ctypes.c_ulonglong),
                            ("ullAvailPhys", ctypes.c_ulonglong), ("ullTotalPageFile", ctypes.c_ulonglong),
                            ("ullAvailPageFile", ctypes.c_ulonglong), ("ullTotalVirtual", ctypes.c_ulonglong),
                            ("ullAvailVirtual", ctypes.c_ulonglong), ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

            st = MEMORYSTATUSEX()
            st.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st)):
                return int(st.ullTotalPhys), int(st.ullAvailPhys)
        except Exception:                                     # noqa: BLE001
            pass
    return None


def gpu_names() -> list[str]:
    names = []
    if IS_WIN:
        try:
            import winreg
            base = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base) as root:
                for i in range(32):
                    try:
                        sub = winreg.EnumKey(root, i)
                    except OSError:
                        break
                    if not sub.isdigit():
                        continue
                    try:
                        with winreg.OpenKey(root, sub) as key:
                            desc = str(winreg.QueryValueEx(key, "DriverDesc")[0]).strip()
                            if desc and desc not in names and "basic display" not in desc.lower() and "remote" not in desc.lower():
                                names.append(desc)
                    except OSError:
                        continue
        except Exception:                                     # noqa: BLE001
            pass
    return names


def nvidia_stats() -> list[dict]:
    exe = shutil.which("nvidia-smi")
    if not exe:
        return []
    out = _run([exe, "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu", "--format=csv,noheader,nounits"])
    rows = []
    for line in out.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 4:
            def num(x):
                try:
                    return float(x)
                except ValueError:
                    return None
            rows.append({"name": parts[0], "util": num(parts[1]), "mem_used": num(parts[2]), "mem_total": num(parts[3]),
                         "temp": num(parts[4]) if len(parts) > 4 else None})
    return rows


# ------------------------------------------------------------------ disks / battery
def disks_text() -> str:
    drives = []
    if IS_WIN:
        try:
            import ctypes
            mask = ctypes.windll.kernel32.GetLogicalDrives()
            for i in range(26):
                if mask & (1 << i):
                    root = f"{chr(65 + i)}:\\"
                    kind = ctypes.windll.kernel32.GetDriveTypeW(root)
                    if kind in (2, 3):                       # removable / fixed only: a network drive could hang
                        drives.append((root, "قابل‌حمل" if kind == 2 else "ثابت"))
        except Exception:                                     # noqa: BLE001
            pass
    if not drives:
        drives = [(os.path.abspath(os.sep), "ثابت")]
    lines = []
    for root, kind in drives:
        try:
            u = shutil.disk_usage(root)
        except OSError:
            lines.append(f"{root} ({kind}): آماده نیست یا خوانده نشد")
            continue
        pct = 100 * u.used / u.total if u.total else 0
        lines.append(f"{root} ({kind}): کل {gb(u.total)} · آزاد {gb(u.free)} · استفاده‌شده {pct:.0f}%")
    return "\n".join(lines)


def battery_text() -> str:
    if IS_WIN:
        try:
            import ctypes

            class SYSTEM_POWER_STATUS(ctypes.Structure):
                _fields_ = [("ACLineStatus", ctypes.c_ubyte), ("BatteryFlag", ctypes.c_ubyte), ("BatteryLifePercent", ctypes.c_ubyte),
                            ("SystemStatusFlag", ctypes.c_ubyte), ("BatteryLifeTime", ctypes.c_ulong), ("BatteryFullLifeTime", ctypes.c_ulong)]

            st = SYSTEM_POWER_STATUS()
            if ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(st)):
                if st.BatteryFlag == 128 or st.BatteryFlag == 255 and st.BatteryLifePercent == 255:
                    return "باتری: این سیستم باتری ندارد (یا خوانده نشد)."
                pct = "نامشخص" if st.BatteryLifePercent == 255 else f"{st.BatteryLifePercent}%"
                plugged = {0: "به برق وصل نیست", 1: "به برق وصل است"}.get(st.ACLineStatus, "وضعیت شارژر نامشخص")
                charging = " · در حال شارژ" if st.BatteryFlag & 8 else ""
                left = ""
                if st.BatteryLifeTime != 0xFFFFFFFF and not st.ACLineStatus:
                    left = f" · حدود {st.BatteryLifeTime // 3600} ساعت و {(st.BatteryLifeTime % 3600) // 60} دقیقه باقی‌مانده"
                return f"باتری: {pct} · {plugged}{charging}{left}"
        except Exception:                                     # noqa: BLE001
            pass
    if psutil is not None:
        try:
            b = psutil.sensors_battery()
            if b is None:
                return "باتری: این سیستم باتری ندارد."
            return f"باتری: {b.percent:.0f}% · {'به برق وصل است' if b.power_plugged else 'به برق وصل نیست'}"
        except Exception:                                     # noqa: BLE001
            pass
    return "باتری: خوانده نشد."


# ------------------------------------------------------------------ composed texts
def system_info_text() -> str:
    physical, logical = cpu_counts()
    cores = f" · {physical} هسته‌ی فیزیکی / {logical} منطقی" if physical else (f" · {logical} هسته‌ی منطقی" if logical else "")
    lines = [windows_text(), f"نام کامپیوتر: {socket.gethostname()}",
             f"زبان نمایشی ویندوز: {_locale_name(True) or 'نامشخص'} · تنظیم منطقه‌ای: {_locale_name(False) or 'نامشخص'}",
             f"CPU: {cpu_model()}{cores}"]
    mem = memory_status()
    if mem:
        lines.append(f"RAM: کل {gb(mem[0])}")
    gpus = nvidia_stats()
    names = [g["name"] for g in gpus] or gpu_names()
    lines.append("GPU: " + (" ، ".join(names) if names else "تشخیص داده نشد"))
    lines.append(f"Python برنامه: {platform.python_version()}")
    return "\n".join(lines)


def usage_text(part: str = "all") -> str:
    part = (part or "all").lower()
    lines = []
    if part in ("all", "cpu"):
        pct = cpu_percent()
        lines.append(f"CPU: {pct:.0f}% در حال استفاده" if pct is not None else "CPU: میزان استفاده خوانده نشد.")
    if part in ("all", "ram"):
        mem = memory_status()
        if mem:
            total, avail = mem
            used = total - avail
            lines.append(f"RAM: {gb(used)} از {gb(total)} استفاده شده ({100 * used / total:.0f}%) · آزاد {gb(avail)}")
        else:
            lines.append("RAM: خوانده نشد.")
    if part in ("all", "gpu"):
        gpus = nvidia_stats()
        if gpus:
            for g in gpus:
                bits = [g["name"]]
                if g["util"] is not None:
                    bits.append(f"{g['util']:.0f}% استفاده")
                if g["mem_used"] is not None and g["mem_total"]:
                    bits.append(f"VRAM {g['mem_used'] / 1024:.1f} از {g['mem_total'] / 1024:.1f} GB")
                if g["temp"] is not None:
                    bits.append(f"{g['temp']:.0f}°C")
                lines.append("GPU: " + " · ".join(bits))
        else:
            names = gpu_names()
            lines.append("GPU: " + (f"{' ، '.join(names)} — میزان استفاده قابل‌خواندن نیست (فقط برای کارت‌های NVIDIA با nvidia-smi ممکن است)."
                                    if names else "تشخیص داده نشد."))
    if part in ("all", "battery"):
        lines.append(battery_text())
    return "\n".join(lines)


# ------------------------------------------------------------------ windows / processes
def _process_name(pid: int) -> str:
    if psutil is not None:
        try:
            return psutil.Process(pid).name()
        except Exception:                                     # noqa: BLE001
            pass
    if IS_WIN:
        try:
            import ctypes
            from ctypes import wintypes
            k32 = ctypes.windll.kernel32
            k32.OpenProcess.restype = wintypes.HANDLE
            h = k32.OpenProcess(0x1000, False, pid)           # PROCESS_QUERY_LIMITED_INFORMATION
            if not h:
                return ""
            try:
                buf = ctypes.create_unicode_buffer(520)
                size = wintypes.DWORD(520)
                if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                    return os.path.basename(buf.value)
            finally:
                k32.CloseHandle(h)
        except Exception:                                     # noqa: BLE001
            pass
    return ""


def visible_windows() -> list[dict]:
    """Visible top-level windows in z-order (topmost first): [{'title', 'pid', 'process'}]."""
    if not IS_WIN:
        return []
    import ctypes
    from ctypes import wintypes
    user32, dwm = ctypes.windll.user32, ctypes.windll.dwmapi
    found = []
    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def cb(hwnd, _):
        try:
            if not user32.IsWindowVisible(hwnd):
                return True
            n = user32.GetWindowTextLengthW(hwnd)
            if n <= 0:
                return True
            if user32.GetWindowLongW(hwnd, -20) & 0x80:      # GWL_EXSTYLE & WS_EX_TOOLWINDOW
                return True
            cloaked = ctypes.c_int(0)
            if dwm.DwmGetWindowAttribute(hwnd, 14, ctypes.byref(cloaked), ctypes.sizeof(cloaked)) == 0 and cloaked.value:
                return True                                    # hidden UWP shells / other virtual desktops
            buf = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(hwnd, buf, n + 1)
            title = buf.value.strip()
            if not title or title in ("Program Manager", "Default IME", "MSCTFIME UI"):
                return True
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            found.append({"title": title, "pid": int(pid.value), "hwnd": int(hwnd or 0)})
        except Exception:                                      # noqa: BLE001
            pass
        return True

    user32.EnumWindows(WNDENUMPROC(cb), 0)
    cache = {}
    for w in found:
        if w["pid"] not in cache:
            cache[w["pid"]] = _process_name(w["pid"])
        w["process"] = cache[w["pid"]]
    return found


def activate_window(hwnd: int):
    """Restore a minimized window and bring it to the front. Returns (ok, note) - ok only if Windows really made it the foreground window."""
    if not IS_WIN:
        return False, "فعال‌سازی پنجره فقط روی ویندوز ممکن است."
    import ctypes
    user32, k32 = ctypes.windll.user32, ctypes.windll.kernel32
    hwnd = int(hwnd)
    if not user32.IsWindow(hwnd):
        return False, "پنجره دیگر وجود ندارد."
    was_min = bool(user32.IsIconic(hwnd))
    if was_min:
        user32.ShowWindow(hwnd, 9)                                 # SW_RESTORE
    else:
        user32.ShowWindow(hwnd, 5)                                 # SW_SHOW (keeps maximized state)
    try:                                                           # Windows only lets the foreground thread change focus: attach to it briefly
        fg = user32.GetForegroundWindow()
        cur_thread = k32.GetCurrentThreadId()
        fg_thread = user32.GetWindowThreadProcessId(fg, None) if fg else 0
        target_thread = user32.GetWindowThreadProcessId(hwnd, None)
        attached = []
        for t in {fg_thread, target_thread}:
            if t and t != cur_thread and user32.AttachThreadInput(cur_thread, t, True):
                attached.append(t)
        user32.keybd_event(0x12, 0, 0, 0)                          # a tap on ALT releases the foreground lock
        user32.keybd_event(0x12, 0, 2, 0)
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
        for t in attached:
            user32.AttachThreadInput(cur_thread, t, False)
    except Exception:                                              # noqa: BLE001
        pass
    for _ in range(6):
        if user32.GetForegroundWindow() == hwnd and not user32.IsIconic(hwnd):
            return True, ("از حالت Minimize بیرون آمد و جلو آورده شد." if was_min else "به جلو آورده شد.")
        time.sleep(0.1)
    if not user32.IsIconic(hwnd):
        return False, ("پنجره Restore شد ولی ویندوز اجازه‌ی گرفتن فوکوس را نداد (ممکن است زیر پنجره‌های دیگر یا در نوار وظیفه چشمک بزند)."
                       if was_min else "ویندوز اجازه‌ی گرفتن فوکوس را نداد؛ ممکن است پشت پنجره‌های دیگر مانده باشد.")
    return False, "پنجره هنوز Minimize است."


def running_apps_text(include_background: bool = False, limit: int = 25) -> str:
    wins = [w for w in visible_windows() if w["pid"] != os.getpid()]
    lines = []
    if wins:
        lines.append(f"برنامه‌هایی که الان پنجره‌ی باز دارند ({len(wins)}):")
        for w in wins[:limit]:
            lines.append(f"- {w['process'] or '؟'} — «{w['title'][:80]}»")
    else:
        lines.append("پنجره‌ی بازی تشخیص داده نشد." if IS_WIN else "خواندن پنجره‌ها فقط روی ویندوز ممکن است.")
    if include_background:
        lines.append("")
        lines.append(processes_text(limit=15))
    return "\n".join(lines)


def processes_text(limit: int = 15) -> str:
    groups: dict[str, list] = {}
    if psutil is not None:
        try:
            for p in psutil.process_iter(["name", "memory_info"]):
                mi = p.info.get("memory_info")
                g = groups.setdefault(p.info.get("name") or "؟", [0, 0])
                g[0] += 1
                g[1] += mi.rss if mi else 0
        except Exception:                                     # noqa: BLE001
            groups = {}
    if not groups and IS_WIN:
        import csv
        import io
        out = _run(["tasklist", "/FO", "CSV", "/NH"], timeout=8)
        for row in csv.reader(io.StringIO(out)):
            if len(row) >= 5:
                mem = "".join(ch for ch in row[4] if ch.isdigit())
                g = groups.setdefault(row[0], [0, 0])
                g[0] += 1
                g[1] += int(mem) * 1024 if mem else 0
    if not groups:
        return "فهرست پردازه‌ها خوانده نشد."
    top = sorted(groups.items(), key=lambda kv: kv[1][1], reverse=True)[:limit]
    lines = [f"پردازه‌ها: {sum(v[0] for v in groups.values())} عدد؛ {limit} مصرف‌کننده‌ی اول RAM:"]
    for name, (count, mem) in top:
        lines.append(f"- {name}" + (f" ×{count}" if count > 1 else "") + f" — {mem / 1024 ** 2:.0f} MB")
    return "\n".join(lines)


def active_window_text() -> str:
    if not IS_WIN:
        return "خواندن پنجره‌ی فعال فقط روی ویندوز ممکن است."
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    hwnd = user32.GetForegroundWindow()
    own = os.getpid()
    title, pid_val = "", 0
    if hwnd:
        n = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, buf, n + 1)
        title = buf.value.strip()
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        pid_val = int(pid.value)
    if hwnd and pid_val and pid_val != own:
        return f"پنجره‌ی فعال: «{title}» — برنامه: {_process_name(pid_val) or 'نامشخص'}"
    # The user is talking to Kira, so Kira's own window is in front: report the topmost OTHER window (z-order) and say so.
    others = [w for w in visible_windows() if w["pid"] != own]
    if others:
        w = others[0]
        return (f"الان پنجره‌ی خود Kira جلوست. بالاترین پنجره‌ی دیگر (احتمالاً برنامه‌ای که قبل از Kira استفاده می‌کردی): "
                f"«{w['title']}» — برنامه: {w['process'] or 'نامشخص'}. این حدس بر اساس ترتیب پنجره‌هاست، نه قطعی.")
    return "پنجره‌ی فعال دیگری تشخیص داده نشد."


# ------------------------------------------------------------------ network
def _tcp_ok(host, port, timeout=2.0):
    t0 = time.monotonic()
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True, int((time.monotonic() - t0) * 1000)
    except OSError:
        return False, None


def network_text() -> str:
    lines = []
    ok, ms = _tcp_ok("1.1.1.1", 443)
    if not ok:
        ok, ms = _tcp_ok("8.8.8.8", 53)
    dns_ok = True
    try:
        socket.setdefaulttimeout(3)
        socket.getaddrinfo("www.msftconnecttest.com", 443)
    except OSError:
        dns_ok = False
    finally:
        socket.setdefaulttimeout(None)
    if ok and dns_ok:
        lines.append(f"اینترنت: وصل است (تأخیر اتصال حدود {ms} ms)")
    elif ok and not dns_ok:
        lines.append("اینترنت: ارتباط مستقیم با IP برقرار است ولی DNS جواب نمی‌دهد (مشکل DNS).")
    else:
        lines.append("اینترنت: اتصال برقرار نشد (شاید قطع است یا فایروال/VPN جلویش را گرفته).")
    lines.append(f"نام کامپیوتر: {socket.gethostname()}")
    ips = set()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))                      # no packet is sent: it only selects the outgoing interface
        ips.add(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except OSError:
        pass
    ips = sorted(i for i in ips if not i.startswith("127."))
    if ips:
        lines.append("IP محلی: " + " ، ".join(ips))
    if psutil is not None:
        try:
            up = [n for n, st in psutil.net_if_stats().items() if st.isup and not n.lower().startswith(("loopback", "lo"))]
            if up:
                lines.append("کارت‌های شبکه‌ی فعال: " + " ، ".join(up[:6]))
        except Exception:                                     # noqa: BLE001
            pass
    return "\n".join(lines)
