"""Explicit ownership registry and lazy Qt feature-controller construction."""
from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Callable


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
    """Own immutable feature membership and materialize controllers on demand."""

    def __init__(
        self,
        controllers: Mapping[str, object | Callable[[], object]],
        *,
        lazy_factories: bool = False,
    ):
        snapshot = dict(controllers)
        self._lazy_factories = bool(lazy_factories)
        self._factories = (
            MappingProxyType(snapshot) if self._lazy_factories else MappingProxyType({})
        )
        self._controllers = {} if self._lazy_factories else snapshot
        self._constructing: list[str] = []

    def _materialize(self, feature: str):
        controller = self._controllers.get(feature)
        if controller is not None:
            return controller
        if not self._lazy_factories or feature not in self._factories:
            return None
        if feature in self._constructing:
            raise RuntimeError(f"Recursive feature controller construction: {feature}")
        self._constructing.append(feature)
        try:
            factory = self._factories[feature]
            if not callable(factory):
                raise TypeError(f"Lazy controller factory is not callable: {feature}")
            controller = factory()
            if controller is None:
                raise TypeError(f"Lazy controller factory returned None: {feature}")
            self._controllers[feature] = controller
            return controller
        finally:
            self._constructing.pop()

    def get(self, feature: str):
        return self._materialize(feature)

    def get_if_materialized(self, feature: str):
        """Return an existing instance without triggering its lazy factory."""
        return self._controllers.get(feature)

    def name_for(self, controller: object) -> str:
        for feature, registered in self._controllers.items():
            if registered is controller:
                return feature
        if self._constructing:
            return self._constructing[-1]
        raise LookupError("Controller instance is not registered in this presentation graph")

    def require(self, feature: str):
        controller = self.get(feature)
        if controller is None:
            raise LookupError(f"Feature controller {feature!r} is not registered")
        return controller

    def owners_for(self, attribute: str) -> tuple[str, ...]:
        """Report realized owners without forcing feature imports."""
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
        from PySide6.QtWidgets import QMainWindow

        base_handler = getattr(QMainWindow, event_name, None)
        if base_handler is not None:
            return base_handler(window, event)
        return None

    @property
    def materialized_features(self) -> tuple[str, ...]:
        return tuple(self._controllers)

    def __contains__(self, feature: str) -> bool:
        return feature in (self._factories if self._lazy_factories else self._controllers)

    def __iter__(self):
        return iter(self._factories if self._lazy_factories else self._controllers)
