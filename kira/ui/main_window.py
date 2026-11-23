"""Thin Qt host with lazy, feature-scoped controller construction."""
from __future__ import annotations

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import QMainWindow

INPUT_HINT_INTERVAL_MS = 25000


class MainWindow(QMainWindow):
    """Qt host that owns the feature registry and typed presentation context."""

    voice_listener_finished = Signal(object, bool, bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        from .feature_controller_registry import FeatureControllerRegistry
        from .window_presentation_context import WindowPresentationContext

        def controller_factory(module_name: str, class_name: str):
            def create():
                from importlib import import_module

                module = import_module(f".{module_name}", __package__)
                return getattr(module, class_name)(self)
            return create

        controllers = {
            "runtime": controller_factory("main_window_runtime", "RuntimeController"),
            "chat": controller_factory("main_window_chat", "ChatController"),
            "attachments_vision": controller_factory("main_window_attachments_vision", "AttachmentsVisionController"),
            "lifecycle": controller_factory("main_window_lifecycle", "LifecycleController"),
            "provider_settings": controller_factory("main_window_provider_settings", "ProviderSettingsController"),
            "character_settings": controller_factory("main_window_character_settings", "CharacterSettingsController"),
            "voice_settings": controller_factory("main_window_voice_settings", "VoiceSettingsController"),
            "session": controller_factory("main_window_session", "SessionController"),
        }
        registry = FeatureControllerRegistry(controllers, lazy_factories=True)
        self.presentation_context = WindowPresentationContext(self, registry)

        from .main_window_fluid_entry import enable_main_window_fluid

        enable_main_window_fluid(self)
        self._init_input_hint_rotation()

    def _init_input_hint_rotation(self):
        """Pick a fresh character-specific example prompt periodically."""
        def refresh():
            try:
                context = self.presentation_context
                field = context.views.input
                setter = getattr(field, "set_character_placeholder", None)
                if not callable(setter) or field.toPlainText().strip():
                    return
                front = getattr(context.state, "front", None)
                setter(getattr(front, "cid", "kira"), context.services.settings.get("ui_lang", "fa"))
            except Exception:  # noqa: BLE001 - a placeholder must never break the window
                pass

        self._input_hint_timer = QTimer(self)
        self._input_hint_timer.setInterval(INPUT_HINT_INTERVAL_MS)
        self._input_hint_timer.timeout.connect(refresh)
        self._input_hint_timer.start()

    def _dispatch_qt_event(self, controller_name, event_name, event):
        context = getattr(self, "presentation_context", None)
        if context is None:
            base_handler = getattr(QMainWindow, event_name, None)
            return base_handler(self, event) if base_handler is not None else None
        return context.controllers.dispatch_event(self, controller_name, event_name, event)

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
