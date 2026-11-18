"""Explicit ownership registry and Qt event routing for presentation controllers."""
from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType


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
    """Own immutable controller membership and deterministic feature lookup."""

    def __init__(self, controllers: Mapping[str, object]):
        # Copy before wrapping so callers cannot mutate registry membership by
        # retaining and changing the dictionary passed to the constructor.
        self._controllers = MappingProxyType(dict(controllers))

    def get(self, feature: str):
        """Return a controller when present, otherwise None."""
        return self._controllers.get(feature)

    def require(self, feature: str):
        """Return a registered controller or fail at the dependency boundary."""
        controller = self.get(feature)
        if controller is None:
            raise LookupError(f"Feature controller {feature!r} is not registered")
        return controller

    def owners_for(self, attribute: str) -> tuple[str, ...]:
        return tuple(
            feature
            for feature, controller in self._controllers.items()
            if attribute in type(controller).__dict__
        )

    def dispatch_event(self, window, feature: str, event_name: str, event):
        expected_owner = QT_EVENT_OWNERS.get(event_name)
        if expected_owner is not None and feature != expected_owner:
            raise ValueError(
                f"{event_name} belongs to {expected_owner!r}, not {feature!r}"
            )
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
