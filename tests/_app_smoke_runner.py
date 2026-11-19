"""Boots the real application offscreen, opens every tab and clicks every harmless button.

Run by tests/test_app_smoke.py in a subprocess with KIRA_DATA_DIR pointing at a temp folder.
Prints APP_SMOKE_ERRORS <n> followed by the collected tracebacks.
"""
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6 import QtWidgets  # noqa: E402

errors = []
sys.excepthook = lambda t, v, tb: errors.append("".join(traceback.format_exception(t, v, tb)))
SKIP = ("حذف", "delete", "نصب", "install", "دانلود", "download", "پاک", "reset", "ریست", "خروج", "quit", "mic", "میکروفون")


def pump(app, seconds):
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


def fake_exec(self=None):
    app = QtWidgets.QApplication.instance()
    for name in ("warning", "information", "question", "critical"):
        setattr(QtWidgets.QMessageBox, name, staticmethod(lambda *a, **k: QtWidgets.QMessageBox.No))
    QtWidgets.QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: ("", ""))
    QtWidgets.QFileDialog.getOpenFileNames = staticmethod(lambda *a, **k: ([], ""))
    QtWidgets.QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: ("", ""))
    QtWidgets.QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: "")
    QtWidgets.QInputDialog.getText = staticmethod(lambda *a, **k: ("", False))
    QtWidgets.QColorDialog.getColor = staticmethod(lambda *a, **k: __import__("PySide6.QtGui", fromlist=["QColor"]).QColor())
    QtWidgets.QMenu.exec = lambda *a, **k: None
    QtWidgets.QDialog.exec = lambda *a, **k: 0
    window = next(w for w in app.topLevelWidgets() if w.isVisible())
    pump(app, 2)
    for tabs in window.findChildren(QtWidgets.QTabWidget):
        for index in range(tabs.count()):
            tabs.setCurrentIndex(index)
            pump(app, 0.2)
            for button in tabs.widget(index).findChildren(QtWidgets.QAbstractButton):
                label = (button.text() or button.toolTip() or button.objectName()).lower()
                if button.isEnabled() and button.isVisible() and not any(word in label for word in SKIP):
                    button.click()
                    pump(app, 0.1)
    pump(app, 1)
    print("APP_SMOKE_ERRORS", len(errors))
    for item in errors:
        print(item)
    return 0


QtWidgets.QApplication.exec = fake_exec
from kira.ui.bootstrap import run_application  # noqa: E402

try:
    run_application()
except SystemExit:
    pass
