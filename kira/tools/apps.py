"""Ordinary actions (level 2): open an installed app, open a file / folder with its default program, open a web link.

No shell is ever involved and nothing is built from model text as a command line. An app is found BY NAME among: Start Menu / Desktop
shortcuts, Steam library games (steam://rungameid/<id>), Windows' installed-apps list (install folder / icon), App Paths and Store apps
(see appcatalog.py) - or a short fixed list of Windows tools. Before starting anything the real state is checked (processes by image path,
visible and tray-hidden windows): a running instance is brought forward instead of starting a second one. Files / folders are opened with
their default program; programs / scripts / shortcuts can never be started through open_path.
"""
from __future__ import annotations

import difflib
import os
import re
import subprocess
import sys
import time
import webbrowser

from .access import PathPolicy, EXECUTABLE_EXT
from .registry import ToolError, DENIED
from . import sysinfo, appcatalog

IS_WIN = sys.platform == "win32"
# Fixed Windows tools: name -> (label, how). "exe" = program in System32, "uri" = a Windows protocol link.
BUILTIN_APPS = {
    "notepad": ("Notepad", "exe", "notepad.exe", ("نوت پد", "نوتپد", "notepad", "ویرایشگر متن")),
    "calculator": ("Calculator", "exe", "calc.exe", ("ماشین حساب", "ماشینحساب", "calculator", "calc")),
    "paint": ("Paint", "exe", "mspaint.exe", ("پینت", "paint")),
    "explorer": ("File Explorer", "exe", "explorer.exe", ("فایل اکسپلورر", "اکسپلورر", "فایل منیجر", "explorer", "file explorer")),
    "clock": ("Clock", "uri", "ms-clock:", ("برنامه ساعت", "برنامه‌ی ساعت", "clock app", "alarms", "آلارم", "زنگ ساعت")),
    "settings": ("Settings", "uri", "ms-settings:", ("تنظیمات ویندوز", "windows settings", "settings")),
}
SKIP_WORDS = appcatalog.SKIP_WORDS
_norm = appcatalog.norm
# Spoken / Persian names -> the name used by the app itself (compared after normalisation)
_NAME_ALIASES = {"هاتاسپاتشیلد": "hotspotshield", "هاتاسپات": "hotspotshield", "هات‌اسپات‌شیلد": "hotspotshield",
                 "والپیپرانجین": "wallpaperengine", "وال‌پیپرانجین": "wallpaperengine", "والپیپر": "wallpaperengine", "wallpaper": "wallpaperengine"}
NOT_FOUND_TEXT_SHORT = "جست‌وجو در Start Menu، Steam، برنامه‌های نصب‌شده‌ی ویندوز و برنامه‌های Store انجام شد (برنامه‌های پورتابل بدون نصب ممکن است دیده نشوند)."
NOT_FOUND_TEXT = "برنامه‌ای با این نام پیدا نشد؛ " + NOT_FOUND_TEXT_SHORT
_NO_PLAN_WAIT = 8.0
_STEAM_WAIT = 20.0


def installed_apps(max_age: float = 120.0) -> list[tuple[str, str]]:
    """[(display name, shortcut path)] from the Start Menu (kept for older callers)."""
    return [(e.name, e.lnk_path()) for e in appcatalog.menu_apps(max_age) if e.lnk_path()]


def _pick(q: str, apps: list):
    """('hit', entry) | ('ambiguous', [names]) | ('none', None) - exact, then prefix, then substring; a clearly shortest name wins."""
    exact = [a for a in apps if a.key == q]
    if len(exact) == 1:
        return "hit", exact[0]
    starts = [a for a in apps if a.key.startswith(q)]
    if len(starts) == 1:
        return "hit", starts[0]
    contains = [a for a in apps if q in a.key]
    pool = exact or starts or contains
    if len(pool) == 1:
        return "hit", pool[0]
    if len(pool) > 1:
        pool = sorted(pool, key=lambda a: len(a.name))
        if len(pool[0].key) * 1.6 < len(pool[1].key):
            return "hit", pool[0]
        return "ambiguous", [a.name for a in pool[:8]]
    return "none", None


