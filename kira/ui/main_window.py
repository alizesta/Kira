"""Main desktop window composed from feature-oriented UI behavior mixins."""
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


class MainWindow(
    RuntimeMixin,
    ChatMixin,
    AttachmentsVisionMixin,
    LifecycleMixin,
    ProviderSettingsMixin,
    CharacterSettingsMixin,
    VoiceSettingsMixin,
    SessionMixin,
    QMainWindow,
):
    voice_listener_finished = Signal(object, bool, bool)

    # Per-chat state: one ChatSession per character; these names read/write the session that is current (see chat_sessions.py).
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
    client = session_property("client")                 # every chat has its own router (own Stop flag); health/cooldowns are shared
    chat = property(lambda self: self.cur.view)
    _stream_timer = property(lambda self: self.cur.timer)
    # One-per-computer things belong to the chat in front; a background chat gets silent stand-ins.
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

    @property
    def listener(self):
        service = getattr(self, "voice_application_service", None)
        return service.listener if service is not None else None

    @property
    def _stopping_listener(self):
        service = getattr(self, "voice_application_service", None)
        return service.stopping_listener if service is not None else None

    def __init__(self, memory_service=None, mood_service=None, character_service=None, chat_history_service=None,
                 session_manager=None, chat_event_publisher=None, chat_application_service_factory=None,
                 session_application_service_factory=None, web_search_service=None,
                 voice_application_service_factory=None, game_mode_application_service=None,
                 settings=None, tool_agent=None, provider_application_service=None,
                 coding_agent_application_service=None, vision_application_service=None,
                 runtime_settings_application_service=None):
        super().__init__()
        from .main_window_composition import initialize_main_window

        initialize_main_window(
            self,
            memory_service=memory_service,
            mood_service=mood_service,
            character_service=character_service,
            chat_history_service=chat_history_service,
            session_manager=session_manager,
            chat_event_publisher=chat_event_publisher,
            chat_application_service_factory=chat_application_service_factory,
            session_application_service_factory=session_application_service_factory,
            web_search_service=web_search_service,
            voice_application_service_factory=voice_application_service_factory,
            game_mode_application_service=game_mode_application_service,
            settings=settings,
            tool_agent=tool_agent,
            provider_application_service=provider_application_service,
            coding_agent_application_service=coding_agent_application_service,
            vision_application_service=vision_application_service,
            runtime_settings_application_service=runtime_settings_application_service,
        )

    # ---------- i18n helpers ----------
