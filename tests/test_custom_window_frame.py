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