def resolve_app(name: str):
    """-> ('builtin', key) | ('app', AppEntry) | ('ambiguous', [display names]) | ('none', [close names]).
    Looks in: Start Menu / Desktop / Steam first (what the user sees), then the Windows installed-apps list and App Paths,
    then Store apps. The first source with a unique match wins; a vague match is reported, never guessed."""
    q = _norm(name)
    if not q:
        return "none", []
    q = _norm(_NAME_ALIASES.get(q, q))
    for key, (label, _, _, aliases) in BUILTIN_APPS.items():
        if q == _norm(key) or q in {_norm(a) for a in aliases}:
            return "builtin", key
    for source in (appcatalog.menu_apps, appcatalog.deep_apps, appcatalog.uwp_apps):
        state, val = _pick(q, source())
        if state != "none":
            return ("app", val) if state == "hit" else ("ambiguous", val)
    names = {_norm(e.name): e.name for e in appcatalog.deep_apps()}
    close = difflib.get_close_matches(q, list(names), n=3, cutoff=0.72)
    return "none", [names[c] for c in close]


# ------------------------------------------------------------------ how to recognise a running app
_GENERIC_STEMS = {"update", "launcher", "setup", "start", "run", "app", "bootstrapper", "squirrel", "installer", "cmd", "powershell", "explorer"}
_GENERIC_WORDS = {"engine", "windows", "microsoft", "google", "desktop", "client", "software", "system", "manager", "service", "services", "player"}
_STEM_ALIASES = {"googlechrome": ("chrome",), "microsoftedge": ("msedge",), "visualstudiocode": ("code",), "telegramdesktop": ("telegram",),
                 "vlcmediaplayer": ("vlc",), "mozillafirefox": ("firefox",), "calculator": ("calculatorapp", "calc", "win32calc"),
                 "paint": ("mspaint",), "notepad": ("notepad",), "fileexplorer": ("explorer",), "microsoftword": ("winword",),
                 "microsoftexcel": ("excel",), "microsoftpowerpoint": ("powerpnt",), "spotify": ("spotify",), "steam": ("steam",)}


def _stem_of(path_or_name: str) -> str:
    return os.path.splitext(os.path.basename(str(path_or_name)))[0].strip().lower().replace(" ", "")


def _process_stems(label: str, extra_exes=()) -> set:
    """Lower-case process names (without .exe) that belong to this app."""
    stems = set(_STEM_ALIASES.get(_norm(label), ()))
    for e in extra_exes:
        if e:
            stems.add(_stem_of(e))
    for word in re.findall(r"[A-Za-z0-9]{4,}", label):             # "Telegram Desktop" -> telegram
        if word.lower() not in _GENERIC_WORDS:
            stems.add(word.lower())
    stems.add(_norm(label))
    return {s for s in (x.replace(" ", "") for x in stems) if s and s not in _GENERIC_STEMS}


def _install_hint(entry) -> tuple:
    """(install folder, exe) of the Windows 'installed apps' record that belongs to the same app, ('', '') if none is clear."""
    key = entry.key
    for other in appcatalog.deep_apps():
        if other is entry or not (other.install_dir or other.exe):
            continue
        ok = other.key == key or (len(key) >= 5 and len(other.key) >= 5 and (other.key.startswith(key) or key.startswith(other.key)))
        if ok:
            return other.install_dir, other.exe
    return "", ""


def _identity(entry) -> appcatalog.AppIdentity:
    folders, exes, loose = [], [], []
    if entry.install_dir:
        folders.append(entry.install_dir)
    if entry.exe:
        exes.append(entry.exe)
        folders.append(os.path.dirname(entry.exe))
    if entry.lnk_path():
        for p in appcatalog.lnk_exes(entry.lnk_path()):
            if os.path.isabs(p):
                exes.append(p)
                folders.append(os.path.dirname(p))
            else:
                loose.append(p)
    if not any(appcatalog._usable_dir(f) for f in folders):       # the shortcut told us nothing: use the Windows installed-apps record
        d, e = _install_hint(entry)
        if d:
            folders.append(d)
        if e:
            exes.append(e)
    return appcatalog.AppIdentity(entry.name, folders, exes, _process_stems(entry.name, exes + loose))


