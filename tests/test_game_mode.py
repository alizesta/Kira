import unittest
from unittest import mock

from PySide6.QtWidgets import QApplication

from kira.game_mode import GameModeMonitor, fit_capture_region, fit_capture_size


class _Geometry:
    def __init__(self, x, y, width, height):
        self._values = (x, y, width, height)

    def x(self):
        return self._values[0]

    def y(self):
        return self._values[1]

    def width(self):
        return self._values[2]

    def height(self):
        return self._values[3]


class GameModeSafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # GameModeMonitor.poll() uses the primary screen geometry for its large-window heuristic.
        # The offscreen Windows CI runner still needs a QApplication instance for that Qt API.
        cls._app = QApplication.instance() or QApplication([])

    def test_starts_disabled(self):
        monitor = GameModeMonitor()
        self.assertFalse(monitor.enabled)

    def test_capture_is_blocked_while_disabled(self):
        monitor = GameModeMonitor()
        monitor.last_game = {"hwnd": 123}
        monitor._user32 = mock.Mock()
        self.assertIsNone(monitor.capture_last_game())
        monitor._user32.IsWindow.assert_not_called()

    def test_disabling_game_mode_clears_cached_game_window_and_releases_capture(self):
        monitor = GameModeMonitor()
        monitor.last_game = {"hwnd": 123, "pid": 456}
        camera = mock.Mock()
        monitor._dxcam_camera = camera
        monitor.set_enabled(False)
        self.assertIsNone(monitor.last_game)
        self.assertIsNone(monitor._dxcam_camera)
        camera.release.assert_called_once_with()

    def test_poll_clears_stale_game_when_foreground_is_not_a_game(self):
        monitor = GameModeMonitor()
        monitor.last_game = {"hwnd": 123, "pid": 456}
        monitor._foreground_info = mock.Mock(return_value={
            "hwnd": 789, "pid": 999999,
            "exe": "notepad.exe", "title": "Untitled - Notepad",
            "rect": (0, 0, 100, 100),
        })
        monitor.poll()
        self.assertIsNone(monitor.last_game)

    def test_capture_size_is_bounded_to_480p_and_keeps_aspect_ratio(self):
        self.assertEqual(fit_capture_size(1920, 1080), (853, 480))
        self.assertEqual(fit_capture_size(1280, 1024), (600, 480))
        self.assertEqual(fit_capture_size(640, 360), (640, 360))

    def test_capture_region_is_clipped_to_primary_output(self):
        self.assertEqual(
            fit_capture_region((-100, 50, 900, 800), _Geometry(0, 0, 800, 600)),
            (0, 50, 800, 600),
        )

    def test_capture_region_accounts_for_monitor_origin_and_dpi(self):
        self.assertEqual(
            fit_capture_region((2800, 100, 4500, 1200), _Geometry(1920, 0, 1280, 720), 1.5),
            (0, 100, 1620, 1080),
        )

    def test_capture_region_rejects_empty_intersections(self):
        self.assertIsNone(
            fit_capture_region((900, 700, 1000, 800), _Geometry(0, 0, 800, 600))
        )

    def test_poll_ignores_ai1_own_process_even_when_window_is_large(self):
        import os
        monitor = GameModeMonitor()
        monitor._foreground_info = mock.Mock(return_value={
            "hwnd": 123, "pid": os.getpid(),
            "exe": "python.exe", "title": "Project Kira 1 stable",
            "rect": (0, 0, 1920, 1080),
        })
        detected = mock.Mock()
        monitor.game_detected.connect(detected)
        monitor.poll()
        self.assertIsNone(monitor.last_game)
        detected.assert_not_called()

    def test_poll_ignores_ai1_title_even_if_reported_pid_differs(self):
        monitor = GameModeMonitor()
        monitor._foreground_info = mock.Mock(return_value={
            "hwnd": 123, "pid": 999999,
            "exe": "python.exe", "title": "Project Kira 1 stable",
            "rect": (0, 0, 1920, 1080),
        })
        detected = mock.Mock()
        monitor.game_detected.connect(detected)
        monitor.poll()
        self.assertIsNone(monitor.last_game)
        detected.assert_not_called()

    def test_poll_still_detects_a_large_non_ai1_window(self):
        monitor = GameModeMonitor()
        monitor._foreground_info = mock.Mock(return_value={
            "hwnd": 456, "pid": 999999,
            "exe": "game.exe", "title": "Some Game",
            "rect": (0, 0, 1920, 1080),
        })
        detected = mock.Mock()
        monitor.game_detected.connect(detected)
        monitor.poll()
        self.assertEqual(monitor.last_game["pid"], 999999)
        detected.assert_called_once()

    def test_poll_is_safe_without_windows_api(self):
        monitor = GameModeMonitor()
        monitor._user32 = None
        monitor._kernel32 = None
        monitor.poll()
        self.assertIsNone(monitor.last_game)


if __name__ == "__main__":
    unittest.main()
