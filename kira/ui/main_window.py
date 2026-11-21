"""Thin Qt host; feature methods and presentation state live outside the shell."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QMainWindow

from .main_window_session import SessionController
from .main_window_voice_settings import VoiceSettingsController
from .main_window_character_settings import CharacterSettingsController
from .main_window_provider_settings import ProviderSettingsController
from .main_window_lifecycle import LifecycleController
from .main_window_attachments_vision import AttachmentsVisionController
from .main_window_chat import ChatController
from .main_window_runtime import RuntimeController
from .feature_controller_registry import FeatureControllerRegistry
from .window_presentation_context import WindowPresentationContext


class MainWindow(QMainWindow):
    """Qt host that owns only the feature-controller graph and presentation context."""

    voice_listener_finished = Signal(object, bool, bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        controllers = {
            "runtime": RuntimeController(self),
            "chat": ChatController(self),
            "attachments_vision": AttachmentsVisionController(self),
            "lifecycle": LifecycleController(self),
            "provider_settings": ProviderSettingsController(self),
            "character_settings": CharacterSettingsController(self),
            "voice_settings": VoiceSettingsController(self),
            "session": SessionController(self),
        }
        registry = FeatureControllerRegistry(controllers)
        self.presentation_context = WindowPresentationContext(self, registry)

    def _dispatch_qt_event(self, controller_name, event_name, event):
        context = getattr(self, "presentation_context", None)
        if context is None:
            base_handler = getattr(QMainWindow, event_name, None)
            return base_handler(self, event) if base_handler is not None else None
        return context.controllers.dispatch_event(self, controller_name, event_name, event)

    # Qt virtual events are shell responsibilities and are forwarded to their
    # explicitly declared feature owner.
    def showEvent(self, event):
        return self._dispatch_qt_event("lifecycle", "showEvent", event)

    def hideEvent(self, event):
        return self._dispatch_qt_event("lifecycle", "hideEvent", event)

    def changeEvent(self, event):
        return self._dispatch_qt_event("lifecycle", "changeEvent", event)

    def resizeEvent(self, event):
        return self._dispatch_qt_event("session", "resizeEvent", event)

    def closeEvent(self, event):
        return self._dispatch_qt_event("runtime", "closeEvent", event)

    def dragEnterEvent(self, event):
        return self._dispatch_qt_event("attachments_vision", "dragEnterEvent", event)

    def dropEvent(self, event):
        return self._dispatch_qt_event("attachments_vision", "dropEvent", event)
