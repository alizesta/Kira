"""Monitor-aware Windows/Qt capture adapter. Raw frames remain in memory only."""
from __future__ import annotations

import ctypes
import os
from dataclasses import dataclass
from ctypes import wintypes
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QApplication

CAPTURE_MAX_WIDTH = 854
CAPTURE_MAX_HEIGHT = 480
CAPTURE_JPEG_QUALITY = 68


def fit_capture_size(width: int, height: int, max_width: int = CAPTURE_MAX_WIDTH,
                     max_height: int = CAPTURE_MAX_HEIGHT) -> tuple[int, int]:
    """Fit inside configured bounds without upscaling or distortion."""
    width, height = max(1, int(width)), max(1, int(height))
    max_width, max_height = max(1, int(max_width)), max(1, int(max_height))
    scale = min(1.0, max_width / width, max_height / height)
    return max(1, round(width * scale)), max(1, round(height * scale))


def fit_capture_region(rect, screen_geometry, device_pixel_ratio=1.0):
    """Convert a physical desktop rect to a clipped DXGI output-local region."""
    left, top, right, bottom = (int(value) for value in rect)
    sx, sy, sw, sh = (int(screen_geometry.x()), int(screen_geometry.y()),
                      int(screen_geometry.width()), int(screen_geometry.height()))
    scale = max(0.5, float(device_pixel_ratio or 1.0))
    ow, oh = max(1, round(sw * scale)), max(1, round(sh * scale))
    left = max(0, min(ow, round(left - sx * scale)))
    top = max(0, min(oh, round(top - sy * scale)))
    right = max(0, min(ow, round(right - sx * scale)))
    bottom = max(0, min(oh, round(bottom - sy * scale)))
    return None if right <= left or bottom <= top else (left, top, right, bottom)


@dataclass(frozen=True)
class MonitorInfo:
    id: str
    name: str
    device_name: str
    geometry: tuple[int, int, int, int]
    primary: bool
    device_pixel_ratio: float


