"""Manual Game Mode and foreground-game detection for Ai1.

Detection is advisory only. It never enables Game Mode or captures a frame by itself.
Screen capture is available only while the user has manually enabled Game Mode.
"""
from __future__ import annotations

import ctypes
import os
import re
from ctypes import wintypes

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication

_NON_GAME = {
    "explorer.exe", "dwm.exe", "applicationframehost.exe", "searchhost.exe",
    "startmenuexperiencehost.exe", "shellexperiencehost.exe", "textinputhost.exe",
    "chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe",
    "code.exe", "devenv.exe", "pycharm64.exe", "notepad.exe", "notepad++.exe",
    "discord.exe", "slack.exe", "teams.exe", "steam.exe", "steamwebhelper.exe",
    "epicgameslauncher.exe", "epicwebhelper.exe", "gog galaxy.exe",
    "battle.net.exe", "upc.exe", "ubisoftconnect.exe", "eadesktop.exe",
    "riotclientservices.exe", "riotclientux.exe", "xboxpcapp.exe",
}
_GAME_HINTS = re.compile(
    r"(game|shipping|win64|win32|client[-_ ]?win64|"
    r"eldenring|elden ring|cyberpunk|valorant|league of legends|"
    r"fortnite|minecraft|gta5|witcher|steam_app)", re.I
)


class GameModeMonitor(QObject):
    game_detected = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.enabled = False
        self.last_game = None
        self._seen_pids = set()
        self._user32 = ctypes.windll.user32 if os.name == "nt" else None
        self._kernel32 = ctypes.windll.kernel32 if os.name == "nt" else None
        if self._user32 is not None:
            self._user32.GetForegroundWindow.restype = wintypes.HWND
            self._user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
            self._user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
            self._user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
            self._user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
            self._user32.IsWindow.argtypes = [wintypes.HWND]
            self._kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            self._kernel32.OpenProcess.restype = wintypes.HANDLE
            self._kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                                                   ctypes.POINTER(wintypes.DWORD)]
            self._kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

    def _foreground_info(self):
        if self._user32 is None:
            return None
        hwnd = self._user32.GetForegroundWindow()
        if not hwnd:
            return None
        pid = wintypes.DWORD()
        self._user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            return None
        title_len = self._user32.GetWindowTextLengthW(hwnd)
        title_buf = ctypes.create_unicode_buffer(min(max(title_len + 1, 2), 1024))
        self._user32.GetWindowTextW(hwnd, title_buf, len(title_buf))
        rect = wintypes.RECT()
        if not self._user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return None
        process = self._kernel32.OpenProcess(0x1000, False, pid.value)
        exe = ""
        if process:
            try:
                size = wintypes.DWORD(1024)
                buf = ctypes.create_unicode_buffer(size.value)
                if self._kernel32.QueryFullProcessImageNameW(process, 0, buf, ctypes.byref(size)):
                    exe = os.path.basename(buf.value).lower()
            finally:
                self._kernel32.CloseHandle(process)
        return {"hwnd": int(hwnd), "pid": int(pid.value), "exe": exe,
                "title": title_buf.value.strip(), "rect": (rect.left, rect.top, rect.right, rect.bottom)}

    def poll(self):
        """Detect a likely game in the foreground. Emits once per process launch."""
        info = self._foreground_info()
        if not info:
            return
        exe = info["exe"]
        title = info["title"]
        if not exe or exe in _NON_GAME or not title:
            return
        left, top, right, bottom = info["rect"]
        width, height = max(0, right-left), max(0, bottom-top)
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        area = screen.geometry()
        large = width >= area.width() * 0.58 and height >= area.height() * 0.58
        hinted = bool(_GAME_HINTS.search(exe) or _GAME_HINTS.search(title))
        # Avoid treating ordinary small windows as games; large immersive windows are a useful generic signal.
        if not hinted and not large:
            return
        self.last_game = info
        if info["pid"] not in self._seen_pids:
            self._seen_pids.add(info["pid"])
            self.game_detected.emit(dict(info))

    def set_enabled(self, enabled):
        self.enabled = bool(enabled)

    def capture_last_game(self):
        """Return a PNG QPixmap for the last detected game window, only in manual Game Mode."""
        if not self.enabled or self._user32 is None or not self.last_game:
            return None
        hwnd = int(self.last_game["hwnd"])
        if not self._user32.IsWindow(hwnd):
            self.last_game = None
            return None
        current_pid = wintypes.DWORD()
        self._user32.GetWindowThreadProcessId(hwnd, ctypes.byref(current_pid))
        if int(current_pid.value) != int(self.last_game.get("pid", -1)):
            self.last_game = None
            return None
        screen = QApplication.primaryScreen()
        if screen is None:
            return None
        pixmap = screen.grabWindow(hwnd)
        return pixmap if not pixmap.isNull() else None
