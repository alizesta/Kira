"""Qt host adapter for a window-scoped feature controller.

Controllers retain QObject lifetime/thread affinity, but no longer proxy
arbitrary reads or writes to MainWindow. Shared presentation dependencies are
available only through WindowPresentationContext.
"""
from __future__ import annotations

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QMainWindow


class WindowFeatureController(QObject):
    """Bind feature behavior to a Qt host and its explicit presentation context."""

    def __init__(self, window):
        QObject.__init__(self, window)
        self._window = window
        self._presentation_context = None

    @property
    def window(self):
        return self._window

    @property
    def context(self):
        scoped = self._presentation_context
        if scoped is not None:
            return scoped
        root = getattr(self.window, "presentation_context", None)
        if root is None:
            raise RuntimeError("WindowPresentationContext is not initialized")
        scoped = root.for_controller(self)
        self._presentation_context = scoped
        return scoped

    def feature_controller(self, feature: str):
        """Resolve only a peer explicitly granted by this controller's capability policy."""
        return self.context.require_peer(feature)

    def qt_super_event(self, event_name, event):
        """Invoke the QMainWindow implementation for a forwarded Qt event."""
        handler = getattr(QMainWindow, event_name, None)
        if handler is not None:
            handler(self.window, event)
