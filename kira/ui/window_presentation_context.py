"""Explicit presentation context shared by desktop feature controllers.

The context is the only bridge between feature controllers and the Qt host.
Each namespace exposes a fixed set of fields; arbitrary MainWindow attributes
are never forwarded to controllers. Per-conversation state remains on the
active ChatSession, while window state, services, adapters and widgets have
separate owners.
"""
from __future__ import annotations

from collections.abc import Mapping

from ..chat_sessions import Muted, NOOP


STATE_FIELDS = frozenset({
    "_api_worker",
    "_att_seq",
    "_bench_busy",
    "_bench_worker",
    "_chat_action_seq",
    "_chat_action_texts",
    "_clicks",
    "_close_after_local_voice",
    "_closing",
    "_quitting",
    "_db_notes",
    "_effect",
    "_game_capture_timer",
    "_game_audio_restart_pending",
    "_game_mode_enabled",
    "_game_mode_profile",
    "_game_poll_timer",
    "_game_prev_mic",
    "_game_prev_wake",
    "_last_variant",
    "_latest_game_frame",
    "_load_tiles",
    "_loading_route",
    "_local_tts_test_active",
    "_local_stt_test_listener",
    "_local_voice_worker",
    "_menu_actions",
    "_mcp_registry_worker",
    "_model_catalog_worker",
    "_model_import_worker",
    "_mood_emotion_glow",
    "_mood_ui_timer",
    "_nav_icon_map",
    "_neon_animations",
    "_ollama_models",
    "_ollama_worker",
    "_provider_editing",
    "_provider_test_worker",
    "_provider_workers",
    "_route_worker",
    "_save_warned",
    "_scan_worker",
    "_status",
    "_stopping_game_audio_listener",
    "_tiles",
    "_tr",
    "_upload_done",
    "_upload_tiles",
    "_upload_token",
    "_web_test_worker",
    "awake",
    "cur",
    "front",
    "reactions",
    "sessions",
})

SERVICE_FIELDS = frozenset({
    "brain_application_service",
    "character_service",
    "chat_application_service",
    "chat_event_publisher",
    "conversation_organization_application_service",
    "chat_search_application_service",
    "chat_transfer_application_service",
    "coding_agent_application_service",
    "game_mode_application_service",
    "initiative_application_service",
    "memory_service",
    "mood_service",
    "ollama_client",
    "provider_application_service",
    "reflection_application_service",
    "runtime_settings_application_service",
    "session_application_service",
    "session_manager",
    "settings",
    "shared_skills_application_service",
    "tool_agent",
    "vision_application_service",
    "voice_application_service",
    "web_search_service",
})

ADAPTER_FIELDS = frozenset({
    "animator",
    "bubble",
    "chat_attachment_controller",
    "companion",
    "director",
    "game_audio_listener",
    "game_mode",
    "speaker",
})

VIEW_FIELDS = frozenset({
    "about_labels",
    "api_add_status",
    "appearance_page",
    "assistant_page",
    "avatar",
    "avatar_card",
    "bench_out",
    "char_tab_buttons",
    "char_tab_group",
    "char_tabs_row",
    "character_page",
    "chat_composer",
    "chat_page",
    "chat_stack",
    "cloud_model_lists",
    "code_chat",
    "companion_btn",
    "conn_btn",
    "conn_lbl",
    "failover_chk",
    "game_mode_btn",
    "game_mode_safe_action",
    "game_mode_story_action",
    "gen_stop_btn",
    "glow_effects",
    "help_page",
    "img_search_btn",
    "import_chat_btn",
    "import_model_btn",
    "input",
    "keep_alive",
    "load_btn",
    "local_asr_download_btn",
    "local_asr_load_btn",
    "local_asr_model_list",
    "local_asr_path_edit",
    "local_model_list",
    "local_model_tabs",
    "local_stt_test_btn",
    "local_tts_download_btn",
    "local_tts_model_list",
    "local_tts_model_path",
    "local_tts_test_btn",
    "local_voice_box",
    "local_voice_progress",
    "local_voice_status",
    "local_whisper_path",
    "mcp_registry_panel",
    "memory_btn",
    "menu_btn",
    "mic_btn",
    "model",
    "modes_chk",
    "mood_emotion_icon",
    "mood_indicator",
    "name",
    "nav_buttons",
    "nav_menu",
    "num_ctx",
    "num_predict",
    "persona",
    "preferences_page",
    "restore_chat_btn",
    "route_add_btn",
    "route_auto_btn",
    "route_badge",
    "route_bench_all_btn",
    "route_bench_btn",
    "route_cooldown",
    "route_ctx",
    "route_default_btn",
    "route_del_btn",
    "route_down_btn",
    "route_enabled_chk",
    "route_id",
    "route_list",
    "route_manual_lbl",
    "route_menu",
    "route_model_edit",
    "route_ollama_enabled",
    "route_predict",
    "route_provider_lbl",
    "route_status",
    "route_test_btn",
    "route_timeout",
    "route_up_btn",
    "route_use_btn",
    "save_btn",
    "send_btn",
    "send_strip",
    "speed_btn",
    "status",
    "stop_btn",
    "tab_keys",
    "tabs",
    "tavily_key",
    "temp",
    "title",
    "tray",
    "ui_lang",
    "unload_btn",
    "url",
    "use_qwen_btn",
    "vision_rate_actions",
    "voice_btn",
    "voice_page",
    "wake_btn",
    "wake_timer",
    "web_btn",
    "web_depth",
    "web_fallback_chk",
    "web_test_btn",
})

