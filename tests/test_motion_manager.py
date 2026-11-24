"""Focused Qt regression tests for the theme-agnostic motion manager."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest

try:
    from PySide6.QtCore import QObject, Property, Signal, QAbstractAnimation
    from PySide6.QtWidgets import QApplication
    from PySide6.QtTest import QTest
    from kira.ui.motion_manager import MotionManager, MotionTrack
    HAVE_QT = True
except ImportError:  # pragma: no cover - portable environments may omit Qt
    HAVE_QT = False


if HAVE_QT:
    class _AnimatedTarget(QObject):
        valueChanged = Signal(float)
        secondaryChanged = Signal(float)
        readOnlyChanged = Signal(float)

        def __init__(self):
            super().__init__()
            self._value = 0.0
            self._secondary = 0.0
            self._read_only = 0.0

        def _get_value(self):
            return self._value

        def _set_value(self, value):
            self._value = float(value)
            self.valueChanged.emit(self._value)

        value = Property(float, _get_value, _set_value, notify=valueChanged)

        def _get_secondary(self):
            return self._secondary

        def _set_secondary(self, value):
            self._secondary = float(value)
            self.secondaryChanged.emit(self._secondary)

        secondary = Property(float, _get_secondary, _set_secondary, notify=secondaryChanged)

        def _get_read_only(self):
            return self._read_only

        readOnly = Property(float, _get_read_only, notify=readOnlyChanged)


@unittest.skipUnless(HAVE_QT, "PySide6 is required for motion manager tests")
class MotionManagerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.manager = MotionManager()
        self.target = _AnimatedTarget()

    def tearDown(self):
        self.manager.shutdown()
        self.app.processEvents()

    def test_single_property_animation_finishes_and_releases_itself(self):
        animation = self.manager.animate(
            self.target, "value", 1.0, start_value=0.0, duration_ms=35, key="panel.fade"
        )
        self.assertEqual(animation.parent(), self.manager)
        self.assertEqual(self.manager.active_count, 1)
        self.assertTrue(self.manager.is_running("panel.fade"))

        QTest.qWait(70)

        self.assertAlmostEqual(self.target.value, 1.0, places=2)
        self.assertEqual(self.manager.active_count, 0)
        self.assertFalse(self.manager.active_keys)

    def test_reusing_a_key_cancels_the_previous_animation(self):
        first = self.manager.animate(
            self.target, "value", 1.0, start_value=0.0, duration_ms=1000, key="panel"
        )
        second = self.manager.animate(
            self.target, "value", 2.0, start_value=0.0, duration_ms=1000, key="panel"
        )

        self.assertEqual(first.state(), QAbstractAnimation.State.Stopped)
        self.assertEqual(self.manager.active_count, 1)
        self.assertEqual(self.manager.active_keys, ("panel",))
        self.assertTrue(self.manager.is_running("panel"))

        self.assertTrue(self.manager.stop("panel"))
        self.assertEqual(self.manager.active_count, 0)
        self.assertFalse(self.manager.stop("panel"))

    def test_parallel_group_animates_multiple_properties(self):
        group = self.manager.animate_group(
            (
                MotionTrack(self.target, "value", 1.0, start_value=0.0),
                MotionTrack(self.target, "secondary", 2.0, start_value=0.0),
            ),
            parallel=True,
            duration_ms=35,
            key="card.enter",
        )
        self.assertEqual(group.parent(), self.manager)
        self.assertEqual(self.manager.active_count, 1)

        QTest.qWait(70)

        self.assertAlmostEqual(self.target.value, 1.0, places=2)
        self.assertAlmostEqual(self.target.secondary, 2.0, places=2)
        self.assertEqual(self.manager.active_count, 0)

    def test_keyed_animation_can_be_paused_and_resumed(self):
        self.manager.animate(
            self.target, "value", 1.0, duration_ms=1000, key="pause.me"
        )

        self.assertTrue(self.manager.pause("pause.me"))
        self.assertFalse(self.manager.is_running("pause.me"))
        self.assertEqual(self.manager.resume_all(), 1)
        self.assertTrue(self.manager.is_running("pause.me"))
        self.assertEqual(self.manager.pause_all(), 1)
        self.assertTrue(self.manager.resume("pause.me"))

    def test_stop_all_can_apply_end_values(self):
        self.manager.animate(
            self.target, "value", 1.0, start_value=0.0, duration_ms=1000, key="one"
        )
        self.manager.animate(
            self.target, "secondary", 2.0, start_value=0.0, duration_ms=1000, key="two"
        )

        self.assertEqual(self.manager.stop_all(finish=True), 2)
        self.assertAlmostEqual(self.target.value, 1.0, places=2)
        self.assertAlmostEqual(self.target.secondary, 2.0, places=2)
        self.assertEqual(self.manager.active_count, 0)

    def test_shutdown_cancels_animations_and_rejects_new_work(self):
        self.manager.animate(
            self.target, "value", 1.0, duration_ms=1000, key="pending"
        )

        self.manager.shutdown()

        self.assertTrue(self.manager.is_shutdown)
        self.assertEqual(self.manager.active_count, 0)
        with self.assertRaises(RuntimeError):
            self.manager.animate(self.target, "value", 2.0)

    def test_unknown_and_read_only_properties_are_rejected(self):
        with self.assertRaises(ValueError):
            self.manager.animate(self.target, "missingProperty", 1.0)
        with self.assertRaises(ValueError):
            self.manager.animate(self.target, "readOnly", 1.0)


if __name__ == "__main__":
    unittest.main()