def _builtin_identity(label: str, exe: str) -> appcatalog.AppIdentity:
    return appcatalog.AppIdentity(label, (), (), _process_stems(label, [exe] if exe else []))


class _State:
    """A snapshot of one app: its processes and windows right now."""

    def __init__(self, ident, with_hidden: bool):
        self.ident = ident
        self.procs = appcatalog.running_processes()
        strong, weak = appcatalog.match_processes(ident, self.procs)
        self.matched = strong + weak
        self.pids = {p["pid"] for p in self.matched}
        all_visible = sysinfo.visible_windows()
        self.visible = [w for w in all_visible if w["pid"] != os.getpid() and (w["pid"] in self.pids or _by_name(w, ident.stems))]
        seen = {w["hwnd"] for w in self.visible}
        self.hidden = []
        if with_hidden and self.pids:
            self.hidden = [w for w in appcatalog.windows_of_pids(self.pids) if not w["visible"] and w["hwnd"] not in seen]
        self.all_hwnds = {w["hwnd"] for w in all_visible}

    def main_exe_count(self) -> int:
        main = next((os.path.normcase(os.path.normpath(e)) for e in self.ident.exes if e), "")
        return sum(1 for p in self.procs if main and p.get("exe") and os.path.normcase(os.path.normpath(p["exe"])) == main)


def _by_name(w: dict, stems: set) -> bool:
    proc = os.path.splitext((w.get("process") or "").lower())[0].replace(" ", "")
    return bool(proc) and (proc in stems or any(len(s) >= 4 and s in proc for s in stems))


def find_running_windows(stems: set) -> list:
    """Visible top-level windows (minimized ones included) of the running app, topmost first."""
    return [w for w in sysinfo.visible_windows() if w["pid"] != os.getpid() and _by_name(w, stems)]


def _activate_best(label: str, wins: list, hidden: bool = False):
    """Restore (if minimized) and raise the best window. -> (report text, ok)."""
    import ctypes
    user32 = ctypes.windll.user32
    wins = sorted(wins, key=lambda w: bool(user32.IsIconic(w["hwnd"])))   # prefer a window that is not minimized (z-order is the tie-break)
    w = wins[0]
    ok, note = sysinfo.activate_window(w["hwnd"])
    if hidden:
        ok = ok or bool(user32.IsWindowVisible(w["hwnd"]) and not user32.IsIconic(w["hwnd"]))
        return (f"«{label}» در پس‌زمینه/System Tray اجرا بود و پنجره‌ی مخفی داشت؛ نمونه‌ی جدید باز نشد. {note} پنجره: «{w['title'][:50]}».", ok)
    more = f" (از {len(wins)} پنجره‌ی باز این برنامه، بالاترین انتخاب شد)" if len(wins) > 1 else ""
    text = f"«{label}» از قبل در حال اجرا بود؛ نمونه‌ی جدید باز نشد. {note}{more} پنجره: «{w['title'][:50]}»."
    if not ok:
        text += " (اگر برنامه با دسترسی Administrator اجرا شده باشد، ویندوز به Kira اجازه‌ی جلو آوردنش را نمی‌دهد.)"
    return text, ok


def activate_existing(label: str, lnk_path: str = "", exe: str = ""):
    """If the app already has a window: restore it (if minimized) and bring it to the front. -> (report text, ok), or None when it has no window."""
    if not IS_WIN:
        return None
    wins = find_running_windows(_process_stems(label, [exe] if exe else []))
    return _activate_best(label, wins) if wins else None


