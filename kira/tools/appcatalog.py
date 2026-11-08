"""App discovery for open_app: WHERE an app lives and WHICH of its processes / windows are running. Nothing here starts anything.

Sources (merged into one entry per app, never built from model text):
  * Start Menu shortcuts (.lnk) and Steam shortcuts (.url -> steam://rungameid/<digits>), plus Steam shortcuts on the Desktop
  * Steam library manifests (appmanifest_*.acf): "Wallpaper Engine" and other Steam apps that have no Start Menu .lnk
  * Windows "Installed apps" registry (Uninstall keys): InstallLocation / DisplayIcon
  * App Paths registry (chrome.exe, ...)
  * Store (UWP) apps through a FIXED Get-StartApps query (no user text in it), only when nothing else matched
  * running processes (by full image path, so "anything inside the install folder" counts) and the windows owned by them,
    including hidden ones (apps that live in the tray keep a hidden main window)

Everything degrades to "not found" on non-Windows systems or when a source is unreadable.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time

from .winrunner import FixedScript, run_fixed

try:                                                          # Windows only
    import winreg
except Exception:                                             # noqa: BLE001
    winreg = None
try:                                                          # optional, faster process list
    import psutil
except Exception:                                             # noqa: BLE001
    psutil = None

IS_WIN = sys.platform == "win32"
NO_WINDOW = 0x08000000 if IS_WIN else 0

SKIP_WORDS = ("uninstall", "حذف", "remove", "readme", "license", "help", "documentation", "website", "release notes")
_REGISTRY_SKIP = SKIP_WORDS + ("redistributable", "visual c++", "runtime", "hotfix", "security update", "update for", "driver package")
# Programs that can run arbitrary commands: an app entry may never resolve to one of these.
BLOCKED_EXES = {"cmd.exe", "powershell.exe", "pwsh.exe", "wscript.exe", "cscript.exe", "mshta.exe", "regsvr32.exe", "rundll32.exe", "msiexec.exe",
                "reg.exe", "wmic.exe", "bash.exe", "wsl.exe", "certutil.exe", "bitsadmin.exe", "schtasks.exe", "sc.exe", "net.exe", "net1.exe",
                "taskkill.exe", "msbuild.exe", "installutil.exe", "regasm.exe", "regsvcs.exe", "forfiles.exe", "at.exe", "python.exe", "pythonw.exe"}
_NOT_MAIN_EXE_RX = re.compile(r"(?i)unins|uninstall|setup|install|updat|crash|helper|report|redist|vcredist|dotnet|webview|elevat|maintenance|repair|"
                              r"cef|squirrel|diagnos|telemetry|bootstrap|notifier")
_GENERIC_ROOTS = {"program files", "program files (x86)", "windows", "system32", "syswow64", "programdata", "users", "common files", "steamapps", "common"}
STEAM_SKIP_APPIDS = {"228980"}                                # Steamworks Common Redistributables
_STEAM_ID_RX = re.compile(r"^\d{1,12}$")
_AUMID_RX = re.compile(r"^[A-Za-z0-9.\-_]+_[a-z0-9]{13}![A-Za-z0-9.\-_]+$")

_PRIORITY = {"lnk": 0, "steam": 1, "exe": 2, "uwp": 3}


def norm(text: str) -> str:
    text = str(text or "").lower().replace("ي", "ی").replace("ك", "ک")
    return re.sub(r"[\u200c\u200f\s\-_.]+", "", text)


class AppEntry:
    """One app, possibly seen by several sources. launchers = [(kind, target)] with kind lnk | steam | exe | uwp."""

    def __init__(self, name: str):
        self.name = name
        self.launchers: list[tuple[str, str]] = []
        self.sources: set[str] = set()
        self.install_dir = ""
        self.exe = ""
        self.steam_id = ""

    @property
    def key(self) -> str:
        return norm(self.name)

    def add(self, source: str, kind: str = "", target: str = "", install_dir: str = "", exe: str = ""):
        self.sources.add(source)
        if kind and target and (kind, target) not in self.launchers:
            self.launchers.append((kind, target))
        if install_dir and not self.install_dir:
            self.install_dir = install_dir
        if exe and not self.exe:
            self.exe = exe
        if kind == "steam" and not self.steam_id:
            self.steam_id = target

    def lnk_path(self) -> str:
        return next((t for k, t in self.launchers if k == "lnk"), "")

    def __repr__(self):                                       # pragma: no cover
        return f"AppEntry({self.name!r}, {sorted(self.sources)})"


# ------------------------------------------------------------------ small helpers
def _read_text(path: str, limit: int = 262144) -> str:
    try:
        with open(path, "rb") as fh:
            raw = fh.read(limit)
    except OSError:
        return ""
    for enc in ("utf-8-sig", "utf-16", "cp1252"):
        try:
            return raw.decode(enc)
        except UnicodeError:
            continue
    return raw.decode("utf-8", "ignore")


def _clean_path(value: str) -> str:
    value = os.path.expandvars(str(value or "").strip().strip('"').strip())
    return value


def _icon_exe(value: str) -> str:
    """DisplayIcon / icon location such as '"C:\\App\\app.exe",0' -> 'C:\\App\\app.exe' ('' when it is not an .exe)."""
    value = str(value or "").strip()
    if value.startswith('"'):
        end = value.find('"', 1)
        value = value[1:end] if end > 0 else value[1:]
    else:
        value = re.sub(r",\s*-?\d+\s*$", "", value)
    value = _clean_path(value)
    return value if value.lower().endswith(".exe") else ""


def is_safe_exe(path: str) -> bool:
    p = str(path or "")
    base = os.path.basename(p).lower()
    return bool(p) and os.path.isabs(p) and p.lower().endswith(".exe") and base not in BLOCKED_EXES and not re.search(r"(?i)unins|uninstall", base) and os.path.isfile(p)


def _usable_dir(path: str) -> bool:
    """An install folder specific enough to identify one app (not C:\\, Program Files itself, ...)."""
    if not path or not os.path.isdir(path):
        return False
    p = os.path.normpath(path)
    drive, rest = os.path.splitdrive(p)
    parts = [x for x in rest.split(os.sep) if x]
    return bool(parts) and os.path.basename(p).lower() not in _GENERIC_ROOTS


# ------------------------------------------------------------------ Start Menu / Desktop shortcuts
def _start_menu_dirs() -> list[str]:
    out = []
    for base in (os.environ.get("PROGRAMDATA"), os.environ.get("APPDATA")):
        if base:
            d = os.path.join(base, "Microsoft", "Windows", "Start Menu", "Programs")
            if os.path.isdir(d):
                out.append(d)
    return out


def _desktop_dirs() -> list[str]:
    out = []
    for base in (os.environ.get("PUBLIC"), os.environ.get("USERPROFILE")):
        if base:
            d = os.path.join(base, "Desktop")
            if os.path.isdir(d):
                out.append(d)
    return out


def _steam_url_id(path: str) -> str:
    """App id from a Steam internet shortcut (.url). Only steam://rungameid/<digits> is ever accepted."""
    m = re.search(r"(?im)^\s*URL\s*=\s*steam://(?:rungameid|run)/(\d{1,12})\s*$", _read_text(path, 8192))
    return m.group(1) if m else ""


