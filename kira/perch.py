"""Where the desktop companion can sit: window title bars, the taskbar, the screen floor.

Pure geometry (``visible_top_edges``, ``landing_surface``, ``place_sitting``) is separated from the Windows lookup
(``windows_rects``) so it can be tested anywhere. All numbers are in the same pixel space (Qt logical pixels): the caller converts
physical Win32 rectangles with the screen's devicePixelRatio.
"""
from __future__ import annotations

import ctypes
import sys
from dataclasses import dataclass

# Fractions of the companion window's height, measured on the standing Kira VRM; tune here if another model sits too high / low.
FEET_FRACTION = 0.97         # feet when standing
SIT_HIP_FRACTION = 0.71      # hips when sitting (the hips drop by one thigh length)
MIN_WINDOW_W, MIN_WINDOW_H = 160, 80


@dataclass(frozen=True)
class Rect:
    handle: int
    left: int
    top: int
    right: int
    bottom: int


@dataclass(frozen=True)
class Surface:
    left: int
    right: int
    y: int
    kind: str          # "window" | "taskbar" | "floor"
    handle: int = 0


def visible_top_edges(rects: list[Rect], screen_top: int = 0) -> list[Surface]:
    """Top edges that nothing covers. ``rects`` are in z-order, topmost first. A window whose top edge is partly hidden
    behind a window above it only offers the visible part."""
    surfaces: list[Surface] = []
    for index, rect in enumerate(rects):
        if rect.right - rect.left < MIN_WINDOW_W or rect.bottom - rect.top < MIN_WINDOW_H or rect.top <= screen_top:
            continue
        segments = [(rect.left, rect.right)]
        for above in rects[:index]:
            if above.top <= rect.top < above.bottom:           # covers the row of this top edge
                segments = _subtract(segments, above.left, above.right)
        for left, right in segments:
            if right - left >= MIN_WINDOW_W // 2:
                surfaces.append(Surface(left, right, rect.top, "window", rect.handle))
    return surfaces


def _subtract(segments, cut_left, cut_right):
    out = []
    for left, right in segments:
        if cut_right <= left or cut_left >= right:
            out.append((left, right))
            continue
        if cut_left > left:
            out.append((left, cut_left))
        if cut_right < right:
            out.append((cut_right, right))
    return out


def landing_surface(feet_x: float, feet_y: float, surfaces: list[Surface], floor: Surface, slack: float = 6.0) -> Surface:
    """The first surface a falling character meets: the highest one below the feet that is under the feet's x. The floor always catches."""
    best = floor
    for surface in surfaces:
        if surface.left <= feet_x <= surface.right and surface.y >= feet_y - slack and surface.y < best.y:
            best = surface
    return best


def place_sitting(window_w: int, window_h: int, feet_x: float, surface: Surface) -> tuple[int, int]:
    """Top-left of a window that sits on ``surface`` with the hips on its edge and the legs hanging in front."""
    x = int(feet_x - window_w / 2)
    x = max(surface.left - window_w // 3, min(surface.right - 2 * window_w // 3, x))        # at least a third of her stays over the edge
    return x, int(surface.y - SIT_HIP_FRACTION * window_h)


def feet_position(x: int, y: int, window_w: int, window_h: int) -> tuple[float, float]:
    return x + window_w / 2, y + FEET_FRACTION * window_h


def hips_y(y: int, window_h: int) -> float:
    return y + SIT_HIP_FRACTION * window_h


# ---------------------------------------------------------------- Windows lookup
def windows_rects(exclude: tuple[int, ...] = ()) -> list[Rect]:
    """Visible, restored, titled top-level windows in z-order (topmost first), physical pixels. Empty list off Windows."""
    if sys.platform != "win32":
        return []
    try:
        user32, dwmapi = ctypes.windll.user32, ctypes.windll.dwmapi
        from ctypes import wintypes
    except Exception:                                   # noqa: BLE001
        return []
    found: list[Rect] = []
    skip = {int(h) for h in exclude}
    rect, cloaked = wintypes.RECT(), ctypes.c_int(0)
    GWL_EXSTYLE, WS_EX_TOOLWINDOW, WS_EX_NOACTIVATE = -20, 0x80, 0x08000000

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def callback(hwnd, _lparam):
        handle = int(hwnd or 0)
        if handle in skip or not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
            return True
        if user32.GetWindowTextLengthW(hwnd) == 0:
            return True
        if user32.GetWindowLongW(hwnd, GWL_EXSTYLE) & (WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE):
            return True
        dwmapi.DwmGetWindowAttribute(hwnd, 14, ctypes.byref(cloaked), ctypes.sizeof(cloaked))      # DWMWA_CLOAKED (other virtual desktop, UWP shell)
        if cloaked.value:
            return True
        if dwmapi.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(rect), ctypes.sizeof(rect)) != 0:    # DWMWA_EXTENDED_FRAME_BOUNDS: no shadow margin
            if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                return True
        found.append(Rect(handle, rect.left, rect.top, rect.right, rect.bottom))
        return True

    try:
        user32.EnumWindows(callback, 0)
    except Exception:                                   # noqa: BLE001 - perching is a bonus, never an error
        return []
    return found


def place_standing(window_w: int, window_h: int, feet_x: float, surface: Surface) -> tuple[int, int]:
    """Top-left of a window whose character stands (feet on the edge), e.g. to dance."""
    x, _ = place_sitting(window_w, window_h, feet_x, surface)
    return x, int(surface.y - FEET_FRACTION * window_h)