# ------------------------------------------------------------------ starting
_WINERR = {2: "فایل پیدا نشد", 3: "مسیر پیدا نشد", 5: "دسترسی رد شد", 87: "پارامتر نامعتبر", 193: "فایل اجرایی معتبر ویندوز نیست",
           740: "برنامه نیاز به دسترسی Administrator دارد", 1155: "هیچ برنامه‌ای برای این نوع لینک/فایل ثبت نشده است (مثلاً Steam نصب یا ثبت نشده)",
           1223: "کاربر پنجره‌ی UAC را لغو کرد", 1260: "سیاست امنیتی ویندوز اجرای این برنامه را مسدود کرده است"}


def _oserr(e: Exception) -> str:
    code = getattr(e, "winerror", None)
    base = _WINERR.get(code) or str(getattr(e, "strerror", "") or e)
    return f"{base} (WinError {code})" if code else base


def _method_text(kind: str, target: str) -> str:
    return {"lnk": "میان‌بر Start Menu", "steam": f"Steam (appid {target})", "exe": f"فایل اجرایی {target}", "uwp": "برنامه‌ی Store (shell:AppsFolder)"}.get(kind, kind)


def _launch_plan(entry) -> list:
    """[(kind, target, certain)] in the order they should be tried. Nothing here comes from model text."""
    plan = []
    by_kind = {k: [t for kk, t in entry.launchers if kk == k] for k in ("lnk", "steam", "exe", "uwp")}
    plan += [("lnk", t, True) for t in by_kind["lnk"]]
    plan += [("steam", t, True) for t in by_kind["steam"]]
    exes = list(by_kind["exe"])
    if entry.exe:
        exes.append(entry.exe)
    certain_exes = [p for p in exes if appcatalog.is_safe_exe(p)]
    if not certain_exes and entry.lnk_path():
        certain_exes = [p for p in appcatalog.lnk_exes(entry.lnk_path()) if os.path.isabs(p) and appcatalog.is_safe_exe(p)]
    plan += [("exe", p, True) for p in dict.fromkeys(certain_exes)]
    if not any(k in ("lnk", "steam", "exe") for k, _, _ in plan):
        folder, hint_exe = entry.install_dir, ""
        if not folder:
            folder, hint_exe = _install_hint(entry)
        if hint_exe and appcatalog.is_safe_exe(hint_exe):
            plan.append(("exe", hint_exe, True))
        else:
            guess = appcatalog.find_main_exe(entry.name, folder) if folder else ""
            if guess:
                plan.append(("exe", guess, False))                   # a guess from the folder contents: not "certain"
    plan += [("uwp", t, True) for t in by_kind["uwp"]]
    return plan


def _start(kind: str, target: str):
    """Start one thing through the Windows shell (never a command line). Raises OSError / ToolError with the real reason."""
    if kind == "lnk":
        bad = [p for p in appcatalog.lnk_exes(target) if os.path.basename(p).lower() in appcatalog.BLOCKED_EXES]
        if bad:
            raise ToolError("این میان‌بر به یک مفسر/ابزار فرمان اشاره می‌کند و اجرا نمی‌شود.", DENIED)
        absolute = [p for p in appcatalog.lnk_exes(target) if os.path.isabs(p) and p.lower().endswith(".exe")]
        if absolute and not any(os.path.isfile(p) for p in absolute):
            raise FileNotFoundError(2, "مقصد میان‌بر وجود ندارد (برنامه جابه‌جا یا حذف شده): " + absolute[0])
        os.startfile(target)
    elif kind == "steam":
        if not appcatalog._STEAM_ID_RX.match(str(target)):
            raise ToolError("شناسه‌ی Steam معتبر نیست.", DENIED)
        os.startfile(f"steam://rungameid/{target}")
    elif kind == "exe":
        if not appcatalog.is_safe_exe(target):
            raise ToolError("این فایل اجرایی مجاز یا موجود نیست: " + str(target), DENIED)
        try:
            os.startfile(target, cwd=os.path.dirname(target))
        except TypeError:
            os.startfile(target)
    elif kind == "uwp":
        if not appcatalog._AUMID_RX.match(str(target)):
            raise ToolError("شناسه‌ی برنامه‌ی Store معتبر نیست.", DENIED)
        os.startfile("shell:AppsFolder\\" + target)
    else:
        raise ToolError("روش اجرای ناشناخته.", DENIED)


