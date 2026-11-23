"""Visible-avatar FPS policy: 60 FPS on-screen and 5 FPS while hidden."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest

try:
    from PySide6.QtWidgets import QApplication, QWidget
    from kira.face import AvatarView, FaceAnimator
    HAVE_QT = True
except ImportError:  # pragma: no cover - portable runs may not install Qt
    HAVE_QT = False


@unittest.skipUnless(HAVE_QT, "PySide6 is required for avatar FPS tests")
class AvatarFrameRateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.animator = FaceAnimator()
        self.animator._timer.stop()
        self.windows = []

    def tearDown(self):
        self.animator._timer.stop()
        for window in self.windows:
            window.close()
            window.deleteLater()
        self.app.processEvents()

    def _window_with_avatar(self):
        window = QWidget()
        window.resize(320, 240)
        AvatarView(self.animator, parent=window)
        self.windows.append(window)
        return window

    def test_avatar_runs_at_60_fps_when_visible_and_5_when_hidden(self):
        window = self._window_with_avatar()

        self.assertEqual(self.animator.animation_fps, 5)
        self.assertEqual(self.animator._timer.interval(), 200)

        window.show()
        self.app.processEvents()
        self.assertEqual(self.animator.animation_fps, 60)
        self.assertEqual(self.animator._timer.interval(), 16)

        window.hide()
        self.app.processEvents()
        self.assertEqual(self.animator.animation_fps, 5)
        self.assertEqual(self.animator._timer.interval(), 200)

    def test_avatar_views_share_rig_transforms_until_next_tick(self):
        calls = []
        original_affine = self.animator.rig.affine

        def counted_affine(x, y, e=14.0):
            calls.append(None)
            return original_affine(x, y, e)

        self.animator.rig.affine = counted_affine
        try:
            tile_result = self.animator._tile_affine()
            self.assertIs(self.animator._tile_affine(), tile_result)
            face_result = self.animator._face_affine()
            self.assertIs(self.animator._face_affine(), face_result)
            self.assertEqual(len(calls), 2)

            self.animator._tick()

            self.assertIsNot(self.animator._tile_affine(), tile_result)
            self.assertIsNot(self.animator._face_affine(), face_result)
            self.assertEqual(len(calls), 4)
        finally:
            self.animator.rig.affine = original_affine

    def test_one_visible_avatar_keeps_full_rate_when_another_is_hidden(self):
        first = self._window_with_avatar()
        second = self._window_with_avatar()

        first.show()
        second.show()
        self.app.processEvents()
        self.assertEqual(self.animator.animation_fps, 60)

        first.hide()
        self.app.processEvents()
        self.assertEqual(self.animator.animation_fps, 60)

        second.hide()
        self.app.processEvents()
        self.assertEqual(self.animator.animation_fps, 5)


if __name__ == "__main__":
    unittest.main()
