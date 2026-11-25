"""Start Kira with Windows (per-user Run key; no admin rights). Qt-free and injectable for tests."""
from __future__ import annotations

import sys
from pathlib import Path

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "ProjectKira"
AUTOSTART_ARG = "autostart"          # start_kira.vbs turns this into KIRA_AUTOSTART=1 so the app starts hidden in the tray


def launcher_command(root: Path | str | None = None) -> str:
    base = Path(root) if root else Path(__file__).resolve().parents[1]
    return f'wscript.exe "{base / "start_kira.vbs"}" {AUTOSTART_ARG}'


def _registry(winreg_module=None):
    if winreg_module is not None:
        return winreg_module
    if not sys.platform.startswith("win"):
        return None
    import winreg                                                         # noqa: PLC0415 - Windows only
    return winreg


def is_enabled(winreg_module=None) -> bool:
    reg = _registry(winreg_module)
    if reg is None:
        return False
    try:
        with reg.OpenKey(reg.HKEY_CURRENT_USER, RUN_KEY, 0, reg.KEY_READ) as key:
            return bool(str(reg.QueryValueEx(key, VALUE_NAME)[0]).strip())
    except OSError:
        return False


def set_enabled(enabled: bool, *, command: str | None = None, winreg_module=None) -> bool:
    """Add/refresh or remove the Run entry. Returns True when the registry now matches `enabled`; never raises."""
    reg = _registry(winreg_module)
    if reg is None:
        return False
    try:
        with reg.OpenKey(reg.HKEY_CURRENT_USER, RUN_KEY, 0, reg.KEY_SET_VALUE | reg.KEY_READ) as key:
            if enabled:
                reg.SetValueEx(key, VALUE_NAME, 0, reg.REG_SZ, command or launcher_command())
            else:
                try:
                    reg.DeleteValue(key, VALUE_NAME)
                except FileNotFoundError:
                    pass
        return True
    except OSError:
        return False
