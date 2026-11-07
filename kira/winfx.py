"""Windows 11 window effects (Mica / Acrylic) through the DWM. Every call is a safe no-op elsewhere."""
import ctypes
import sys

EFFECTS = ("off", "mica", "acrylic")
_DWMWA_USE_IMMERSIVE_DARK_MODE = 20
_DWMWA_WINDOW_CORNER_PREFERENCE = 33
_DWMWA_SYSTEMBACKDROP_TYPE = 38
_BACKDROP = {"off": 1, "mica": 2, "acrylic": 3}          # DWM_SYSTEMBACKDROP_TYPE: none / Mica / Acrylic (transient window)
_ROUND = 2                                               # DWMWCP_ROUND


class _Margins(ctypes.Structure):
    _fields_ = [("l", ctypes.c_int), ("r", ctypes.c_int), ("t", ctypes.c_int), ("b", ctypes.c_int)]


def windows_build():
    return sys.getwindowsversion().build if sys.platform == "win32" else 0


def supported():
    """System backdrops need Windows 11 22H2 (build 22621) or newer."""
    return windows_build() >= 22621


def active_effect(setting):
    """The effect that will really be used for a saved setting value."""
    setting = setting if setting in EFFECTS else "acrylic"
    return setting if supported() else "off"


def apply_effect(hwnd, effect):
    """Apply (or remove) the backdrop on a native window handle. Returns True when the DWM accepted it."""
    if not supported():
        return False
    try:
        dwm = ctypes.windll.dwmapi
        hwnd = ctypes.c_void_p(int(hwnd))
        for attr, value in ((_DWMWA_USE_IMMERSIVE_DARK_MODE, 1), (_DWMWA_WINDOW_CORNER_PREFERENCE, _ROUND),
                            (_DWMWA_SYSTEMBACKDROP_TYPE, _BACKDROP.get(effect, 1))):
            dwm.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(ctypes.c_int(value)), ctypes.sizeof(ctypes.c_int))
        margin = -1 if effect in ("mica", "acrylic") else 0          # extend the glass over the whole client area
        dwm.DwmExtendFrameIntoClientArea(hwnd, ctypes.byref(_Margins(margin, margin, margin, margin)))
        return True
    except Exception:                                                  # noqa: BLE001 - cosmetic only, never break the app
        return False
