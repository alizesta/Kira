"""Explicit ownership registry for window-scoped presentation controllers.

The registry is the only compatibility boundary that resolves legacy MainWindow
feature methods. Controller ownership and Qt event routing are declared here,
rather than inferred independently by the shell.
"""
from __future__ import annotations

from collections.abc import Mapping


QT_EVENT_OWNERS = {
    "showEvent": "lifecycle",
    "hideEvent": "lifecycle",
    "changeEvent": "lifecycle",
    "resizeEvent": "session",
    "closeEvent": "runtime",
    "dragEnterEvent": "attachments_vision",
    "dropEvent": "attachments_vision",
}


class FeatureControllerRegistry:
    """Own controller lookup and deterministic legacy method delegation."""

    def __init__(self, controllers: Mapping[str, object]):
        self._controllers = dict(controllers)

    def get(self, feature: str):
        return self._controllers.get(feature)

    def resolve(self, attribute: str):
        """Resolve a method declared by exactly one feature controller.

        During migration, duplicate names retain the historical first-owner
        behavior. The owner can be inspected with `owners_for` and migrated
        explicitly without changing the shell's public compatibility surface.
        """
        for controller in self._controllers.values():
            if attribute in type(controller).__dict__:
                return getattr(controller, attribute)
        raise AttributeError(attribute)

    def owners_for(self, attribute: str) -> tuple[str, ...]:
        return tuple(
            feature
            for feature, controller in self._controllers.items()
            if attribute in type(controller).__dict__
        )

    def dispatch_event(self, window, feature: str, event_name: str, event):
        controller = self.get(feature)
        if controller is not None:
            handler = getattr(controller, event_name, None)
            if handler is not None:
                return handler(event)
        # Preserve Qt's default implementation when a feature has no handler.
        from PySide6.QtWidgets import QMainWindow

        base_handler = getattr(QMainWindow, event_name, None)
        if base_handler is not None:
            return base_handler(window, event)
        return None

    def __contains__(self, feature: str) -> bool:
        return feature in self._controllers

    def __iter__(self):
        return iter(self._controllers)
