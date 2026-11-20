"""Regression tests for the in-app console log capture."""
from __future__ import annotations

import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QPlainTextEdit

from kira.ui.console_log import ConsoleLogCapture


class ConsoleLogCaptureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_stdout_is_tee_captured_before_page_is_attached(self):
        capture = ConsoleLogCapture()
        original_stdout = sys.stdout
        try:
            capture.install()
            sys.stdout.write("startup console marker\n")
            output = QPlainTextEdit()
            capture.attach(output)
            self.assertIn("startup console marker", output.toPlainText())
        finally:
            capture.restore()
        self.assertIs(sys.stdout, original_stdout)

    def test_logging_records_are_added_to_attached_page(self):
        import logging

        capture = ConsoleLogCapture()
        output = QPlainTextEdit()
        capture.attach(output)
        try:
            capture.install()
            logging.getLogger("kira.test").warning("runtime log marker")
            self.assertIn("runtime log marker", output.toPlainText())
        finally:
            capture.restore()


if __name__ == "__main__":
    unittest.main()
