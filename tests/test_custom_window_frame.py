"""Regression tests for Kira's custom frameless desktop frame."""
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QMainWindow, QToolButton
    HAVE_QT = True
except Exception:  # pragma: no cover - optional in minimal environments
    HAVE_QT = False


@unittest.skipUnless(HAVE_QT, "PySide6 not installed")
class CustomWindowFrameTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_resize_hit_test_covers_all_edges_and_corners(self):
        from kira.ui.custom_window_frame import resize_region_at

        cases = (
            ((0, 240), "left"),
            ((639, 240), "right"),
            ((320, 0), "top"),
            ((320, 479), "bottom"),
            ((0, 0), "top_left"),
            ((639, 0), "top_right"),
            ((0, 479), "bottom_left"),
            ((639, 479), "bottom_right"),
        )
        for point, expected in cases:
            with self.subTest(point=point):
                self.assertEqual(resize_region_at(*point, 640, 480), expected)

        self.assertIsNone(resize_region_at(320, 240, 640, 480))
        self.assertIsNone(resize_region_at(-1, 20, 640, 480))
        self.assertIsNone(resize_region_at(640, 20, 640, 480))

    def test_title_bar_is_attached_and_window_controls_work(self):
        from kira.ui.custom_window_frame import create_custom_title_bar

        window = QMainWindow()
        window.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        title_bar = create_custom_title_bar(window, window)
        window.setCentralWidget(title_bar)
        window.resize(640, 480)
        window.show()
        self.app.processEvents()

        self.assertTrue(window.windowFlags() & Qt.WindowType.FramelessWindowHint)
        self.assertEqual(title_bar.objectName(), "kiraCustomTitleBar")
        self.assertEqual(title_bar.height(), 40)
        self.assertEqual(
            title_bar.layout().direction(),
            QHBoxLayout.Direction.LeftToRight,
        )

        buttons = {button.toolTip(): button for button in title_bar.findChildren(QToolButton)}
        self.assertEqual(set(buttons), {"Minimize", "Maximize", "Close"})

        buttons["Maximize"].click()
        self.app.processEvents()
        self.assertTrue(window.isMaximized())

        buttons["Maximize"].click()
        self.app.processEvents()
        self.assertFalse(window.isMaximized())

        buttons["Minimize"].click()
        self.app.processEvents()
        self.assertTrue(window.isMinimized())
        window.showNormal()
        window.close()
        self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
