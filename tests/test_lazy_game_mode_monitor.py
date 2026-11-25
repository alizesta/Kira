"""Regression tests for lazy Game Mode loading and resource cleanup."""
from __future__ import annotations

import unittest

from kira.ui.lazy_game_mode_monitor import LazyGameModeMonitor


class FakeSignal:
    def __init__(self):
        self._callbacks = []

    def connect(self, callback):
        self._callbacks.append(callback)

    def emit(self, value):
        for callback in tuple(self._callbacks):
            callback(value)


class FakeCaptureService:
    def __init__(self):
        self.releases = 0

    def release(self):
        self.releases += 1


class FakeGameModeMonitor:
    def __init__(self):
        self.game_detected = FakeSignal()
        self.capture_service = FakeCaptureService()
        self.last_game = None
        self.enabled = False
        self.poll_count = 0

    def poll(self):
        self.poll_count += 1

    def set_enabled(self, enabled):
        self.enabled = bool(enabled)
        if not self.enabled:
            self.last_game = None
            self.capture_service.release()


class LazyGameModeMonitorTests(unittest.TestCase):
    def test_cold_disable_and_shutdown_do_not_construct_monitor(self):
        created = []
        monitor = LazyGameModeMonitor(factory=lambda: created.append(FakeGameModeMonitor()) or created[-1])

        monitor.set_enabled(False)
        self.assertEqual(created, [])
        self.assertIsNone(monitor.last_game)
        monitor.dispose()
        monitor.dispose()
        monitor.poll()
        self.assertEqual(created, [])

    def test_first_poll_realizes_detector_and_forwards_events(self):
        created = []
        monitor = LazyGameModeMonitor(factory=lambda: created.append(FakeGameModeMonitor()) or created[-1])
        events = []
        monitor.game_detected.connect(events.append)

        monitor.poll()
        monitor.poll()
        self.assertEqual(len(created), 1)
        self.assertEqual(created[0].poll_count, 2)
        payload = {"exe": "example-game.exe"}
        created[0].game_detected.emit(payload)
        self.assertEqual(events, [payload])
        self.assertFalse(monitor.enabled)

    def test_explicit_enable_realizes_once_and_disable_releases_capture(self):
        created = []
        monitor = LazyGameModeMonitor(factory=lambda: created.append(FakeGameModeMonitor()) or created[-1])

        monitor.set_enabled(True)
        self.assertEqual(len(created), 1)
        self.assertTrue(created[0].enabled)
        self.assertTrue(monitor.enabled)

        monitor.set_enabled(False)
        self.assertFalse(created[0].enabled)
        self.assertEqual(created[0].capture_service.releases, 1)
        self.assertFalse(monitor.enabled)

    def test_capture_service_access_is_an_explicit_realization_boundary(self):
        created = []
        monitor = LazyGameModeMonitor(factory=lambda: created.append(FakeGameModeMonitor()) or created[-1])

        capture = monitor.capture_service
        self.assertEqual(len(created), 1)
        self.assertIs(capture, created[0].capture_service)

        monitor.dispose()
        self.assertEqual(capture.releases, 1)

    def test_shutdown_releases_realized_monitor_once(self):
        created = []
        monitor = LazyGameModeMonitor(factory=lambda: created.append(FakeGameModeMonitor()) or created[-1])
        monitor.poll()

        monitor.dispose()
        monitor.dispose()

        self.assertEqual(created[0].capture_service.releases, 1)
        self.assertFalse(monitor.enabled)


if __name__ == "__main__":
    unittest.main()
