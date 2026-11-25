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
from ..app.runtime_state import RuntimeState


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
    "_deepseek_login_worker",
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
    "_music_watcher_timer",
    "_nav_icon_map",
    "_neon_animations",
    "_ollama_worker",
    "_provider_editing",
    "_provider_catalog_auto_refresh_started",
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
    "desktop_context_application_service",
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
    "vision_runtime_provider",
    "vision_router",
    "voice_application_service",
    "web_search_service",
})

ADAPTER_FIELDS = frozenset({
    "animator",
    "appearance_runtime",
    "bubble",
    "chat_attachment_controller",
    "companion",
    "director",
    "game_audio_listener",
    "game_mode",
    "perception_worker_controller",
    "music_watcher",
    "motion",
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
    "code_chat",
    "kode_activity",
    "companion_btn",
    "conn_btn",
    "conn_lbl",
    "desktop_vision_action",
    "desktop_vision_auto_action",
    "desktop_vision_monitor_actions",
    "desktop_vision_monitor_menu",
    "failover_chk",
    "game_mode_btn",
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
    "new_chat_btn",
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
    "search_btn",
    "screen_capture_btn",
    "route_bench_btn",
    "route_cooldown",
    "route_ctx",
    "route_del_btn",
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
    "voice_btn",
    "voice_mode_badge",
    "voice_page",
    "wake_btn",
    "wake_timer",
    "web_btn",
    "web_depth",
    "web_fallback_chk",
    "web_test_btn",
    "ui_design_guidance_chk",
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
    "_deepseek_login_worker": ("state", "_deepseek_login_worker"),
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

    __slots__ = ("_context", "_name", "_allowed", "_values", "_front_only", "_pure", "_source", "_store")

    def __init__(
        self,
        context: "WindowPresentationContext",
        name: str,
        allowed: frozenset[str],
        *,
        front_only: frozenset[str] = frozenset(),
        pure: Mapping[str, frozenset[str]] | None = None,
        source: "_FieldBucket | None" = None,
        store: RuntimeState | None = None,
    ) -> None:
        object.__setattr__(self, "_context", context)
        object.__setattr__(self, "_name", name)
        object.__setattr__(self, "_allowed", allowed)
        object.__setattr__(self, "_values", {})
        object.__setattr__(self, "_front_only", front_only)
        object.__setattr__(self, "_pure", dict(pure or {}))
        object.__setattr__(self, "_source", source)
        object.__setattr__(self, "_store", store)

    def __getattr__(self, name: str):
        if name not in self._allowed:
            raise AttributeError(f"{self._name} has no declared field {name!r}")
        values = object.__getattribute__(self, "_values")
        source = object.__getattribute__(self, "_source")
        if source is not None:
            value = getattr(source, name)
        else:
            store = object.__getattribute__(self, "_store")
            if store is not None and store.contains(name):
                value = store.get(name)
            elif name in values:
                value = values[name]
            else:
                raise AttributeError(f"{self._name}.{name} has not been initialized")
        if name in self._front_only and self._context.is_background_session:
            if value is None:
                return None
            pure = self._pure.get(name)
            return Muted(value, pure) if pure else NOOP
        return value

    def __setattr__(self, name: str, value) -> None:
        if name not in self._allowed:
            raise AttributeError(f"{self._name} has no declared field {name!r}")
        source = object.__getattribute__(self, "_source")
        if source is not None:
            setattr(source, name, value)
        else:
            store = object.__getattribute__(self, "_store")
            if store is not None:
                store.set(name, value)
            else:
                self._values[name] = value

    def __contains__(self, name: str) -> bool:
        if name not in self._allowed:
            return False
        source = object.__getattribute__(self, "_source")
        if source is not None:
            return name in source
        store = object.__getattribute__(self, "_store")
        return store.contains(name) if store is not None else name in self._values



# Per-controller least-privilege capability matrix. Root allowlists above are
# composition-only; adding a root field never grants it to feature controllers.
CONTROLLER_ACCESS = {
 "runtime": {
  "state": frozenset({"_clicks","_close_after_local_voice","_closing","_quitting","_game_mode_profile","_last_variant","_provider_workers","_save_warned","awake","cur","front","reactions","sessions"}),
  "services": frozenset({"brain_application_service","character_service","chat_application_service","vision_application_service","game_mode_application_service","memory_service","mood_service","provider_application_service","reflection_application_service","session_application_service","settings","tool_agent","vision_router","voice_application_service"}),
  "adapters": frozenset({"animator","bubble","companion","director","game_mode","motion"}),
  "views": frozenset({"code_chat","companion_btn","desktop_vision_action","desktop_vision_auto_action","desktop_vision_monitor_actions","desktop_vision_monitor_menu","gen_stop_btn","input","kode_activity","mic_btn","route_badge","route_menu","route_status","send_btn","status","tab_keys","tray","voice_btn","voice_page","wake_btn","wake_timer"}),
  "peers": frozenset({"session","provider_settings","attachments_vision","chat","lifecycle","voice_settings"}),
  "resources": frozenset({"_model_import_worker","_local_voice_worker","_local_stt_test_listener","_mcp_registry_worker","_model_catalog_worker","_api_worker","_route_worker","_bench_worker","_scan_worker","_provider_test_worker","_ollama_worker","_vision_worker","_web_test_worker","_attach_worker","_stopping_listener","_stopping_game_audio_listener","game_audio_listener","listener","wake_timer","_game_poll_timer","_game_capture_timer","_mood_ui_timer"}),
  "extras": frozenset({"session","listener","resource","is_background_session"}),
 },
 "chat": {
  "state": frozenset({"_closing","_game_mode_enabled","_save_warned","_web_test_worker","cur","sessions","front"}),
  "services": frozenset({"brain_application_service","character_service","chat_application_service","coding_agent_application_service","memory_service","mood_service","session_manager","settings","tool_agent","voice_application_service","web_search_service","vision_application_service"}),
  "adapters": frozenset({"animator","director","bubble"}),
  "views": frozenset({"gen_stop_btn","img_search_btn","input","search_btn","screen_capture_btn","status","tavily_key","web_btn","web_depth","web_test_btn","code_chat","kode_activity"}),
  "peers": frozenset({"session","runtime","attachments_vision","chat"}),
  "resources": frozenset(),
  "extras": frozenset({"session","is_background_session"}),
 },
 "session": {
  "state": frozenset({"_att_seq","_chat_action_seq","_chat_action_texts","_menu_actions","_nav_icon_map","_status","_tr","cur","front","sessions","_closing","_effect","_mood_emotion_glow","_save_warned"}),
  "services": frozenset({"character_service","chat_application_service","initiative_application_service","mood_service","provider_application_service","session_application_service","session_manager","settings","tool_agent","voice_application_service"}),
  "adapters": frozenset({"bubble","director","chat_attachment_controller", "appearance_runtime"}),
  "views": frozenset({"code_chat","appearance_page","assistant_page","char_tab_buttons","char_tab_group","char_tabs_row","character_page","chat_page","chat_stack","gen_stop_btn","glow_effects","help_page","input","kode_activity","mic_btn","mood_indicator","mood_emotion_icon","nav_buttons","avatar_card","menu_btn","new_chat_btn","route_badge","preferences_page","save_btn","status","tab_keys","tabs","title","voice_page"}),
  "peers": frozenset({"session","runtime","chat","character_settings","attachments_vision","voice_settings"}),
  "resources": frozenset(),
  "extras": frozenset({"session","is_background_session"}),
 },
 "lifecycle": {
  "state": frozenset({"_closing","_effect","_ollama_worker","_quitting","sessions"}),
  "services": frozenset({"ollama_client","provider_application_service","runtime_settings_application_service","settings","tool_agent","vision_router"}),
  "adapters": frozenset({"animator","companion","bubble", "appearance_runtime"}),
  "views": frozenset({"appearance_page","avatar","character_page","conn_btn","conn_lbl","keep_alive","load_btn","mic_btn","model","modes_chk","name","num_ctx","num_predict","persona","route_ollama_enabled","speed_btn","tavily_key","temp","tray","ui_lang","unload_btn","url","voice_page","web_btn","web_depth","web_fallback_chk"}),
  "peers": frozenset({"session","provider_settings","runtime","character_settings"}),
  "resources": frozenset(),
  "extras": frozenset({"session"}),
 },
 "attachments": {
  "state": frozenset({"_upload_done","_upload_tiles","_upload_token"}),
  "services": frozenset(),
  "adapters": frozenset(),
  "views": frozenset({"send_strip"}),
  "peers": frozenset({"chat"}),
  "resources": frozenset(),
  "extras": frozenset({"is_background_session"}),
 },
 "attachments_vision": {
  "state": frozenset({"_closing","_game_audio_restart_pending","_game_capture_timer","_game_mode_enabled","_game_mode_profile","_game_poll_timer","_game_prev_mic","_game_prev_wake","_latest_game_frame","_stopping_game_audio_listener","_upload_done","_upload_tiles","_upload_token","cur","sessions"}),
  "services": frozenset({"coding_agent_application_service","desktop_context_application_service","game_mode_application_service","settings","tool_agent","vision_application_service","vision_runtime_provider","vision_router","voice_application_service"}),
  "adapters": frozenset({"game_audio_listener","game_mode","perception_worker_controller"}),
  "views": frozenset({"game_mode_btn","desktop_vision_action","desktop_vision_auto_action","desktop_vision_monitor_actions","desktop_vision_monitor_menu","mic_btn","send_strip","wake_btn","code_chat","tray"}),
  "peers": frozenset({"session","chat","runtime","game_audio","attachments"}),
  "resources": frozenset({"_stopping_game_audio_listener"}),
  "extras": frozenset({"session","resource","is_background_session"}),
 },
 "game_audio": {
  "state": frozenset({"_closing","_game_audio_restart_pending","_game_mode_enabled","_game_mode_profile","_stopping_game_audio_listener"}),
  "services": frozenset({"game_mode_application_service","settings","voice_application_service"}),
  "adapters": frozenset({"game_audio_listener"}),
  "views": frozenset(),
  "peers": frozenset({"session","runtime"}),
  "resources": frozenset({"_stopping_game_audio_listener"}),
  "extras": frozenset({"resource","session"}),
 },
 "provider_settings": {
  "state": frozenset({"_api_worker","_bench_busy","_bench_worker","_closing","_deepseek_login_worker","_loading_route","_model_catalog_worker","_route_worker","_scan_worker"}),
  "services": frozenset({"provider_application_service","settings"}),
  "adapters": frozenset(),
  "views": frozenset({"assistant_page","api_add_status","bench_out","import_model_btn","local_asr_download_btn","local_asr_load_btn","local_asr_model_list","local_asr_path_edit","local_model_list","local_model_tabs","local_stt_test_btn","local_tts_download_btn","local_tts_model_list","local_tts_model_path","local_voice_box","local_voice_progress","local_voice_status","local_whisper_path","mcp_registry_panel","model","route_bench_btn","route_cooldown","route_ctx","route_del_btn","route_enabled_chk","route_list","route_manual_lbl","route_model_edit","route_ollama_enabled","route_predict","route_provider_lbl","route_status","route_test_btn","route_timeout","route_use_btn","tabs","url","local_tts_test_btn","failover_chk","route_add_btn","route_auto_btn"}),
  "peers": frozenset({"voice_settings","runtime","character_settings","session"}),
  "resources": frozenset({"_model_catalog_worker","_route_worker","_scan_worker","_deepseek_login_worker"}),
  "extras": frozenset({"resource","session","is_background_session"}),
 },
 "character_settings": {
  "state": frozenset({"_closing","_effect","_mcp_registry_worker","front","sessions"}),
  "services": frozenset({"character_service","mood_service","settings","shared_skills_application_service","tool_agent","voice_application_service"}),
  "adapters": frozenset({"animator","speaker", "appearance_runtime"}),
  "views": frozenset({"assistant_page","appearance_page","character_page","help_page","mcp_registry_panel","preferences_page","save_btn","glow_effects","tabs","ui_lang","tavily_key","web_depth","web_fallback_chk","web_test_btn","ui_design_guidance_chk","restore_chat_btn","memory_btn","import_chat_btn","about_labels"}),
  "peers": frozenset({"session","lifecycle","runtime","chat","provider_settings"}),
  "resources": frozenset({"_mcp_registry_worker"}),
  "extras": frozenset({"resource","is_background_session"}),
 },
 "voice_settings": {
  "state": frozenset({"_close_after_local_voice","_closing","_local_stt_test_listener","_local_tts_test_active","_local_voice_worker","_model_import_worker"}),
  "services": frozenset({"game_mode_application_service","provider_application_service","settings","voice_application_service"}),
  "adapters": frozenset({"animator"}),
  "views": frozenset({"code_chat","game_mode_btn","gen_stop_btn","img_search_btn","input","kode_activity","mic_btn","route_badge","route_menu","screen_capture_btn","search_btn","send_btn","send_strip","voice_btn","wake_btn","web_btn","api_add_status","assistant_page","avatar","avatar_card","char_tab_buttons","char_tab_group","char_tabs_row","chat_composer","chat_page","chat_stack","companion_btn","conn_btn","conn_lbl","glow_effects","import_model_btn","keep_alive","load_btn","local_asr_download_btn","local_asr_load_btn","local_asr_model_list","local_asr_path_edit","local_model_tabs","local_stt_test_btn","local_tts_download_btn","local_tts_model_list","local_tts_model_path","local_tts_test_btn","local_voice_progress","local_voice_status","local_whisper_path","model","modes_chk","mood_emotion_icon","mood_indicator","name","num_ctx","num_predict","persona","speed_btn","status","tab_keys","tabs","temp","title","unload_btn","url","use_qwen_btn","voice_mode_badge","voice_page"}),
  "peers": frozenset({"session","runtime","lifecycle","provider_settings","character_settings","chat"}),
  "resources": frozenset({"_local_stt_test_listener"}),
  "extras": frozenset({"resource","is_background_session"}),
 },
}

class _ControllerPresentationContext:
    """Capability-limited view of the root context for one registered controller."""
    __slots__ = ("_root", "_feature", "_access", "state", "services", "adapters", "views")

    def __init__(self, root: "WindowPresentationContext", feature: str) -> None:
        access = CONTROLLER_ACCESS.get(feature)
        if access is None:
            raise LookupError(f"No Presentation Context access policy for controller {feature!r}")
        object.__setattr__(self, "_root", root)
        object.__setattr__(self, "_feature", feature)
        object.__setattr__(self, "_access", access)
        for namespace in ("state", "services", "adapters", "views"):
            source = getattr(root, namespace)
            bucket = _FieldBucket(
                self,
                f"{feature}.{namespace}",
                access.get(namespace, frozenset()),
                source=source,
            )
            object.__setattr__(self, namespace, bucket)

    def require_peer(self, feature: str):
        if feature not in self._access["peers"]:
            raise PermissionError(f"Controller {self._feature!r} cannot access peer controller {feature!r}")
        return self._root.controllers.require(feature)

    def get_peer_if_materialized(self, feature: str):
        """Return a peer instance only when already realized; never trigger lazy loading."""
        if feature not in self._access["peers"]:
            raise PermissionError(
                f"Controller {self._feature!r} cannot access peer controller {feature!r}"
            )
        return self._root.controllers.get_if_materialized(feature)

    @property
    def session(self):
        if "session" not in self._access["extras"]:
            raise PermissionError(f"Controller {self._feature!r} has no session capability")
        return self._root.session

    @property
    def listener(self):
        if "listener" not in self._access["extras"]:
            raise PermissionError(f"Controller {self._feature!r} has no listener capability")
        return self._root.listener

    @property
    def is_background_session(self):
        if "is_background_session" not in self._access["extras"]:
            raise PermissionError(f"Controller {self._feature!r} has no background-session capability")
        return self._root.is_background_session

    def resource(self, name: str, default=None):
        if "resource" not in self._access["extras"] or name not in self._access["resources"]:
            raise PermissionError(f"Controller {self._feature!r} cannot access resource {name!r}")
        return self._root.resource(name, default)

    def __getattr__(self, name: str):
        raise AttributeError(f"Controller {self._feature!r} has no Presentation Context capability {name!r}")


class WindowPresentationContext:
    """Typed presentation boundary for one MainWindow and its feature registry."""

    def __init__(self, host, controllers) -> None:
        self.host = host
        self.controllers = controllers
        self.runtime_state = RuntimeState(STATE_FIELDS)
        self.state = _FieldBucket(self, "state", STATE_FIELDS, store=self.runtime_state)
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

    def for_controller(self, controller):
        """Return the least-privilege context assigned to a registered controller."""
        feature = self.controllers.name_for(controller)
        return _ControllerPresentationContext(self, feature)

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
