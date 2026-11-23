"""Normalize foreground-window identity already read by the Win32 capture adapter."""
from __future__ import annotations

from typing import Any


class ActiveWindowProbe:
    """Validate and normalize metadata from DesktopCaptureService.foreground_window_info()."""

    def inspect(self, window_info: dict[str, Any] | None) -> dict[str, Any] | None:
        if not isinstance(window_info, dict):
            return None
        try:
            hwnd = int(window_info.get("hwnd") or 0)
            pid = int(window_info.get("pid") or 0)
            rect = tuple(int(value) for value in window_info.get("rect", ()))
        except (TypeError, ValueError):
            return None
        exe = str(window_info.get("exe") or "").strip().lower()
        title = " ".join(str(window_info.get("title") or "").split())
        path = str(window_info.get("path") or "").strip()
        if hwnd <= 0 or pid <= 0 or len(rect) != 4 or not exe or not title or not path:
            return None
        if rect[2] <= rect[0] or rect[3] <= rect[1]:
            return None
        return {
            "hwnd": hwnd, "pid": pid, "exe": exe[:100],
            "title": title[:160], "path": path[:260], "rect": rect,
        }

    @staticmethod
    def key(window_info: dict[str, Any] | None) -> tuple[int, int] | None:
        if not isinstance(window_info, dict):
            return None
        try:
            return int(window_info["hwnd"]), int(window_info["pid"])
        except (KeyError, TypeError, ValueError):
            return None
