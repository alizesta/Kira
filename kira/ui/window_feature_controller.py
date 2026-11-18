"""Base adapter for feature controllers hosted by the desktop window.

Feature controllers keep UI behavior out of MainWindow's inheritance tree while
sharing the existing widget/state surface during the incremental migration.
"""
from __future__ import annotations

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QMainWindow


class WindowFeatureController(QObject):
    """Bind a feature's behavior to a single owning MainWindow instance."""

    def __init__(self, window):
        QObject.__init__(self, window)
        object.__setattr__(self, "_window", window)

    @property
    def window(self):
        return object.__getattribute__(self, "_window")

    def feature_controller(self, feature: str):
        """Return a named peer controller for an explicit UI workflow dependency."""
        registry = getattr(self.window, "_controller_registry", None)
        controller = registry.get(feature) if registry is not None else None
        if controller is None:
            raise LookupError(f"Feature controller {feature!r} is not registered")
        return controller

    def __getattr__(self, name):
        return getattr(self.window, name)

    def __setattr__(self, name, value):
        if name == "_window":
            object.__setattr__(self, name, value)
        else:
            setattr(self.window, name, value)

    def __delattr__(self, name):
        if name == "_window":
            raise AttributeError("feature controller ownership cannot be deleted")
        delattr(self.window, name)

    def qt_super_event(self, event_name, event):
        """Invoke the QMainWindow implementation for a forwarded Qt event."""
        handler = getattr(QMainWindow, event_name, None)
        if handler is not None:
            handler(self.window, event)