def _collect_shortcuts(add) -> None:
    for root, recurse in [(r, True) for r in _start_menu_dirs()] + [(r, False) for r in _desktop_dirs()]:
        for folder, _, files in os.walk(root):
            for f in files:
                low = f.lower()
                if low.endswith(".lnk") and recurse:
                    kind, name = "lnk", f[:-4]
                elif low.endswith(".url"):
                    kind, name = "url", f[:-4]
                else:
                    continue
                if any(w in name.lower() for w in SKIP_WORDS):
                    continue
                full = os.path.join(folder, f)
                if kind == "lnk":
                    add(name, "startmenu", "lnk", full)
                else:
                    appid = _steam_url_id(full)
                    if appid and appid not in STEAM_SKIP_APPIDS:
                        add(name, "steam-shortcut", "steam", appid)
            if not recurse:
                break


# ------------------------------------------------------------------ Steam
def _reg_value(hive, path: str, name: str, view: int = 0):
    if winreg is None:
        return None
    try:
        with winreg.OpenKey(hive, path, 0, winreg.KEY_READ | view) as k:
            return winreg.QueryValueEx(k, name)[0]
    except OSError:
        return None


def steam_root() -> str:
    cands = []
    if IS_WIN and winreg is not None:
        cands.append(_reg_value(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"))
        cands.append(_reg_value(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"))
        cands.append(_reg_value(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam", "InstallPath"))
    for env in ("PROGRAMFILES(X86)", "PROGRAMFILES"):
        if os.environ.get(env):
            cands.append(os.path.join(os.environ[env], "Steam"))
    for c in cands:
        if c and os.path.isdir(os.path.normpath(str(c))):
            return os.path.normpath(str(c))
    return ""


def steam_libraries() -> list[str]:
    root = steam_root()
    if not root:
        return []
    libs = [root]
    text = _read_text(os.path.join(root, "steamapps", "libraryfolders.vdf"))
    for m in re.finditer(r'(?im)^\s*"(?:path|\d+)"\s+"([^"]+)"', text):
        p = m.group(1).replace("\\\\", "\\")
        if re.match(r"^[A-Za-z]:[\\/]", p) or p.startswith("\\\\"):
            libs.append(os.path.normpath(p))
    out, seen = [], set()
    for lib in libs:
        k = os.path.normcase(lib)
        if k not in seen and os.path.isdir(os.path.join(lib, "steamapps")):
            seen.add(k)
            out.append(lib)
    return out


def _collect_steam(add) -> None:
    for lib in steam_libraries():
        apps_dir = os.path.join(lib, "steamapps")
        try:
            names = os.listdir(apps_dir)
        except OSError:
            continue
        for fn in names:
            if not (fn.startswith("appmanifest_") and fn.endswith(".acf")):
                continue
            text = _read_text(os.path.join(apps_dir, fn), 65536)
            appid = re.search(r'"appid"\s+"(\d+)"', text)
            name = re.search(r'"name"\s+"([^"]+)"', text)
            idir = re.search(r'"installdir"\s+"([^"]+)"', text)
            flags = re.search(r'"StateFlags"\s+"(\d+)"', text)
            if not (appid and name and idir) or appid.group(1) in STEAM_SKIP_APPIDS:
                continue
            if flags and not (int(flags.group(1)) & 4):                    # 4 = fully installed
                continue
            if re.match(r"(?i)^(proton|steam linux runtime|steamworks)", name.group(1)):
                continue
            folder = os.path.join(apps_dir, "common", idir.group(1))
            if os.path.isdir(folder):
                add(name.group(1).replace("\\\"", '"'), "steam", "steam", appid.group(1), install_dir=folder)


# ------------------------------------------------------------------ Windows "Installed apps" registry + App Paths
def _enum_subkeys(hive, path: str, view: int):
    try:
        with winreg.OpenKey(hive, path, 0, winreg.KEY_READ | view) as k:
            i = 0
            while True:
                try:
                    yield winreg.EnumKey(k, i)
                except OSError:
                    return
                i += 1
    except OSError:
        return


def _read_values(hive, path: str, view: int) -> dict:
    out = {}
    try:
        with winreg.OpenKey(hive, path, 0, winreg.KEY_READ | view) as k:
            i = 0
            while True:
                try:
                    n, v, _ = winreg.EnumValue(k, i)
                except OSError:
                    break
                out[n] = v
                i += 1
    except OSError:
        pass
    return out


def _collect_uninstall(add) -> None:
    if not (IS_WIN and winreg is not None):
        return
    base = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"
    for hive, view in ((winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_64KEY), (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_32KEY), (winreg.HKEY_CURRENT_USER, 0)):
        for sub in _enum_subkeys(hive, base, view):
            vals = _read_values(hive, base + "\\" + sub, view)
            name = str(vals.get("DisplayName") or "").strip()
            if not name or vals.get("SystemComponent") == 1 or vals.get("ParentKeyName") or vals.get("ParentDisplayName"):
                continue
            low = name.lower()
            if any(w in low for w in _REGISTRY_SKIP):
                continue
            exe = _icon_exe(vals.get("DisplayIcon"))
            loc = _clean_path(vals.get("InstallLocation"))
            if not _usable_dir(loc):
                loc = os.path.dirname(exe) if exe and _usable_dir(os.path.dirname(exe)) else ""
            if exe and not is_safe_exe(exe):
                exe = ""
            if loc or exe:
                add(name, "installed-apps", "exe" if exe else "", exe, install_dir=loc, exe=exe)


def _collect_app_paths(add) -> None:
    if not (IS_WIN and winreg is not None):
        return
    base = r"Software\Microsoft\Windows\CurrentVersion\App Paths"
    for hive, view in ((winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_64KEY), (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_32KEY), (winreg.HKEY_CURRENT_USER, 0)):
        for sub in _enum_subkeys(hive, base, view):
            if not sub.lower().endswith(".exe"):
                continue
            exe = _icon_exe(_reg_value(hive, base + "\\" + sub, "", view) or "")
            if exe and is_safe_exe(exe):
                folder = os.path.dirname(exe)
                add(sub[:-4], "app-paths", "exe", exe, install_dir=folder if _usable_dir(folder) else "", exe=exe)


# ------------------------------------------------------------------ catalog (two tiers: what the user sees in menus, then everything else)
_CACHE = {"time": 0.0, "menu": [], "deep": []}
_UWP = {"time": 0.0, "items": None}


def _build(collectors) -> list[AppEntry]:
    entries: dict[str, AppEntry] = {}
    by_steam: dict[str, AppEntry] = {}

    def add(name, source, kind="", target="", install_dir="", exe=""):
        key = norm(name)
        if not key:
            return
        e = by_steam.get(target) if kind == "steam" and target in by_steam else entries.get(key)
        if e is None:
            e = entries[key] = AppEntry(name)
        e.add(source, kind, target, install_dir, exe)
        if kind == "steam":
            by_steam[target] = e

    for fn in collectors:
        try:
            fn(add)
        except Exception:                                      # noqa: BLE001 - one broken source must not hide the others
            continue
    items = list(entries.values())
    items.sort(key=lambda e: e.name.lower())
    return items


def _refresh(max_age: float):
    now = time.monotonic()
    if _CACHE["menu"] and now - _CACHE["time"] < max_age:
        return
    _CACHE["menu"] = _build([_collect_shortcuts, _collect_steam])
    _CACHE["deep"] = None                                      # built lazily
    _CACHE["time"] = now


def menu_apps(max_age: float = 120.0) -> list[AppEntry]:
    """Apps the user can see in the Start Menu / Desktop / Steam library."""
    _refresh(max_age)
    return _CACHE["menu"]


def deep_apps(max_age: float = 120.0) -> list[AppEntry]:
    """menu apps + Installed-apps registry + App Paths (only needed when the menu has no match)."""
    _refresh(max_age)
    if _CACHE["deep"] is None:
        _CACHE["deep"] = _build([_collect_shortcuts, _collect_steam, _collect_uninstall, _collect_app_paths])
    return _CACHE["deep"]


_STARTAPPS = FixedScript("start-apps", """
[Console]::OutputEncoding=[Text.Encoding]::UTF8
$o=@(Get-StartApps | ForEach-Object { @{ Name=[string]$_.Name; AppID=[string]$_.AppID } })
@{ ok=$true; items=$o } | ConvertTo-Json -Compress -Depth 4
""")


def uwp_apps(max_age: float = 600.0) -> list[AppEntry]:
    """Store (UWP) apps from a FIXED Get-StartApps query. No user text is ever part of this command."""
    if not IS_WIN:
        return []
    now = time.monotonic()
    if _UWP["items"] is not None and now - _UWP["time"] < max_age:
        return _UWP["items"]
    items: list[AppEntry] = []
    try:
        res = run_fixed(_STARTAPPS, timeout=15, api_name="Store apps")
        data = [] if res.get("fatal") or not res.get("ok") else res.get("items") or []
        if isinstance(data, dict):
            data = [data]
        for row in data:
            name, aid = str(row.get("Name") or "").strip(), str(row.get("AppID") or "").strip()
            if name and _AUMID_RX.match(aid) and not any(w in name.lower() for w in SKIP_WORDS):
                e = AppEntry(name)
                e.add("store-app", "uwp", aid)
                items.append(e)
    except Exception:                                          # noqa: BLE001 - PowerShell blocked / slow: Store apps are simply not listed
        items = []
    _UWP.update(time=now, items=items)
    return items


def drop_cache():
    _CACHE.update(time=0.0, menu=[], deep=[])
    _UWP.update(time=0.0, items=None)


# ------------------------------------------------------------------ finding the main program inside an install folder
def find_main_exe(name: str, folder: str) -> str:
    """The most likely main .exe of an app inside its install folder, or '' when it is not clear (then Kira does NOT guess)."""
    if not _usable_dir(folder):
        return ""
    want = norm(name)
    words = [w for w in re.findall(r"[a-z0-9]{3,}", name.lower())]
    cands = []

    def scan(d, depth):
        try:
            names = os.listdir(d)
        except OSError:
            return
        for n in names[:400]:
            full = os.path.join(d, n)
            if n.lower().endswith(".exe"):
                if _NOT_MAIN_EXE_RX.search(n) or not is_safe_exe(full):
                    continue
                cands.append((full, depth))
            elif depth == 0 and os.path.isdir(full) and n.lower() not in ("redist", "_commonredist", "resources", "locales"):
                scan(full, 1)

    scan(folder, 0)
    best, best_score = "", 0
    for full, depth in cands:
        stem = norm(os.path.splitext(os.path.basename(full))[0])
        score = 0
        if stem == want:
            score = 100
        elif len(stem) >= 3 and (want.startswith(stem) or stem.startswith(want) or want in stem):
            score = 80
        elif any(w in stem for w in words):
            score = 50
        if score:
            score += 5 if depth == 0 else 0
        if score > best_score:
            best, best_score = full, score
    if not best and len(cands) == 1:
        best, best_score = cands[0][0], 45
    return best if best_score >= 45 else ""


# ------------------------------------------------------------------ .lnk files (minimal parser, no COM)
def lnk_details(path: str) -> dict:
    """{'target', 'args', 'workdir', 'icon', 'relpath'} from a Shell Link; empty strings for whatever is missing."""
    import struct
    out = {"target": "", "args": "", "workdir": "", "icon": "", "relpath": ""}
    try:
        with open(path, "rb") as fh:
            d = fh.read(262144)
        if len(d) < 0x4C or struct.unpack_from("<I", d, 0)[0] != 0x4C:
            return out
        flags = struct.unpack_from("<I", d, 0x14)[0]
        pos = 0x4C
        if flags & 1:                                              # HasLinkTargetIDList
            pos += 2 + struct.unpack_from("<H", d, pos)[0]
        if flags & 2:                                              # HasLinkInfo
            start = pos
            size, hdr, lflags = struct.unpack_from("<III", d, pos)
            if lflags & 1:
                uni_off = struct.unpack_from("<I", d, start + 0x1C)[0] if hdr >= 0x24 else 0
                if uni_off:
                    out["target"] = d[start + uni_off:start + size].decode("utf-16-le", "ignore").split("\x00", 1)[0]
                else:
                    off = struct.unpack_from("<I", d, start + 0x10)[0]
                    out["target"] = d[start + off:start + size].split(b"\x00", 1)[0].decode("mbcs" if IS_WIN else "latin-1", "ignore")
            pos = start + size
        unicode_strings = bool(flags & 0x80)
        for bit, key in ((0x4, "name"), (0x8, "relpath"), (0x10, "workdir"), (0x20, "args"), (0x40, "icon")):
            if flags & bit:
                n = struct.unpack_from("<H", d, pos)[0]
                pos += 2
                width = 2 if unicode_strings else 1
                text = d[pos:pos + n * width].decode("utf-16-le" if unicode_strings else "latin-1", "ignore")
                pos += n * width
                if key != "name":
                    out[key] = text
        while pos + 8 <= len(d):                                   # extra data blocks: the environment block stores the full target path
            bsize, sig = struct.unpack_from("<II", d, pos)
            if bsize < 8:
                break
            if sig == 0xA0000001 and bsize >= 0x314 and not out["target"]:
                out["target"] = d[pos + 0x10c:pos + 0x10c + 520].decode("utf-16-le", "ignore").split("\x00", 1)[0]
                if not out["target"]:
                    out["target"] = d[pos + 8:pos + 8 + 260].split(b"\x00", 1)[0].decode("latin-1", "ignore")
            pos += bsize
    except Exception:                                              # noqa: BLE001
        pass
    return out


def lnk_exes(path: str) -> list[str]:
    """Every program path a shortcut points at (target, relative path, icon, .exe named in the arguments), env-vars expanded."""
    info = lnk_details(path)
    folder = os.path.dirname(path)
    found = []
    for raw in (info["target"], info["relpath"]):
        raw = _clean_path(raw)
        if not raw.lower().endswith(".exe"):
            continue
        if not os.path.isabs(raw):
            raw = os.path.normpath(os.path.join(info["workdir"] and _clean_path(info["workdir"]) or folder, raw))
        found.append(raw)
    icon = _icon_exe(info["icon"])
    if icon:
        found.append(icon)
    for m in re.finditer(r'([\w\-. ]+?\.exe)', info["args"], re.I):
        base = os.path.basename(m.group(1)).strip()
        if base:
            found.append(base)                                     # a bare name (e.g. Update.exe --processStart Discord.exe)
    out, seen = [], set()
    for p in found:
        if p.lower() not in seen:
            seen.add(p.lower())
            out.append(p)
    return out


# ------------------------------------------------------------------ running processes
def _image_path(pid: int) -> str:
    if not IS_WIN:
        return ""
    try:
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.windll.kernel32
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k32.CloseHandle.argtypes = [wintypes.HANDLE]
        h = k32.OpenProcess(0x1000, False, pid)                    # PROCESS_QUERY_LIMITED_INFORMATION (works for most elevated processes too)
        if not h:
            return ""
        try:
            buf = ctypes.create_unicode_buffer(1040)
            size = wintypes.DWORD(1040)
            if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                return buf.value
        finally:
            k32.CloseHandle(h)
    except Exception:                                              # noqa: BLE001
        pass
    return ""


def running_processes() -> list[dict]:
    """[{'pid', 'name', 'exe'}] of every process (exe is '' when Windows does not let us read it)."""
    out = []
    if psutil is not None:
        try:
            for p in psutil.process_iter(["pid", "name", "exe"]):
                info = p.info
                out.append({"pid": int(info["pid"]), "name": info.get("name") or "", "exe": info.get("exe") or ""})
            return out
        except Exception:                                          # noqa: BLE001
            out = []
    if not IS_WIN:
        return out
    try:
        import ctypes
        from ctypes import wintypes

        class PROCESSENTRY32W(ctypes.Structure):
            _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                        ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                        ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD),
                        ("szExeFile", ctypes.c_wchar * 260)]

        k32 = ctypes.windll.kernel32
        k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        k32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        k32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
        k32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
        k32.CloseHandle.argtypes = [wintypes.HANDLE]
        snap = k32.CreateToolhelp32Snapshot(0x2, 0)                # TH32CS_SNAPPROCESS
        if not snap or snap == ctypes.c_void_p(-1).value:
            return out
        try:
            e = PROCESSENTRY32W()
            e.dwSize = ctypes.sizeof(PROCESSENTRY32W)
            ok = k32.Process32FirstW(snap, ctypes.byref(e))
            while ok:
                pid = int(e.th32ProcessID)
                out.append({"pid": pid, "name": e.szExeFile, "exe": _image_path(pid) if pid else ""})
                ok = k32.Process32NextW(snap, ctypes.byref(e))
        finally:
            k32.CloseHandle(snap)
    except Exception:                                              # noqa: BLE001
        pass
    return out


def _under(path: str, folder: str) -> bool:
    if not path or not folder:
        return False
    p, f = os.path.normcase(os.path.normpath(path)), os.path.normcase(os.path.normpath(folder))
    return p == f or p.startswith(f.rstrip("\\/") + os.sep)


class AppIdentity:
    """Everything known about how to recognise one app's processes: install folders, exact exe paths, process-name stems."""

    def __init__(self, label: str, folders=(), exes=(), stems=()):
        self.label = label
        self.folders = [f for f in folders if f and _usable_dir(f)]
        self.exes = [e for e in exes if e]
        self.stems = set(stems)

    def merge(self, other: "AppIdentity"):
        for f in other.folders:
            if f not in self.folders:
                self.folders.append(f)
        for e in other.exes:
            if e not in self.exes:
                self.exes.append(e)
        self.stems |= other.stems


def match_processes(ident: AppIdentity, procs=None) -> tuple[list[dict], list[dict]]:
    """(strong, weak): strong = image path is the app's exe or inside its install folder; weak = process name looks like the app."""
    procs = running_processes() if procs is None else procs
    me = os.getpid()
    strong, weak = [], []
    exe_set = {os.path.normcase(os.path.normpath(e)) for e in ident.exes}
    for p in procs:
        if p["pid"] == me or p["pid"] == 0:
            continue
        path = p.get("exe") or ""
        if path and (os.path.normcase(os.path.normpath(path)) in exe_set or any(_under(path, f) for f in ident.folders)):
            strong.append(p)
            continue
        stem = os.path.splitext((p.get("name") or "").lower())[0].replace(" ", "")
        if stem and (stem in ident.stems or any(len(s) >= 4 and s in stem for s in ident.stems)):
            weak.append(p)
    return strong, weak


# ------------------------------------------------------------------ windows (visible AND hidden) owned by given processes
_IGNORED_CLASSES = {"msctfime ui", "ime", "gdi+ hook window class", "cicmarshalwnd", "tooltips_class32", "notifyiconoverflowwindow", "shell_traywnd",
                    "progman", "workerw", "dummydwmlistenerwindow", "msctf", "nvopencsdl"}


def windows_of_pids(pids: set) -> list[dict]:
    """Top-level windows of the given processes: [{'hwnd','title','pid','visible','iconic'}], visible ones first.
    Hidden windows are included only when they look like a real main window (titled, not a tool window, no owner, reasonable size) -
    that is how tray apps keep their window while 'closed'."""
    if not IS_WIN or not pids:
        return []
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    found = []
    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def cb(hwnd, _):
        try:
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if int(pid.value) not in pids:
                return True
            n = user32.GetWindowTextLengthW(hwnd)
            if n <= 0:
                return True
            if user32.GetWindowLongW(hwnd, -20) & 0x80:            # WS_EX_TOOLWINDOW
                return True
            cls = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, cls, 256)
            if cls.value.lower() in _IGNORED_CLASSES:
                return True
            buf = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(hwnd, buf, n + 1)
            title = buf.value.strip()
            if not title or title in ("Program Manager", "Default IME", "MSCTFIME UI"):
                return True
            visible = bool(user32.IsWindowVisible(hwnd))
            if not visible:
                if user32.GetWindow(hwnd, 4):                      # GW_OWNER: owned popups are not main windows
                    return True
                rect = wintypes.RECT()
                if not user32.GetWindowRect(hwnd, ctypes.byref(rect)) or (rect.right - rect.left) < 300 or (rect.bottom - rect.top) < 200:
                    return True
            found.append({"hwnd": int(hwnd or 0), "title": title, "pid": int(pid.value), "visible": visible, "iconic": bool(user32.IsIconic(hwnd))})
        except Exception:                                          # noqa: BLE001
            pass
        return True

    user32.EnumWindows(WNDENUMPROC(cb), 0)
    found.sort(key=lambda w: (not w["visible"], w["iconic"]))
    return found
