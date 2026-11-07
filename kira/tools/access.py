"""Which files Kira may touch. Everything file-related goes through PathPolicy.

Allowed = inside one of the allowed folders (Desktop, Documents, Downloads, Pictures, Videos, Music of the Windows user, plus
folders the user adds in settings under "tools_allowed_paths"). Even inside them these are always refused: Kira's own data folder
(settings, API keys, chat database), AppData, the Windows folder, and anything that looks like a secret (keys, passwords, .env ...).
Paths are resolved first (symlinks / junctions / ".." are followed), then checked, so a link cannot lead outside the allowed area.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

from .registry import ToolError, DENIED

_KNOWN_FOLDERS = {                       # Windows Known Folder IDs: they also follow folders the user moved to another drive / OneDrive
    "Desktop": "B4BFCC3A-DB2C-424C-B029-7FE99A87C641",
    "Documents": "FDD39AD0-238F-46AF-ADB4-6C85480369C7",
    "Downloads": "374DE290-123F-4565-9164-39C4925E467B",
    "Pictures": "33E28130-4E1E-4676-835A-98395C3BC3BB",
    "Videos": "18989B1D-99B5-455B-841C-AB7C74E4DDFC",
    "Music": "4BD8D571-6D19-48D3-BE97-422220080E43",
}
SENSITIVE_DIR_NAMES = {".ssh", ".gnupg", ".aws", ".azure", ".kube", ".docker", ".config", "appdata", "$recycle.bin", "system volume information"}
SENSITIVE_NAME_RX = re.compile(
    r"(?i)(?:\.pem$|\.key$|\.pfx$|\.p12$|\.ppk$|\.kdbx?$|\.keystore$|\.jks$|\.gpg$|\.asc$|^id_(?:rsa|dsa|ecdsa|ed25519)|^\.env(?:\..*)?$"
    r"|^\.npmrc$|^\.netrc$|^\.git-credentials$|^cookies?(?:\.sqlite)?$|^login data$|^web data$|^local state$"
    r"|password|passwd|credential|secret|api[-_ ]?key|private[-_ ]?key|seed[-_ ]?phrase|recovery[-_ ]?code|wallet\.dat|رمز\s*عبور|پسورد|رمز\s*ورود)")
EXECUTABLE_EXT = {".exe", ".bat", ".cmd", ".com", ".scr", ".msi", ".msp", ".ps1", ".psm1", ".vbs", ".vbe", ".js", ".jse", ".wsf", ".wsh",
                  ".hta", ".reg", ".lnk", ".url", ".jar", ".dll", ".cpl", ".pif", ".gadget", ".application", ".appx", ".msix"}


def _known_folder(guid: str):
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        import uuid
        from ctypes import wintypes

        class GUID(ctypes.Structure):
            _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]

        u = uuid.UUID(guid)
        g = GUID(u.time_low, u.time_mid, u.time_hi_version, (ctypes.c_ubyte * 8)(*u.bytes[8:]))
        ptr = ctypes.c_void_p()
        shell32 = ctypes.windll.shell32
        shell32.SHGetKnownFolderPath.argtypes = [ctypes.POINTER(GUID), wintypes.DWORD, wintypes.HANDLE, ctypes.POINTER(ctypes.c_void_p)]
        if shell32.SHGetKnownFolderPath(ctypes.byref(g), 0, None, ctypes.byref(ptr)) != 0 or not ptr.value:
            return None
        path = ctypes.wstring_at(ptr.value)
        ctypes.windll.ole32.CoTaskMemFree(ptr)
        return path
    except Exception:                                              # noqa: BLE001 - fall back to %USERPROFILE%\<name>
        return None


def _norm(path) -> str:
    return os.path.normcase(os.path.realpath(os.path.expandvars(os.path.expanduser(str(path)))))


def _inside(path: str, root: str) -> bool:
    try:
        return os.path.commonpath([path, root]) == root
    except ValueError:                                              # different drives
        return False


class PathPolicy:
    def __init__(self, settings: dict | None = None, data_dir: Path | None = None, program_root: Path | None = None):
        self.settings = settings if settings is not None else {}
        self.data_dir = data_dir
        self.program_root = program_root

    # ---- the allowed area ----
    def default_roots(self) -> list[tuple[str, str]]:
        """[(label, real path)] of the standard user folders that exist."""
        home = Path.home()
        out, seen = [], set()
        for label, guid in _KNOWN_FOLDERS.items():
            for cand in (_known_folder(guid), str(home / label)):
                if cand and os.path.isdir(cand):
                    real = _norm(cand)
                    if real not in seen:
                        seen.add(real)
                        out.append((label, str(cand)))
        return out

    def extra_roots(self) -> list[str]:
        raw = self.settings.get("tools_allowed_paths") or []
        if isinstance(raw, str):
            raw = [raw]
        out = []
        for item in raw:
            try:
                if item and os.path.isdir(os.path.expandvars(os.path.expanduser(str(item)))):
                    out.append(str(item))
            except (OSError, ValueError):
                continue
        return out

    def roots(self) -> list[str]:
        """Real (normalised) allowed folders."""
        seen, out = set(), []
        for _, p in self.default_roots():
            real = _norm(p)
            if real not in seen:
                seen.add(real)
                out.append(real)
        for p in self.extra_roots():
            real = _norm(p)
            if real not in seen:
                seen.add(real)
                out.append(real)
        return out

    def root_labels(self) -> list[str]:
        """Display paths of the allowed folders (for the model and the user)."""
        shown = [p for _, p in self.default_roots()] + self.extra_roots()
        seen, out = set(), []
        for p in shown:
            key = _norm(p)
            if key not in seen:
                seen.add(key)
                out.append(str(p))
        return out

    def _blocked_roots(self) -> list[str]:
        blocked = []
        for cand in (self.data_dir, os.environ.get("APPDATA"), os.environ.get("LOCALAPPDATA"), os.environ.get("WINDIR"),
                     os.environ.get("PROGRAMFILES"), os.environ.get("PROGRAMFILES(X86)"), os.environ.get("PROGRAMDATA")):
            if cand:
                try:
                    blocked.append(_norm(cand))
                except OSError:
                    continue
        return blocked

    # ---- checks ----
    def sensitive_name(self, path: str) -> bool:
        name = os.path.basename(str(path).rstrip("\\/"))
        return bool(SENSITIVE_NAME_RX.search(name))

    def blocked_reason(self, real: str, root: str | None = None) -> str | None:
        """Why a resolved path must not be touched (None = fine). root = the allowed folder it lies in (names ABOVE it are not judged)."""
        for b in self._blocked_roots():
            if _inside(real, b):
                return "این پوشه‌ی سیستمی یا اطلاعات خود Kira است (تنظیمات، کلیدها، گفتگوها) و در دسترس نیست."
        for part in Path(real).parts:
            if part.lower() in SENSITIVE_DIR_NAMES:
                return f"پوشه‌ی «{part}» حساس است و در دسترس نیست."
        below = Path(real).parts
        if root:
            below = below[len(Path(root).parts):]
        if any(SENSITIVE_NAME_RX.search(part) for part in below[-8:]):
            return "نام این فایل/پوشه (یا پوشه‌ی بالاسری‌اش) شبیه اطلاعات محرمانه است (کلید، رمز، .env ...) و برای حفظ حریم خصوصی باز نمی‌شود."
        return None

    def _root_of(self, real: str) -> str | None:
        best = None
        for r in self.roots():
            if _inside(real, r) and (best is None or len(r) > len(best)):
                best = r
        return best

    def is_allowed(self, path) -> bool:
        try:
            real = _norm(path)
        except (OSError, ValueError):
            return False
        root = self._root_of(real)
        return root is not None and self.blocked_reason(real, root) is None

    def check(self, path, must_exist: bool = True) -> str:
        """Resolved absolute path if Kira may use it; otherwise ToolError(denied) with the real reason."""
        if not str(path or "").strip():
            raise ToolError("مسیر خالی است.")
        text = os.path.expandvars(os.path.expanduser(str(path).strip().strip('"')))
        if not os.path.isabs(text):
            raise ToolError("مسیر باید کامل (مثل C:\\Users\\...) باشد. اگر مسیر را نمی‌دانی اول search_files یا list_folder را بزن.")
        real = _norm(text)
        root = self._root_of(real)
        if root is None:
            raise ToolError("این مسیر بیرون از پوشه‌های مجاز است. پوشه‌های مجاز: " + "؛ ".join(self.root_labels()) +
                            " (کاربر می‌تواند پوشه‌ی دیگری را در تنظیمات tools_allowed_paths اضافه کند).", DENIED)
        reason = self.blocked_reason(real, root)
        if reason:
            raise ToolError(reason, DENIED)
        if must_exist and not os.path.exists(real):
            raise ToolError("چنین فایل یا پوشه‌ای وجود ندارد.")
        return os.path.realpath(text)