class DesktopCaptureService:
    """Enumerate displays and capture only a caller-approved foreground window/output."""

    def __init__(self) -> None:
        self._dxcam_camera = None
        self._dxcam_backend = None
        self._dxcam_output = None
        self._user32 = ctypes.windll.user32 if os.name == "nt" else None
        self._kernel32 = ctypes.windll.kernel32 if os.name == "nt" else None
        self._configure_windows_api()

    def _configure_windows_api(self) -> None:
        if self._user32 is None or self._kernel32 is None:
            return
        self._user32.GetForegroundWindow.restype = wintypes.HWND
        self._user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        self._user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
        self._user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        self._user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        self._user32.IsWindow.argtypes = [wintypes.HWND]
        self._kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self._kernel32.OpenProcess.restype = wintypes.HANDLE
        self._kernel32.QueryFullProcessImageNameW.argtypes = [
            wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)
        ]
        self._kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

    @property
    def user32(self):
        return self._user32

    @user32.setter
    def user32(self, value):
        self._user32 = value

    @property
    def kernel32(self):
        return self._kernel32

    @kernel32.setter
    def kernel32(self, value):
        self._kernel32 = value

    def foreground_window_info(self, *, allow_partial_identity: bool = False) -> dict[str, Any] | None:
        """Return foreground identity. Partial metadata is opt-in for monitor-only Live capture."""
        if self._user32 is None or self._kernel32 is None:
            return None
        hwnd = self._user32.GetForegroundWindow()
        if not hwnd:
            return None
        pid = wintypes.DWORD()
        self._user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            return None
        title_len = self._user32.GetWindowTextLengthW(hwnd)
        title = ctypes.create_unicode_buffer(min(max(title_len + 1, 2), 1024))
        self._user32.GetWindowTextW(hwnd, title, len(title))
        rect = wintypes.RECT()
        if not self._user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return None
        process = self._kernel32.OpenProcess(0x1000, False, pid.value)
        exe, path = "", ""
        if process:
            try:
                size = wintypes.DWORD(1024)
                buffer = ctypes.create_unicode_buffer(size.value)
                if self._kernel32.QueryFullProcessImageNameW(process, 0, buffer, ctypes.byref(size)):
                    path = buffer.value
                    exe = os.path.basename(path).lower()
            finally:
                self._kernel32.CloseHandle(process)
        title_text = title.value.strip()
        if not allow_partial_identity and (not exe or not path or not title_text):
            return None
        if allow_partial_identity and not (exe or path or title_text):
            return None
        return {
            "hwnd": int(hwnd), "pid": int(pid.value), "exe": exe, "path": path,
            "title": title_text, "rect": (rect.left, rect.top, rect.right, rect.bottom),
        }

    def _is_current_foreground(self, hwnd: int, pid: int) -> bool:
        if self._user32 is None:
            return False
        try:
            if not self._user32.IsWindow(hwnd):
                return False
            if int(self._user32.GetForegroundWindow() or 0) != int(hwnd):
                return False
            current_pid = wintypes.DWORD()
            self._user32.GetWindowThreadProcessId(hwnd, ctypes.byref(current_pid))
            return int(current_pid.value) == int(pid)
        except Exception:  # noqa: BLE001 - uncertainty fails closed
            return False

    @staticmethod
    def _qt_screens():
        return QApplication.screens(), QApplication.primaryScreen()

    @staticmethod
    def _screen_rect(screen) -> tuple[int, int, int, int]:
        geometry = screen.geometry()
        dpr = max(0.5, float(screen.devicePixelRatio() or 1.0))
        left, top = round(geometry.x() * dpr), round(geometry.y() * dpr)
        return left, top, left + round(geometry.width() * dpr), top + round(geometry.height() * dpr)

    def list_monitors(self) -> tuple[MonitorInfo, ...]:
        try:
            screens, primary = self._qt_screens()
        except Exception:  # noqa: BLE001 - display enumeration is best effort
            return ()
        result = []
        for index, screen in enumerate(screens or ()):
            try:
                device = str(screen.name() or "").strip()
                serial = str(screen.serialNumber() or "").strip()
                geometry = screen.geometry()
                result.append(MonitorInfo(
                    id=device or serial or f"screen-{index}",
                    name=device or serial or f"Display {index + 1}",
                    device_name=device,
                    geometry=(int(geometry.x()), int(geometry.y()),
                              int(geometry.width()), int(geometry.height())),
                    primary=screen is primary,
                    device_pixel_ratio=max(0.5, float(screen.devicePixelRatio() or 1.0)),
                ))
            except Exception:  # noqa: BLE001 - ignore a display removed mid-enumeration
                continue
        return tuple(result)

    def _screen_for_monitor(self, monitor_id: str | None):
        try:
            screens, primary = self._qt_screens()
        except Exception:  # noqa: BLE001
            return None
        if not screens:
            return None
        if monitor_id:
            for screen in screens:
                try:
                    if monitor_id in {str(screen.name() or ""), str(screen.serialNumber() or "")}:
                        return screen
                except Exception:
                    continue
            return None
        return primary or screens[0]

    def _monitor_for_rect(self, rect):
        left, top, right, bottom = (int(value) for value in rect)
        best, best_area = None, 0
        try:
            screens, _primary = self._qt_screens()
        except Exception:  # noqa: BLE001
            return None
        for screen in screens or ():
            sl, st, sr, sb = self._screen_rect(screen)
            area = max(0, min(right, sr) - max(left, sl)) * max(0, min(bottom, sb) - max(top, st))
            if area > best_area:
                best, best_area = screen, area
        return best

    @staticmethod
    def _dxcam_output_for_screen(screen) -> tuple[int, int] | None:
        """Map Windows DISPLAY name to DXcam's adapter/output indices."""
        try:
            from dxcam.util.io import get_output_metadata
            target = str(screen.name() or "").strip().casefold()
            for device_idx, (_adapter_name, metadata) in enumerate(get_output_metadata().items()):
                outputs = metadata[2] if isinstance(metadata, (tuple, list)) and len(metadata) > 2 else ()
                for output_idx, output in enumerate(outputs or ()):
                    name = output[0] if isinstance(output, (tuple, list)) else output
                    if str(name or "").strip().casefold() == target:
                        return device_idx, output_idx
        except Exception:  # noqa: BLE001 - DXcam metadata varies by version
            return None
        return None

    def _release_dxcam(self) -> None:
        camera, self._dxcam_camera = self._dxcam_camera, None
        self._dxcam_backend = self._dxcam_output = None
        if camera is not None:
            try:
                camera.release()
            except Exception:  # noqa: BLE001 - cleanup must not block Stop
                pass

    def release(self) -> None:
        self._release_dxcam()

    @staticmethod
    def _frame_to_pixmap(frame):
        if frame is None or getattr(frame, "ndim", 0) != 3 or frame.shape[2] != 4:
            return None
        height, width = frame.shape[:2]
        image = QImage(frame.data, width, height, int(frame.strides[0]),
                       QImage.Format.Format_ARGB32).copy()
        return None if image.isNull() else QPixmap.fromImage(image)

    def _capture_dxcam(self, screen, rect, max_width, max_height):
        try:
            import dxcam
        except Exception:  # noqa: BLE001 - QScreen remains supported
            return None
        output = self._dxcam_output_for_screen(screen)
        if output is None:
            return None
        region = fit_capture_region(
            rect, screen.geometry(), getattr(screen, "devicePixelRatio", lambda: 1.0)()
        )
        if region is None:
            return None
        backends = ([self._dxcam_backend] + [b for b in ("dxgi", "winrt") if b != self._dxcam_backend]
                    if self._dxcam_backend else ["dxgi", "winrt"])
        for backend in backends:
            try:
                if (self._dxcam_camera is None or self._dxcam_backend != backend
                        or self._dxcam_output != output):
                    self._release_dxcam()
                    options = dict(
                        device_idx=output[0], output_idx=output[1],
                        output_color="BGRA", backend=backend, processor_backend="numpy",
                    )
                    try:
                        self._dxcam_camera = dxcam.create(**options, max_buffer_len=2)
                    except TypeError:
                        self._dxcam_camera = dxcam.create(**options)
                    self._dxcam_backend, self._dxcam_output = backend, output
                pixmap = self._frame_to_pixmap(
                    self._dxcam_camera.grab(region=region, new_frame_only=False)
                )
                if pixmap is None or pixmap.isNull():
                    self._release_dxcam()
                    continue
                target = fit_capture_size(pixmap.width(), pixmap.height(), max_width, max_height)
                if pixmap.width() > target[0] or pixmap.height() > target[1]:
                    pixmap = pixmap.scaled(
                        target[0], target[1], Qt.KeepAspectRatio, Qt.FastTransformation
                    )
                return pixmap
            except Exception:  # noqa: BLE001 - try other backend, then Qt fallback
                self._release_dxcam()
        return None

    def _capture_monitor_screen(self, screen, max_width: int, max_height: int):
        if screen is None:
            return None
        pixmap = self._capture_dxcam(screen, self._screen_rect(screen), max_width, max_height)
        if pixmap is None:
            try:
                pixmap = screen.grabWindow(0)
            except Exception:  # noqa: BLE001
                return None
        if pixmap is None or pixmap.isNull():
            return None
        target = fit_capture_size(pixmap.width(), pixmap.height(), max_width, max_height)
        if pixmap.width() > target[0] or pixmap.height() > target[1]:
            pixmap = pixmap.scaled(target[0], target[1], Qt.KeepAspectRatio, Qt.FastTransformation)
        return pixmap

    def capture_monitor(self, monitor_id: str | None = None,
                        max_width: int = CAPTURE_MAX_WIDTH,
                        max_height: int = CAPTURE_MAX_HEIGHT):
        """Capture one full output. Callers must apply privacy policy before using it."""
        return self._capture_monitor_screen(
            self._screen_for_monitor(monitor_id), max_width, max_height
        )

    def capture_monitor_for_window(
        self, window_info: dict[str, Any] | None, *, monitor_id: str | None = None,
        max_width: int = CAPTURE_MAX_WIDTH, max_height: int = CAPTURE_MAX_HEIGHT,
    ):
        """Capture the complete selected/foreground monitor, only for the current HWND/PID."""
        if not isinstance(window_info, dict):
            return None
        try:
            hwnd, pid = int(window_info["hwnd"]), int(window_info["pid"])
            rect = tuple(int(value) for value in window_info["rect"])
            if len(rect) != 4 or rect[2] <= rect[0] or rect[3] <= rect[1]:
                return None
        except (KeyError, TypeError, ValueError):
            return None
        if hwnd <= 0 or pid <= 0 or not self._is_current_foreground(hwnd, pid):
            return None
        screen = self._screen_for_monitor(monitor_id) if monitor_id else self._monitor_for_rect(rect)
        return self._capture_monitor_screen(screen, max_width, max_height)

    def capture_window(self, window_info: dict[str, Any] | None, *, monitor_id: str | None = None,
                       max_width: int = CAPTURE_MAX_WIDTH, max_height: int = CAPTURE_MAX_HEIGHT):
        """Capture a foreground HWND crop on one monitor, never the surrounding desktop."""
        if not isinstance(window_info, dict):
            return None
        try:
            hwnd, pid = int(window_info["hwnd"]), int(window_info["pid"])
            rect = tuple(int(value) for value in window_info["rect"])
            if len(rect) != 4 or rect[2] <= rect[0] or rect[3] <= rect[1]:
                return None
        except (KeyError, TypeError, ValueError):
            return None
        if not self._is_current_foreground(hwnd, pid):
            return None
        screen = self._screen_for_monitor(monitor_id) if monitor_id else self._monitor_for_rect(rect)
        if screen is None:
            return None
        sl, st, sr, sb = self._screen_rect(screen)
        left, top = max(rect[0], sl), max(rect[1], st)
        right, bottom = min(rect[2], sr), min(rect[3], sb)
        if right <= left or bottom <= top:
            return None
        pixmap = self._capture_dxcam(screen, (left, top, right, bottom), max_width, max_height)
        if pixmap is None:
            try:
                pixmap = screen.grabWindow(hwnd)
                if pixmap is not None and not pixmap.isNull():
                    # QScreen can return the full HWND; crop it to the selected display intersection.
                    sx = pixmap.width() / max(1, rect[2] - rect[0])
                    sy = pixmap.height() / max(1, rect[3] - rect[1])
                    pixmap = pixmap.copy(
                        max(0, round((left - rect[0]) * sx)),
                        max(0, round((top - rect[1]) * sy)),
                        max(1, round((right - left) * sx)),
                        max(1, round((bottom - top) * sy)),
                    )
            except Exception:  # noqa: BLE001
                return None
        if pixmap is None or pixmap.isNull():
            return None
        target = fit_capture_size(pixmap.width(), pixmap.height(), max_width, max_height)
        if pixmap.width() > target[0] or pixmap.height() > target[1]:
            pixmap = pixmap.scaled(target[0], target[1], Qt.KeepAspectRatio, Qt.FastTransformation)
        return pixmap
