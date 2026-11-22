""""Manual Game Mode and foreground-game detection for Ai1.

Detection is advisory only. It never enables Game Mode or captures a frame by itself.
Screen capture is available only while the user has manually enabled Game Mode.
"""
from __future__ import annotations

import ctypes
import os
import re
from ctypes import wintypes

from PySide6.QtCore import QObject, Signal, Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QApplication
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
    # Kira itself: console, interpreter, launcher and the Qt WebEngine helper of the 3D avatar are never games
    "cmd.exe", "conhost.exe", "openconsole.exe", "powershell.exe", "pwsh.exe", "windowsterminal.exe", "wt.exe",
    "python.exe", "pythonw.exe", "py.exe", "pyw.exe", "qtwebengineprocess.exe",
}
_OWN_TITLE = re.compile(r"\\b(kira|ai1)\\b", re.I)
CAPTURE_MAX_WIDTH = 854
CAPTURE_MAX_HEIGHT = 480
CAPTURE_INTERVAL_MS = 1000
CAPTURE_JPEG_QUALITY = 68


def fit_capture_size(width: int, height: int, max_width: int = CAPTURE_MAX_WIDTH,
                     max_height: int = CAPTURE_MAX_HEIGHT) -> tuple[int, int]:
    """Fit a frame inside the 480p bounds without upscaling or changing its aspect ratio."""
    width, height = max(1, int(width)), max(1, int(height))
    scale = min(1.0, max_width / width, max_height / height)
    return max(1, round(width * scale)), max(1, round(height * scale))


def fit_capture_region(rect, screen_geometry, device_pixel_ratio=1.0):
    """Convert a physical desktop window rect into a clipped DXGI output-local region."""
    left, top, right, bottom = (int(value) for value in rect)
    screen_x, screen_y, screen_width, screen_height = (
        int(screen_geometry.x()), int(screen_geometry.y()),
        int(screen_geometry.width()), int(screen_geometry.height()),
    )
    scale = max(0.5, float(device_pixel_ratio or 1.0))
    output_width = max(1, round(screen_width * scale))
    output_height = max(1, round(screen_height * scale))
    left = max(0, min(output_width, round(left - screen_x * scale)))
    top = max(0, min(output_height, round(top - screen_y * scale)))
    right = max(0, min(output_width, round(right - screen_x * scale)))
    bottom = max(0, min(output_height, round(bottom - screen_y * scale)))
    if right <= left or bottom <= top:
        return None
    return left, top, right, bottom


_GAME_HINTS = re.compile(
    r"(game|shipping|win64|win32|client[-_ ]?win64|"
    r"eldenring|elden ring|cyberpunk|valorant|league of legends|"
    r"fortnite|minecraft|gta5|witcher|steam_app)", re.I
)


def _is_own_process(info):
    """True for this process, its parents / children (venv launcher, WebEngine helpers) and anything running from the project folder."""
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
        related = {me.pid} | {p.pid for p in me.parents()} | {c.pid for c in me.children(recursive=True)}
        return pid in related
    except Exception:                                   # noqa: BLE001 - psutil is optional
        return False


class GameModeMonitor(QObject):
    game_detected = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.enabled = False
        self.last_game = None
        self._seen_pids = set()
        self._dxcam_camera = None
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
        exe, path = "", ""
        if process:
            try:
                size = wintypes.DWORD(1024)
                buf = ctypes.create_unicode_buffer(size.value)
                if self._kernel32.QueryFullProcessImageNameW(process, 0, buf, ctypes.byref(size)):
                    path = buf.value
                    exe = os.path.basename(path).lower()
            finally:
                self._kernel32.CloseHandle(process)
        return {"hwnd": int(hwnd), "pid": int(pid.value), "exe": exe, "path": path,
                "title": title_buf.value.strip(), "rect": (rect.left, rect.top, rect.right, rect.bottom)}

    def poll(self):
        """Detect a likely game in the foreground. Emits once per process launch."""
        # Never keep capturing a previously focused game after the user switches away.
        self.last_game = None
        info = self._foreground_info()
        if not info:
            return
        # Ai1's main and companion windows share this process. Exclude the
        # current process and known product window titles before game heuristics.
        if is_ai1_window(info, os.getpid()):
            return
        exe = info["exe"]
        title = info["title"]
        if not exe or exe in _NON_GAME or not title:
            return
        if _OWN_TITLE.search(title) or _is_own_process(info):
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

    def _release_dxcam(self):
        camera, self._dxcam_camera = self._dxcam_camera, None
        if camera is not None:
            try:
                camera.release()
            except Exception:  # noqa: BLE001 - cleanup must not interrupt Game Mode shutdown
                pass

    def set_enabled(self, enabled):
        self.enabled = bool(enabled)
        if not self.enabled:
            self.last_game = None
            self._release_dxcam()

    def _capture_with_dxcam(self, rect, screen, max_width, max_height):
        """Capture the foreground game through DXGI Desktop Duplication when available."""
        try:
            import dxcam
            geometry = screen.geometry()
            region = fit_capture_region(
                rect, geometry, getattr(screen, "devicePixelRatio", lambda: 1.0)()
            )
            if region is None:
                return None
            if self._dxcam_camera is None:
                # BGRA avoids OpenCV and keeps the capture path lightweight.
                self._dxcam_camera = dxcam.create(
                    output_color="BGRA",
                    backend="dxgi",
                    processor_backend="numpy",
                    max_buffer_len=2,
                )
            frame = self._dxcam_camera.grab(region=region, new_frame_only=False)
            if frame is None or getattr(frame, "ndim", 0) != 3 or frame.shape[2] != 4:
                return None
            height, width = frame.shape[:2]
            image = QImage(
                frame.data, width, height, int(frame.strides[0]),
                QImage.Format.Format_ARGB32,
            ).copy()
            if image.isNull():
                return None
            target = fit_capture_size(image.width(), image.height(), max_width, max_height)
            if image.width() > target[0] or image.height() > target[1]:
                image = image.scaled(
                    target[0], target[1], Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.FastTransformation,
                )
            return QPixmap.fromImage(image)
        except Exception:  # noqa: BLE001 - keep the legacy Qt path as a safe fallback
            self._release_dxcam()
            return None

    def capture_last_game(self, max_width=CAPTURE_MAX_WIDTH, max_height=CAPTURE_MAX_HEIGHT):
        """Return a bounded game frame; prefer DXcam and retain Qt as a fallback."""
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
        pixmap = self._capture_with_dxcam(
            self.last_game.get("rect", (0, 0, 0, 0)), screen, max_width, max_height
        )
        if pixmap is not None and not pixmap.isNull():
            return pixmap
        # Compatibility fallback for systems where DXcam is unavailable or unsupported.
        pixmap = screen.grabWindow(hwnd)
        if pixmap.isNull():
            return None
        target = fit_capture_size(pixmap.width(), pixmap.height(), max_width, max_height)
        if pixmap.width() > target[0] or pixmap.height() > target[1]:
            pixmap = pixmap.scaled(
                target[0], target[1], Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.FastTransformation,
            )
        return pixmap
"