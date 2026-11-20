"""Capture Python, logging and Qt diagnostics in Kira's in-app log tab."""
from __future__ import annotations

import logging
import sys
import threading
from collections import deque

from PySide6.QtCore import QObject, Signal, QtMsgType, qInstallMessageHandler
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget


class _LineStream:
    """Tee text writes to the original console and the thread-safe Qt signal."""

    def __init__(self, original, capture, label: str):
        self._original = original
        self._capture = capture
        self._label = label
        self._pending = ""
        self._lock = threading.Lock()
        self.encoding = getattr(original, "encoding", "utf-8")
        self.errors = getattr(original, "errors", "replace")

    def write(self, value):
        if not isinstance(value, str):
            value = str(value)
        written = self._original.write(value) if self._original is not None else len(value)
        with self._lock:
            self._pending += value
            parts = self._pending.splitlines(keepends=True)
            self._pending = ""
            if parts and not parts[-1].endswith(("\\n", "\\r")):
                self._pending = parts.pop()
        for part in parts:
            line = part.rstrip("\\r\\n")
            if line:
                self._capture.write_line(f"{self._label}{line}")
        return written if written is not None else len(value)

    def flush(self):
        if self._original is not None:
            self._original.flush()
        with self._lock:
            pending, self._pending = self._pending, ""
        if pending:
            self._capture.write_line(f"{self._label}{pending}")

    def isatty(self):
        return bool(self._original and self._original.isatty())

    def fileno(self):
        if self._original is None:
            raise OSError("underlying stream is unavailable")
        return self._original.fileno()

    def writable(self):
        return True


class _QtLogHandler(logging.Handler):
    def __init__(self, capture):
        super().__init__()
        self._capture = capture
        self.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s", "%H:%M:%S"))

    def emit(self, record):
        try:
            self._capture.write_line(self.format(record))
        except Exception:
            self.handleError(record)


class ConsoleLogCapture(QObject):
    """Tee console output into a bounded UI log without crossing Qt thread affinity."""

    line_ready = Signal(str)

    def __init__(self):
        super().__init__()
        self._widget = None
        self._backlog = deque(maxlen=1500)
        self._original_stdout = sys.stdout
        self._original_stderr = sys.stderr
        self._stdout = _LineStream(self._original_stdout, self, "")
        self._stderr = _LineStream(self._original_stderr, self, "[stderr] ")
        self._handler = _QtLogHandler(self)
        self._previous_qt_handler = None
        self._installed = False
        self.line_ready.connect(self._append_line)

    def install(self):
        if self._installed:
            return
        sys.stdout = self._stdout
        sys.stderr = self._stderr
        logging.getLogger().addHandler(self._handler)
        self._previous_qt_handler = qInstallMessageHandler(self._handle_qt_message)
        self._installed = True

    def attach(self, widget: QPlainTextEdit):
        self._widget = widget
        for line in self._backlog:
            widget.appendPlainText(line)
        self._backlog.clear()

    def write_line(self, line: str):
        self.line_ready.emit(str(line))

    def _append_line(self, line: str):
        if self._widget is None:
            self._backlog.append(line)
            return
        self._widget.appendPlainText(line)

    def _handle_qt_message(self, message_type, context, message):
        labels = {
            QtMsgType.QtDebugMsg: "DEBUG",
            QtMsgType.QtInfoMsg: "INFO",
            QtMsgType.QtWarningMsg: "WARNING",
            QtMsgType.QtCriticalMsg: "CRITICAL",
            QtMsgType.QtFatalMsg: "FATAL",
        }
        label = labels.get(message_type, "QT")
        category = getattr(context, "category", "") or "qt"
        self.write_line(f"{label} {category}: {message}")
        previous = self._previous_qt_handler
        if previous is not None:
            previous(message_type, context, message)

    def restore(self):
        if not self._installed:
            return
        self._stdout.flush()
        self._stderr.flush()
        if sys.stdout is self._stdout:
            sys.stdout = self._original_stdout
        if sys.stderr is self._stderr:
            sys.stderr = self._original_stderr
        logging.getLogger().removeHandler(self._handler)
        qInstallMessageHandler(self._previous_qt_handler)
        self._installed = False


def build_console_log_page(capture: ConsoleLogCapture, parent=None):
    """Build the in-app console page and attach the capture stream."""
    page = QWidget(parent)
    layout = QVBoxLayout(page)
    toolbar = QHBoxLayout()
    title = QLabel("Runtime log", page)
    clear_button = QPushButton("Clear", page)
    toolbar.addWidget(title)
    toolbar.addStretch(1)
    toolbar.addWidget(clear_button)
    output = QPlainTextEdit(page)
    output.setObjectName("runtimeLogOutput")
    output.setReadOnly(True)
    output.setMaximumBlockCount(5000)
    output.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
    clear_button.clicked.connect(output.clear)
    layout.addLayout(toolbar)
    layout.addWidget(output, 1)
    capture.attach(output)
    page.setObjectName("runtimeLogPage")
    return page
