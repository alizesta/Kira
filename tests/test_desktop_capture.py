"""Tests for monitor discovery and fail-closed capture adapter behavior."""
import ctypes
import unittest
from ctypes import wintypes
from types import SimpleNamespace
from unittest import mock

from kira.desktop_capture import DesktopCaptureService, fit_capture_region, fit_capture_size


class Geometry:
    def __init__(self, x, y, width, height):
        self.values = (x, y, width, height)
    def x(self): return self.values[0]
    def y(self): return self.values[1]
    def width(self): return self.values[2]
    def height(self): return self.values[3]


class FakeScreen:
    def __init__(self, name, geometry, primary=False):
        self._name, self._geometry, self._primary = name, Geometry(*geometry), primary
    def name(self): return self._name
    def serialNumber(self): return ""
    def geometry(self): return self._geometry
    def devicePixelRatio(self): return 1.0


class DesktopCaptureAdapterTests(unittest.TestCase):
    def test_geometry_helpers_remain_compatible(self):
        self.assertEqual(fit_capture_size(1920, 1080), (853, 480))
        self.assertEqual(fit_capture_region((-100, 50, 900, 800),
                                            Geometry(0, 0, 800, 600)),
                         (0, 50, 800, 600))

    def test_monitor_enumeration_lists_each_display(self):
        service = DesktopCaptureService()
        first = FakeScreen(r"\\.\DISPLAY1", (0, 0, 1920, 1080), True)
        second = FakeScreen(r"\\.\DISPLAY2", (1920, 0, 2560, 1440))
        service._qt_screens = mock.Mock(return_value=([first, second], first))
        monitors = service.list_monitors()
        self.assertEqual([item.id for item in monitors], [first.name(), second.name()])
        self.assertTrue(monitors[0].primary)
        self.assertFalse(monitors[1].primary)

    def test_missing_window_identity_is_rejected(self):
        self.assertIsNone(DesktopCaptureService().capture_window(None))

    def test_foreground_metadata_can_be_partial_only_for_monitor_capture(self):
        service = DesktopCaptureService.__new__(DesktopCaptureService)

        def write_pid(_hwnd, pointer):
            ctypes.cast(pointer, ctypes.POINTER(wintypes.DWORD)).contents.value = 202
            return 1

        def write_rect(_hwnd, pointer):
            rect = ctypes.cast(pointer, ctypes.POINTER(wintypes.RECT)).contents
            rect.left, rect.top, rect.right, rect.bottom = 0, 0, 1920, 1080
            return 1

        def write_title(_hwnd, buffer, _size):
            buffer.value = "Desktop"
            return 7

        service._user32 = SimpleNamespace(
            GetForegroundWindow=lambda: 101,
            GetWindowThreadProcessId=write_pid,
            GetWindowTextLengthW=lambda _hwnd: 7,
            GetWindowTextW=write_title,
            GetWindowRect=write_rect,
        )
        service._kernel32 = SimpleNamespace(OpenProcess=lambda *_args: None)

        self.assertIsNone(service.foreground_window_info())
        info = service.foreground_window_info(allow_partial_identity=True)
        self.assertEqual(info["hwnd"], 101)
        self.assertEqual(info["pid"], 202)
        self.assertEqual(info["title"], "Desktop")
        self.assertEqual(info["exe"], "")
        self.assertEqual(info["path"], "")

    def test_foreground_metadata_without_any_app_identity_still_fails_closed(self):
        service = DesktopCaptureService.__new__(DesktopCaptureService)

        def write_pid(_hwnd, pointer):
            ctypes.cast(pointer, ctypes.POINTER(wintypes.DWORD)).contents.value = 202
            return 1

        def write_rect(_hwnd, pointer):
            rect = ctypes.cast(pointer, ctypes.POINTER(wintypes.RECT)).contents
            rect.left, rect.top, rect.right, rect.bottom = 0, 0, 1920, 1080
            return 1

        service._user32 = SimpleNamespace(
            GetForegroundWindow=lambda: 101,
            GetWindowThreadProcessId=write_pid,
            GetWindowTextLengthW=lambda _hwnd: 0,
            GetWindowTextW=lambda *_args: 0,
            GetWindowRect=write_rect,
        )
        service._kernel32 = SimpleNamespace(OpenProcess=lambda *_args: None)

        self.assertIsNone(service.foreground_window_info(allow_partial_identity=True))

    def test_background_window_is_rejected_before_dxcam(self):
        service = DesktopCaptureService()
        service._is_current_foreground = mock.Mock(return_value=False)
        service._capture_dxcam = mock.Mock()
        item = {"hwnd": 10, "pid": 20, "exe": "browser.exe", "path": r"C:\Browser.exe",
                "title": "Work", "rect": (0, 0, 1280, 720)}
        self.assertIsNone(service.capture_window(item))
        service._capture_dxcam.assert_not_called()

    def test_full_monitor_capture_uses_monitor_containing_foreground_window(self):
        service = DesktopCaptureService()
        primary = FakeScreen(r"\\.\\DISPLAY1", (0, 0, 1920, 1080), True)
        secondary = FakeScreen(r"\\.\\DISPLAY2", (1920, 0, 2560, 1440))
        service._qt_screens = mock.Mock(return_value=([primary, secondary], primary))
        service._is_current_foreground = mock.Mock(return_value=True)
        service._capture_monitor_screen = mock.Mock(return_value="full-monitor")
        # Full-monitor capture only needs the current HWND/PID and monitor geometry;
        # title/executable/path may be unavailable for desktop surfaces or overlays.
        item = {"hwnd": 10, "pid": 20, "rect": (2000, 100, 3000, 900)}
        self.assertEqual(service.capture_monitor_for_window(item), "full-monitor")
        service._capture_monitor_screen.assert_called_once_with(secondary, 854, 480)

    def test_full_monitor_capture_rejects_background_window(self):
        service = DesktopCaptureService()
        service._is_current_foreground = mock.Mock(return_value=False)
        service._capture_monitor_screen = mock.Mock()
        item = {"hwnd": 10, "pid": 20, "exe": "browser.exe", "path": r"C:\Browser.exe",
                "title": "Work", "rect": (0, 0, 1280, 720)}
        self.assertIsNone(service.capture_monitor_for_window(item))
        service._capture_monitor_screen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