class AppTools:
    def __init__(self, policy: PathPolicy):
        self.policy = policy

    @staticmethod
    def _describe(entry) -> str:
        sources = {"startmenu": "Start Menu", "steam": "کتابخانه‌ی Steam", "steam-shortcut": "میان‌بر Steam", "installed-apps": "برنامه‌های نصب‌شده‌ی ویندوز",
                   "app-paths": "App Paths", "store-app": "برنامه‌ی Store"}
        src = "، ".join(sources.get(s, s) for s in sorted(entry.sources))
        plan = _launch_plan(entry)
        how = _method_text(plan[0][0], plan[0][1]) + ("" if plan[0][2] else " (حدس از محتوای پوشه‌ی نصب)") if plan else "نامشخص (مسیر مطمئن اجرا پیدا نشد)"
        return f"منبع: {src}. روش اجرا: {how}."

    def find_app(self, a: dict) -> str:
        kind, val = resolve_app(a["name"])
        if kind == "builtin":
            return f"ابزار ویندوز پیدا شد: {BUILTIN_APPS[val][0]} (با open_app باز می‌شود)."
        if kind == "app":
            status = ""
            if IS_WIN:
                st = _State(_identity(val), with_hidden=True)
                status = (" وضعیت: پنجره‌ی باز دارد." if st.visible else " وضعیت: در پس‌زمینه/Tray اجرا شده (پنجره‌ی مخفی دارد)." if st.hidden
                          else f" وضعیت: {len(st.pids)} پردازش در حال اجراست ولی پنجره‌ی قابل‌دیدن ندارد." if st.pids else " وضعیت: الان اجرا نیست.")
            return f"برنامه پیدا شد: {val.name} (با open_app باز می‌شود). {self._describe(val)}{status}"
        if kind == "ambiguous":
            return "چند برنامه‌ی نزدیک پیدا شد؛ از کاربر بپرس کدام: " + " ، ".join(val)
        if val:
            return "دقیقاً پیدا نشد؛ شاید منظور این‌هاست: " + " ، ".join(val)
        return NOT_FOUND_TEXT

    def open_app(self, a: dict) -> str:
        if not IS_WIN:
            raise ToolError("باز کردن برنامه فقط روی ویندوز ممکن است.")
        kind, val = resolve_app(a["name"])
        if kind == "ambiguous":
            return "برنامه‌ای باز نشد چون نام مبهم است. چند گزینه: " + " ، ".join(val) + ". از کاربر بپرس کدام را می‌خواهد."
        if kind == "none":
            hint = (" شاید منظور این‌ها باشد: " + " ، ".join(val)) if val else ""
            raise ToolError(f"برنامه‌ای به نام «{a['name']}» پیدا نشد؛ {NOT_FOUND_TEXT_SHORT}{hint}")
        if kind == "builtin":
            label, how, target, _ = BUILTIN_APPS[val]
            return self._open_builtin(label, how, target)
        return self._open_entry(val)

    # -- Windows tools (Notepad, Calculator ...): visible windows only, exactly as before
    def _open_builtin(self, label: str, how: str, target: str) -> str:
        found = activate_existing(label, exe=target if how == "exe" else "")
        if found:
            text, ok = found
            return text if ok else text + " (برنامه دوباره اجرا نشد.)"
        before = {w["hwnd"] for w in sysinfo.visible_windows()}
        if how == "exe":
            subprocess.Popen([target], shell=False)
        else:
            os.startfile(target)                                  # a Windows protocol link such as ms-clock:
        return f"دستور اجرای «{label}» به ویندوز داده شد. " + self._wait_new_window(before, 4.0)[1]

    # -- every other app: look at the real state first, reuse the running instance, start only if needed
    def _open_entry(self, entry) -> str:
        label = entry.name
        ident = _identity(entry)
        st = _State(ident, with_hidden=True)
        if st.visible:                                            # 1) a normal window exists: restore it and bring it forward
            text, ok = _activate_best(label, st.visible)
            return text if ok else text + " (برنامه دوباره اجرا نشد.)"
        if st.hidden:                                             # 2) running in the tray: its own hidden main window can be shown
            text, ok = _activate_best(label, st.hidden, hidden=True)
            if ok:
                return text
        running_note = ""
        if st.pids:
            names = ", ".join(sorted({p["name"] for p in st.matched if p.get("name")})[:4])
            running_note = (f"«{label}» از قبل در پس‌زمینه/System Tray در حال اجراست ({len(st.pids)} پردازش: {names}) ولی پنجره‌ی قابل‌دیدن ندارد؛ "
                            "برای فعال‌سازی همان نمونه، فقط یک‌بار دستور اجرای عادی داده شد تا خود برنامه نمونه‌ی در حال اجرا را بالا بیاورد. ")
        plan = _launch_plan(entry)
        if not plan:
            where = self._describe(entry)
            raise ToolError(f"«{label}» شناسایی شد ولی مسیر یا روش مطمئن اجرایش مشخص نیست، پس چیزی اجرا نشد تا نمونه‌ی ناخواسته ساخته نشود. {where}"
                            + (f" (برنامه در پس‌زمینه اجراست: {len(st.pids)} پردازش.)" if st.pids else ""))
        if st.pids and not plan[0][2]:
            return (f"«{label}» در پس‌زمینه اجراست ولی پنجره‌ی قابل‌دیدن ندارد و مسیر مطمئنی برای فعال‌سازی‌اش ندارم "
                    f"(فقط حدس: {plan[0][1]}). برای جلوگیری از اجرای نمونه‌ی دوم چیزی اجرا نشد؛ از کاربر بخواه از System Tray بازش کند.")
        errors, started = [], None
        for kind, target, _certain in plan:
            try:
                _start(kind, target)
                started = (kind, target)
                break
            except ToolError as e:
                errors.append(f"{_method_text(kind, target)}: {e}")
            except OSError as e:
                errors.append(f"{_method_text(kind, target)}: {_oserr(e)}")
        if not started:
            raise ToolError(f"اجرای «{label}» ناموفق بود. علت: " + " | ".join(errors))
        wait = _STEAM_WAIT if started[0] == "steam" else _NO_PLAN_WAIT
        report = self._verify(label, ident, st, wait)
        tried = (" (روش‌های ناموفق قبلی: " + " | ".join(errors) + ")") if errors else ""
        return f"{running_note}دستور اجرای «{label}» با {_method_text(*started)} به ویندوز داده شد.{tried} {report}"

    @staticmethod
    def _wait_new_window(before_hwnds: set, seconds: float, pids=None):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            time.sleep(0.5)
            new = [w for w in sysinfo.visible_windows() if w["hwnd"] not in before_hwnds and w["pid"] != os.getpid()]
            if pids is not None:
                new = [w for w in new if w["pid"] in pids] or []
            if new:
                w = new[0]
                return w, f"پنجره‌ی جدید دیده شد: «{w['title'][:60]}» ({w.get('process') or 'نامشخص'})."
        return None, (f"تا {int(seconds)} ثانیه پنجره‌ی جدیدی دیده نشد؛ ممکن است هنوز در حال بالا آمدن باشد یا در System Tray اجرا شود. "
                      "باز شدنش را تأیید نکن، فقط همین را به کاربر بگو.")

    def _verify(self, label: str, ident, before: "_State", seconds: float) -> str:
        """Honest check after a start: a new window, a window of the app's processes, or (at least) its processes."""
        deadline = time.monotonic() + seconds
        other_new = None
        while time.monotonic() < deadline:
            time.sleep(0.5)
            procs = appcatalog.running_processes()
            strong, weak = appcatalog.match_processes(ident, procs)
            pids = {p["pid"] for p in strong + weak}
            new = [w for w in sysinfo.visible_windows() if w["hwnd"] not in before.all_hwnds and w["pid"] != os.getpid()]
            mine = [w for w in new if w["pid"] in pids or _by_name(w, ident.stems)]
            if mine:
                return self._finish(f"پنجره‌ی جدید دیده شد: «{mine[0]['title'][:60]}» ({mine[0].get('process') or 'نامشخص'}).", ident, before)
            if new and other_new is None:
                other_new = new[0]
        procs = appcatalog.running_processes()
        strong, weak = appcatalog.match_processes(ident, procs)
        pids = {p["pid"] for p in strong + weak}
        hidden = [w for w in appcatalog.windows_of_pids(pids) if not w["visible"]] if pids else []
        if hidden:                                                # the relaunch woke the app's tray window: show it
            text, ok = _activate_best(label, hidden, hidden=True)
            if ok:
                return self._finish(text, ident, before)
        if other_new:
            return self._finish(f"پنجره‌ی جدید دیده شد: «{other_new['title'][:60]}» ({other_new.get('process') or 'نامشخص'}) "
                                "(ممکن است پنجره‌ی لانچر/برنامه‌ی واسط باشد، نه خود برنامه).", ident, before)
        if pids:
            names = ", ".join(sorted({p["name"] for p in strong + weak if p.get("name")})[:4])
            return self._finish(f"پردازش برنامه در حال اجراست ({len(pids)} پردازش: {names}) ولی تا {int(seconds)} ثانیه پنجره‌ی جدیدی دیده نشد؛ "
                                "احتمالاً در System Tray/پس‌زمینه است یا با دسترسی Administrator اجرا شده و Kira نمی‌تواند پنجره‌اش را ببیند. "
                                "باز شدنش را تأیید نکن، فقط همین را به کاربر بگو.", ident, before)
        return self._finish(f"تا {int(seconds)} ثانیه پنجره‌ی جدیدی دیده نشد و هیچ پردازشی از این برنامه هم پیدا نشد؛ ویندوز دستور را پذیرفت ولی برنامه بالا نیامد "
                            "(علت ممکن: خطای خود برنامه، نیاز به ورود/به‌روزرسانی، یا مسدود شدن توسط آنتی‌ویروس/UAC). باز شدنش را تأیید نکن، فقط همین را به کاربر بگو.",
                            ident, before)

    @staticmethod
    def _finish(text: str, ident, before: "_State") -> str:
        """Add a warning when the main program now has MORE processes than before (a possible second copy)."""
        try:
            now_procs = appcatalog.running_processes()
            main = next((os.path.normcase(os.path.normpath(e)) for e in ident.exes if e), "")
            after = sum(1 for p in now_procs if main and p.get("exe") and os.path.normcase(os.path.normpath(p["exe"])) == main)
            was = before.main_exe_count()
            if was and after > was:
                text += f" ⚠️ تعداد پردازش‌های برنامه‌ی اصلی از {was} به {after} رسید؛ ممکن است نمونه‌ی دوم هم باز شده باشد (برنامه‌های چندپردازشی ممکن است عادی باشد)."
        except Exception:                                          # noqa: BLE001
            pass
        return text

    def open_path(self, a: dict) -> str:
        path = self.policy.check(a["path"])
        ext = os.path.splitext(path)[1].lower()
        if ext in EXECUTABLE_EXT:
            raise ToolError("اجرای برنامه، اسکریپت یا میان‌بر از طریق open_path ممنوع است. برنامه‌ها فقط با open_app و نامشان باز می‌شوند.", DENIED)
        if not IS_WIN:
            raise ToolError("باز کردن فایل با برنامه‌ی پیش‌فرض فقط روی ویندوز ممکن است.")
        os.startfile(path)
        return ("پوشه در File Explorer باز شد: " if os.path.isdir(path) else "فایل با برنامه‌ی پیش‌فرضش باز شد: ") + path

    def open_url(self, a: dict) -> str:
        url = str(a["url"]).strip()
        if not re.match(r"^https?://[^\s]+$", url, re.I):
            raise ToolError("فقط لینک http یا https باز می‌شود.", DENIED)
        if not webbrowser.open(url):
            raise ToolError("مرورگر پیش‌فرض باز نشد.")
        return f"لینک در مرورگر پیش‌فرض باز شد: {url}"
