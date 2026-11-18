"""Thin Qt shell; feature behavior is composed from window-scoped controllers."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QMainWindow

from ..chat_sessions import session_property, front_only_property
from .main_window_session import SessionMixin
from .main_window_voice_settings import VoiceSettingsMixin
from .main_window_character_settings import CharacterSettingsMixin
from .main_window_provider_settings import ProviderSettingsMixin
from .main_window_lifecycle import LifecycleMixin
from .main_window_attachments_vision import AttachmentsVisionMixin
from .main_window_chat import ChatMixin
from .main_window_runtime import RuntimeMixin


class MainWindow(QMainWindow):
    """Qt host and feature-controller registry; no feature mixin inheritance."""

    voice_listener_finished = Signal(object, bool, bool)

    # Session-bound state remains on the shell because it is shared by the
    # window-scoped feature controllers and the active ChatSession.
    busy = session_property("busy")
    worker = session_property("worker")
    _stream_text = session_property("_stream_text")
    _stream_pos = session_property("_stream_pos")
    _stream_dirty = session_property("_stream_dirty")
    _stream_mood = session_property("_stream_mood")
    _emotion_applied = session_property("_emotion_applied")
    _body_done = session_property("_body_done")
    _t_req = session_property("_t_req")
    _t_first = session_property("_t_first")
    _speech_live = session_property("_speech_live")
    _turn_extra = session_property("_turn_extra")
    _turn_attach_kinds = session_property("_turn_attach_kinds")
    _turn_voice = session_property("_turn_voice")
    _turn_mode = session_property("_turn_mode")
    _tool_plan = session_property("_tool_plan")
    _brain = session_property("_brain")
    _brain_user_text = session_property("_brain_user_text")
    _brain_mode_name = session_property("_brain_mode_name")
    _plain_retry = session_property("_plain_retry")
    _web_found = session_property("_web_found")
    _image_search_turn = session_property("_image_search_turn")
    _search_token = session_property("_search_token")
    _search_worker = session_property("_search_worker")
    _search_base = session_property("_search_base")
    _route_info = session_property("_route_info")
    _badge_phase = session_property("_badge_phase")
    client = session_property("client")
    chat = property(lambda self: self.cur.view)
    _stream_timer = property(lambda self: self.cur.timer)

    # Device/presentation objects are front-window resources; controllers
    # access them through this explicit shell-owned compatibility surface.
    speaker = front_only_property("speaker")
    voice_application_service = front_only_property("voice_application_service")
    director = front_only_property("director", ("parse_reply", "format_hint", "library"))
    animator = front_only_property("animator")
    bubble = front_only_property("bubble")
    status = front_only_property("status")
    gen_stop_btn = front_only_property("gen_stop_btn")
    send_btn = front_only_property("send_btn")
    input = front_only_property("input")
    voice_btn = front_only_property("voice_btn")

    def __init__(self, parent=None):
        super().__init__(parent)
        self._feature_controllers = {
            "runtime": RuntimeMixin(self),
            "chat": ChatMixin(self),
            "attachments_vision": AttachmentsVisionMixin(self),
            "lifecycle": LifecycleMixin(self),
            "provider_settings": ProviderSettingsMixin(self),
            "character_settings": CharacterSettingsMixin(self),
            "voice_settings": VoiceSettingsMixin(self),
            "session": SessionMixin(self),
        }

    def __getattr__(self, name):
        controllers = self.__dict__.get("_feature_controllers", {})
        for controller in controllers.values():
            if name in type(controller).__dict__:
                return getattr(controller, name)
        raise AttributeError(f"{type(self).__name__!s} has no attribute {name!r}")

    def _dispatch_qt_event(self, controller_name, event_name, event):
        controller = self.__dict__.get("_feature_controllers", {}).get(controller_name)
        if controller is not None:
            return getattr(controller, event_name)(event)
        base_handler = getattr(QMainWindow, event_name, None)
        if base_handler is not None:
            return base_handler(self, event)
        return None

    # Qt virtual events are explicit shell responsibilities and are forwarded
    # to the relevant feature controller.
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

    @property
    def listener(self):
        service = getattr(self, "voice_application_service", None)
        return service.listener if service is not None else None

    @property
    def _stopping_listener(self):
        service = getattr(self, "voice_application_service", None)
        return service.stopping_listener if service is not None else None
