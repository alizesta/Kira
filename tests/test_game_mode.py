import unittest
from unittest import mock

from kira.game_mode import GameModeMonitor, fit_capture_size


class GameModeSafetyTests(unittest.TestCase):
    def test_starts_disabled(self):
        monitor = GameModeMonitor()
        self.assertFalse(monitor.enabled)

    def test_capture_is_blocked_while_disabled(self):
        monitor = GameModeMonitor()
        monitor.last_game = {"hwnd": 123}
        monitor._user32 = mock.Mock()
        self.assertIsNone(monitor.capture_last_game())
        monitor._user32.IsWindow.assert_not_called()

    def test_capture_size_is_bounded_to_480p_and_keeps_aspect_ratio(self):
        self.assertEqual(fit_capture_size(1920, 1080), (853, 480))
        self.assertEqual(fit_capture_size(1280, 1024), (600, 480))
        self.assertEqual(fit_capture_size(640, 360), (640, 360))

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
