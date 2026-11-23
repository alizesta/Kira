"""Manual Game Mode and foreground-game detection for Ai1.

Detection is advisory only. Native capture belongs to DesktopCaptureService.
Historical names and GameModeMonitor remain compatibility exports.
"""
from __future__ import annotations

import os
import re

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from .desktop_capture import (
    CAPTURE_JPEG_QUALITY, CAPTURE_MAX_HEIGHT, CAPTURE_MAX_WIDTH,
    DesktopCaptureService, fit_capture_region, fit_capture_size,
)
from .game_detection import is_ai1_window

_NON_GAME = {
    "explorer.exe", "dwm.exe", "applicationframehost.exe", "searchhost.exe",
    "startmenuexperiencehost.exe", "shellexperiencehost.exe", "textinputhost.exe",
    "chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe",
    "code.exe", "devenv.exe", "pycharm64.exe", "notepad.exe", "notepad++.exe",
    "discord.exe", "slack.exe", "teams.exe", "steam.exe", "steamwebhelper.exe",
    "epicgameslauncher.exe", "epicwebhelper.exe", "gog galaxy.exe",
    "battle.net.exe", "upc.exe", "ubisoftconnect.exe", "eadesktop.exe",
    "riotclientservices.exe", "riotclientux.exe", "xboxpcapp.exe",
    "cmd.exe", "conhost.exe", "openconsole.exe", "powershell.exe", "pwsh.exe",
    "windowsterminal.exe", "wt.exe", "python.exe", "pythonw.exe", "py.exe",
    "pyw.exe", "qtwebengineprocess.exe",
}
_OWN_TITLE = re.compile(r"\b(kira|ai1)\b", re.I)
_GAME_HINTS = re.compile(
    r"(game|shipping|win64|win32|client[-_ ]?win64|eldenring|elden ring|"
    r"cyberpunk|valorant|league of legends|fortnite|minecraft|gta5|witcher|steam_app)",
    re.I,
)
CAPTURE_INTERVAL_MS = 1000


def _is_own_process(info):
    """True for this process, related processes, or any executable under the project folder."""
    pid = int(info.get("pid", -1))
    path = str(info.get("path") or "")
    try:
        root = os.path.normcase(os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir)))
        if path and os.path.normcase(os.path.abspath(path)).startswith(root + os.sep):
            return True
    except (OSError, ValueError):
        pass
    try:
        import psutil
        me = psutil.Process(os.getpid())
        related = ({me.pid} | {p.pid for p in me.parents()}
                   | {p.pid for p in me.children(recursive=True)})
        return pid in related
    except Exception:  # noqa: BLE001 - psutil is optional
        return False


class GameModeMonitor(QObject):
    """Foreground game detector and backwards-compatible capture facade."""

    game_detected = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.enabled = False
        self.last_game = None
        self._seen_pids = set()
        self.capture_service = DesktopCaptureService()

    @property
    def _user32(self):
        return self.capture_service.user32

    @_user32.setter
    def _user32(self, value):
        self.capture_service.user32 = value

    @property
    def _kernel32(self):
        return self.capture_service.kernel32

    @_kernel32.setter
    def _kernel32(self, value):
        self.capture_service.kernel32 = value

    @property
    def _dxcam_camera(self):
        return self.capture_service._dxcam_camera

    @_dxcam_camera.setter
    def _dxcam_camera(self, value):
        self.capture_service._dxcam_camera = value

    @property
    def _dxcam_backend(self):
        return self.capture_service._dxcam_backend

    @_dxcam_backend.setter
    def _dxcam_backend(self, value):
        self.capture_service._dxcam_backend = value

    def _foreground_info(self):
        return self.capture_service.foreground_window_info()

    def poll(self):
        """Detect a likely game in the foreground. Emits once per process launch."""
        self.last_game = None
        info = self._foreground_info()
        if not info or is_ai1_window(info, os.getpid()):
            return
        exe, title = info["exe"], info["title"]
        if not exe or exe in _NON_GAME or not title:
            return
        if _OWN_TITLE.search(title) or _is_own_process(info):
            return
        left, top, right, bottom = info["rect"]
        width, height = max(0, right - left), max(0, bottom - top)
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        geometry = screen.geometry()
        large = width >= geometry.width() * 0.58 and height >= geometry.height() * 0.58
        if not (_GAME_HINTS.search(exe) or _GAME_HINTS.search(title) or large):
            return
        self.last_game = info
        if info["pid"] not in self._seen_pids:
            self._seen_pids.add(info["pid"])
            self.game_detected.emit(dict(info))

    def _release_dxcam(self):
        self.capture_service.release()

    def set_enabled(self, enabled):
        self.enabled = bool(enabled)
        if not self.enabled:
            self.last_game = None
            self._release_dxcam()

    def _capture_with_dxcam(self, rect, screen, max_width, max_height):
        return self.capture_service._capture_dxcam(screen, rect, max_width, max_height)

    def capture_last_game(self, max_width=CAPTURE_MAX_WIDTH, max_height=CAPTURE_MAX_HEIGHT):
        if not self.enabled or self._user32 is None or not self.last_game:
            return None
        return self.capture_service.capture_window(
            self.last_game, max_width=max_width, max_height=max_height
        )