SERVICE_FRONT_ONLY = frozenset({"voice_application_service"})
ADAPTER_FRONT_ONLY = {
    "speaker": frozenset(),
    "director": frozenset({"parse_reply", "format_hint", "library"}),
    "animator": frozenset(),
    "bubble": frozenset(),
}


RESOURCE_OWNERS = {
    "_local_voice_worker": ("state", "_local_voice_worker"),
    "_local_stt_test_listener": ("state", "_local_stt_test_listener"),
    "_api_worker": ("state", "_api_worker"),
    "_route_worker": ("state", "_route_worker"),
    "_bench_worker": ("state", "_bench_worker"),
    "_scan_worker": ("state", "_scan_worker"),
    "_provider_test_worker": ("state", "_provider_test_worker"),
    "_ollama_worker": ("state", "_ollama_worker"),
    "_vision_worker": ("session", "_vision_worker"),
    "_web_test_worker": ("state", "_web_test_worker"),
    "_attach_worker": ("session_controller", "_attach_worker"),
    "_mcp_registry_worker": ("state", "_mcp_registry_worker"),
    "_model_catalog_worker": ("state", "_model_catalog_worker"),
    "_model_import_worker": ("state", "_model_import_worker"),
    "_stopping_listener": ("context", "stopping_listener"),
    "_stopping_game_audio_listener": ("state", "_stopping_game_audio_listener"),
    "game_audio_listener": ("adapters", "game_audio_listener"),
    "listener": ("context", "listener"),
    "wake_timer": ("views", "wake_timer"),
    "_game_capture_timer": ("state", "_game_capture_timer"),
    "_game_poll_timer": ("state", "_game_poll_timer"),
    "_mood_ui_timer": ("state", "_mood_ui_timer"),
    "code_chat": ("views", "code_chat"),
    "tray": ("views", "tray"),
    "bubble": ("adapters", "bubble"),
}

VIEW_FRONT_ONLY = frozenset({"status", "gen_stop_btn", "send_btn", "input", "voice_btn"})


class _FieldBucket:
    """A strict, mutable namespace with a declared field contract."""

    __slots__ = ("_context", "_name", "_allowed", "_values", "_front_only", "_pure")

    def __init__(
        self,
        context: "WindowPresentationContext",
        name: str,
        allowed: frozenset[str],
        *,
        front_only: frozenset[str] = frozenset(),
        pure: Mapping[str, frozenset[str]] | None = None,
    ) -> None:
        object.__setattr__(self, "_context", context)
        object.__setattr__(self, "_name", name)
        object.__setattr__(self, "_allowed", allowed)
        object.__setattr__(self, "_values", {})
        object.__setattr__(self, "_front_only", front_only)
        object.__setattr__(self, "_pure", dict(pure or {}))

    def __getattr__(self, name: str):
        if name not in self._allowed:
            raise AttributeError(f"{self._name} has no declared field {name!r}")
        values = object.__getattribute__(self, "_values")
        if name not in values:
            raise AttributeError(f"{self._name}.{name} has not been initialized")
        value = values[name]
        if name in self._front_only and self._context.is_background_session:
            if value is None:
                return None
            pure = self._pure.get(name)
            return Muted(value, pure) if pure else NOOP
        return value

    def __setattr__(self, name: str, value) -> None:
        if name not in self._allowed:
            raise AttributeError(f"{self._name} has no declared field {name!r}")
        self._values[name] = value

    def __contains__(self, name: str) -> bool:
        return name in self._allowed and name in self._values


class WindowPresentationContext:
    """Typed presentation boundary for one MainWindow and its feature registry."""

    def __init__(self, host, controllers) -> None:
        self.host = host
        self.controllers = controllers
        self.state = _FieldBucket(self, "state", STATE_FIELDS)
        self.services = _FieldBucket(
            self, "services", SERVICE_FIELDS, front_only=SERVICE_FRONT_ONLY
        )
        self.adapters = _FieldBucket(
            self, "adapters", ADAPTER_FIELDS,
            front_only=frozenset(ADAPTER_FRONT_ONLY),
            pure=ADAPTER_FRONT_ONLY,
        )
        self.views = _FieldBucket(
            self, "views", VIEW_FIELDS, front_only=VIEW_FRONT_ONLY
        )

    def resource(self, name: str, default=None):
        """Read one explicitly owned worker/timer resource for lifecycle cleanup."""
        owner_spec = RESOURCE_OWNERS.get(name)
        if owner_spec is None:
            return default
        namespace, field = owner_spec
        if namespace == "context":
            owner = self
        elif namespace == "session_controller":
            owner = self.controllers.require("session")
        else:
            owner = getattr(self, namespace)
        try:
            return getattr(owner, field)
        except AttributeError:
            return default

    @property
    def session(self):
        """The ChatSession currently handling the UI event."""
        try:
            session = self.state.cur
        except AttributeError as exc:
            raise RuntimeError("The active ChatSession is not initialized") from exc
        if session is None:
            raise RuntimeError("The active ChatSession is not initialized")
        return session

    @property
    def is_background_session(self) -> bool:
        try:
            return self.state.cur is not self.state.front
        except AttributeError:
            return False

    @property
    def listener(self):
        service = self.services.voice_application_service
        return service.listener if service is not None else None

    @property
    def stopping_listener(self):
        service = self.services.voice_application_service
        return service.stopping_listener if service is not None else None
