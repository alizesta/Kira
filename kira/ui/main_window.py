"""Thin Qt host; feature methods and presentation state live outside the shell."""
from __future__ import annotations

from PySide6.QtCore import QTimer, Signal
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
from kira.ui.main_window_fluid_entry import enable_main_window_fluid
from kira.ui.pages._pages_finalizer_entry import apply_all_page_finalizers

INPUT_HINT_INTERVAL_MS = 25000


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

        # Apply responsive sizing after the controller graph and its view registry exist.
        enable_main_window_fluid(self)
        views = self.presentation_context.views
        page_fields = {
            "appearance": "appearance_page",
            "assistant": "assistant_page",
            "characters": "character_page",
            "help": "help_page",
            "preferences": "preferences_page",
            "skills": "skills_page",
            "voice": "voice_page",
        }
        pages = {
            key: getattr(views, field)
            for key, field in page_fields.items()
            if field in views
        }
        apply_all_page_finalizers(pages)
        self._init_input_hint_rotation()

    def _init_input_hint_rotation(self):
        """Pick a fresh character-specific example prompt every so often (also set on character switch/retranslate)."""
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
