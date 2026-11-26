"""Canonical, dependency-free settings schema and product defaults.

All persisted settings defaults, validation choices/ranges, and built-in
provider model preferences originate here. This module must not import Config,
Routes, UI, or Provider services.
"""
LOCAL_UNCENSORED_MODEL = "kira-qwen3.5-9b-abliterated:q4_k_m"
DEFAULT_OLLAMA_URL = "http://localhost:11434"
LEGACY_LOCAL_CHAT_MODELS = frozenset({"qwen3.5:4b"})
STT_LANGUAGE_OPTIONS = ("fa", "en", "auto")
SETTINGS_SCHEMA_VERSION = 9

DEFAULTS = {
    "settings_version": SETTINGS_SCHEMA_VERSION,
    "ollama_url": DEFAULT_OLLAMA_URL,
    "model": LOCAL_UNCENSORED_MODEL,
    "assistant_name": "Kira",
    "active_character_id": "kira",
    # Extra user notes only. Kira's real character is defined in kira/personality.py and always applied.
    "persona": "",
    "temperature": 0.7,
    "web_search": True,                  # Kira may search the web when a message needs current information
    "news_feed_enabled": True,             # independent rolling feeds for Kira, Ren and Mika
    "news_feed_interval_hours": 6,         # background refresh while the app is running
    "news_health_region": {"city": "", "country": "", "confirmed": False, "source": "", "confirmed_at": ""},
    "image_search": False,               # a picture sent to Kira is also searched on the web (Gemini sees it; Tavily / DuckDuckGo use a text query made from it)
    "web_fallback": True,                # Tavily fails -> Google (Gemini) -> DuckDuckGo
    "tavily_api_key": "",                # web search engine key (https://tavily.com, free plan)
    "web_depth": "basic",                # basic = 1 credit per search, advanced = 2 credits and better relevance
    # Web Intelligence & Research (kira/webintel, docs/WEB_RESEARCH_FA.md): multi-source research tools used through the Tool System / Autonomous Agent
    "web_research": True,                # the web_search / web_read / web_research tools exist (they still run only on an explicit request)
    "web_research_max_searches": 8,      # most searches in ONE deep research (1-20)
    "web_research_max_pages": 10,        # most pages read in ONE deep research (1-25)
    "web_research_max_seconds": 90,      # time limit of ONE deep research (15-300); it pauses and can be continued
    "web_research_max_chars": 9000,      # size of the report sent to the model (2500-14000 characters)
    "web_read_timeout": 15,              # seconds to wait for one page
    "web_read_max_mb": 2.5,              # biggest page / PDF read (MB); the rest is cut
    "web_max_redirects": 4,              # redirects followed per page (each hop is re-checked against SSRF rules)
    "speak_replies": True,
    "desktop_vision_enabled": False,        # Live Desktop Vision starts off on every app launch
    "eye_mode_profile": "competitive_safe",   # manual Eye Mode game profile: competitive_safe | story
    "eye_live_min_interval_seconds": 5,      # Gemini Live frame budget: minimum seconds between frames
    "eye_live_max_frames_per_minute": 10,    # Gemini Live frame budget: hard per-minute cap
    "desktop_vision_monitor_id": "",          # empty = monitor containing the foreground window
    "desktop_vision_allowlist": [],           # explicit exe:<n>, title:<pattern>, path:<pattern> exceptions
    "desktop_vision_blocklist": {},           # custom privacy rules merged with defaults
    "desktop_vision_ocr_enabled": True,       # local OCR on changed desktop content when Tesseract already exists
    "vision_ocr_in_game_mode": False,         # OCR stays off during gameplay unless explicitly enabled
    "voice_engine": "gemini_live",       # gemini_live = bidirectional cloud voice; local = selected offline ASR adapter + Piper
    "gemini_live_provider": "",          # provider id from the existing Google API Manager; never stores a second API key
    "gemini_live_model": "gemini-3.8-live",
    "gemini_voice": "Zephyr",             # Gemini Live prebuilt voice name (see GEMINI_VOICES in ui/pages/voice_page.py)
    "voice_local_fallback": True,        # retain existing local STT/TTS as the fallback path
    "active_modes": True,                # per-message Active Mode (chat / task / plain answer): the request outranks the personality
    "stream_speech": True,               # speech starts from the first finished sentence while the reply is still being written
    "voice_rate": 0,                      # local Piper speech speed adjustment
    "voice_volume": 0.9,
    "output_device": "",                  # "" = Windows default speaker; otherwise the device description
    "mic_device": "",                     # "" = Windows default microphone; otherwise the device name
    "mic_gain": 100,                      # 50-300 %: software gain of the microphone (independent of the speaker volume)
    "local_voice_asr": True,              # enable the selected offline ASR path
    "local_voice_asr_backend": "shenava",  # selected local ASR adapter
    "realtime_asr_enabled": True,          # local microphone ASR; file-based offline tests still work when disabled
    "tts_engine": "piper",                # piper = Persian (default) | kitten = English-only KittenTTS 2
    "kitten_model": "mini",               # pico | nano | mini
    "local_voice_tts": True,              # Piper local TTS only; no network or Windows voice fallback
    "local_voice_asr_model": "SajjadMajdi/shenava-koochik-fa-int8",
    "local_voice_tts_model": "",
    "model_filter_mode": "all",
    "appearance": {"background_color": "#0A0A1C", "brightness": 100, "glow": 58, "transparency": 28},
    "character_voice": {},
    "character_notes": {},
    "character_resources": {},
    "character_initiative": {},        # per-character, explicit opt-in; defaults off
    "initiative_casual": True,         # when a character's check-ins are allowed and nothing specific is worth recalling, send a short friendly nudge
    "character_initiative_history": {},  # bounded per-character sent timestamps and memory IDs

    "whisper_model": "small",
    "stt_language": "fa",
    "wake_timeout": 25,
    "mic_sensitivity": 100,               # 50-200 %: lower = ignores more room noise
    "barge_in": True,                     # talking over Kira stops her (headphones give the best result)
    "ui_lang": "en",
    "window_effect": "acrylic",          # Windows 11: acrylic | mica | off (ignored elsewhere)
    "click_reactions": True,
    "body_control": True,                 # chat commands move the 3D body (raise hand, turn back, bend ...; kira/body.py)
    "companion_height": 620,
    "follow_strength": 1.0,
    "motion_strength": 1.0,
    "always_on_top": True,
    "minimize_to_tray": True,            # minimize button hides the window to the system tray
    "close_to_tray": False,              # close (X) hides to the tray instead of quitting
    "idle_talk": True,
    "start_with_windows": True,          # per-user Run key (kira/autostart.py); starts hidden in the tray
    "game_commentary": True,             # Eye/Game Mode: speak up on a remarkable moment (rate-limited; no extra model request)
    "companion_perch": True,             # after a drag she falls and sits on the window / taskbar under her (kira/pet.py)
    "companion_hang": True,              # while dragged she hangs from the cursor and swings
    "auto_dance": True,                  # dance by herself when music plays on the PC (needs PyAudioWPatch)
    "provider_order": ["groq", "cloudflare", "mistral", "openrouter", "ollama"],
    "route_cooldown": 45,
    "memory_context_limit": 12,
    # Evidence memory (kira/evidence_memory.py, docs/MEMORY_EVIDENCE_FA.md): facts with their source quote, recalled by relevance.
    "evidence_memory": "auto",      # auto = on (falls back to the plain fact list on any problem) | off = the earlier behaviour only
    "memory_top_k": 6,              # most facts recalled for one message (besides the pinned name / nickname / answer-length preference)
    "embedding_backend": "off",     # off (default: no embedding request is ever made) | ollama (local) | provider (an OpenAI-compatible API)
    "embedding_model": "",          # e.g. "bge-m3" or "nomic-embed-text" for ollama; the provider's embedding model id for "provider"
    "embedding_provider": "",       # route provider id used when embedding_backend = "provider" (independent of the chat route)
    # Multi-stage brain (kira/brain.py, docs/BRAIN_FA.md): deterministic stage choice + free reply check; model calls only when enabled here.
    "brain_mode": "auto",           # auto | surface_only (never the deep stage) | off (the module does nothing)
    "brain_reflection": "rules",    # rules (free) | model (also one small background call on deep turns) | off
    "brain_memory_writer": "off",   # off | idle (background fact writer; every fact must quote the user, verified in code)
    "role_routes": {"surface": "auto", "deep": "auto", "reflection": "auto", "memory": "auto"},   # route id per role, or "auto"
    # Provider boundaries per role. Since schema v8 the normal chat role (surface) may use the built-in Cloud
    # providers as well as local Ollama (the owner's decision); deep/reflection stay Gemini-only and memory stays local.
    # A Cloud provider is still only used when it is enabled and has a key. Custom providers must be added by hand.
    "role_provider_allowlist": {"surface": ["ollama", "groq", "cloudflare", "mistral", "openrouter", "google"],
                                "deep": ["google"], "reflection": ["google"], "memory": ["ollama"]},
    "role_route_models": {"surface": [LOCAL_UNCENSORED_MODEL]},
    "mcp_mode": "auto",             # auto = use kira_mcp.json when it exists | off (docs/MCP_AGENTS_FA.md)
    # Usage ledger (kira/usage.py, docs/USAGE_FA.md): numbers only; Unknown when the provider does not report.
    "model_prices": {},             # {"provider:model" or "model": {"input_per_million": 0.5, "output_per_million": 1.5, "cache_per_million": 0.1}}
    "usage_limits": {},             # {"role:deep": {"requests_per_day": 50, "tokens_per_day": 200000, "action": "warn|block"}, "provider:groq": {...}}
    # Computer Awareness + Tool System (kira/tools, docs/TOOLS_FA.md)
    "tools_mode": "auto",           # auto = tools are offered to the model only for requests about this PC | always | off (old fixed shortcuts only)
    "tools_allowed_paths": [],      # extra folders Kira may search/read/open, besides Desktop, Documents, Downloads, Pictures, Videos, Music
    "tools_max_rounds": 4,          # most tool steps in ONE answer (1-6)
    "agent_planning": "auto",       # auto = a multi-step request about this PC is planned and executed step by step | off = only the plain tool loop
    "agent_max_steps": 8,           # most steps of one planned task (2-15); tool executions are capped at twice this
    "agent_max_replans": 3,         # how many times the plan may be revised during one task (0-5)
    # Route Manager (1.5.1): "routes" itself is created by routes.ensure_routes() on load (migrated from the old layout).
    "manual_route_id": "",          # "" = automatic by priority; otherwise the route chosen by hand
    "failover_enabled": True,       # manual choice may still fall back within the active network policy
    "network_policy": "cloud_permitted",  # local_only blocks every Cloud route; since schema v8 the default is cloud_permitted (unknown values still fail closed to local_only)
    "default_route_id": "",
    "route_free_only": True,        # catalog refresh switches off routes whose model is explicitly no longer free
    "providers": {
        "groq": {"enabled": False, "api_key": "", "model": "openai/gpt-oss-120b", "timeout": 18},
        "cloudflare": {"enabled": False, "api_key": "", "account_id": "", "model": "@cf/meta/llama-3.1-8b-instruct", "timeout": 18},
        "mistral": {"enabled": False, "api_key": "", "model": "mistral-small-latest", "timeout": 18},
        "openrouter": {"enabled": False, "api_key": "", "model": "", "timeout": 18},
        # num_ctx / keep_alive keep the local model light while gaming (8 GB VRAM card).
        # "model" and "base_url" here mirror the top-level "model" / "ollama_url" keys.
        "ollama": {"enabled": True, "base_url": DEFAULT_OLLAMA_URL, "model": LOCAL_UNCENSORED_MODEL,
                   "num_ctx": 6144, "keep_alive": "2m", "timeout": 180, "num_predict": 512}
    }
}

# Semantic constraints are part of the settings schema, not UI-only assumptions.
SETTING_CHOICES = {
    "network_policy": frozenset({"local_only", "cloud_permitted"}),
    "voice_engine": frozenset({"gemini_live", "local"}),
    "stt_language": frozenset(STT_LANGUAGE_OPTIONS),
    "tts_engine": frozenset({"piper", "kitten"}),
    "kitten_model": frozenset({"pico", "nano", "mini"}),
    "web_depth": frozenset({"basic", "advanced"}),
    "eye_mode_profile": frozenset({"competitive_safe", "story"}),
    "ui_lang": frozenset({"en", "fa"}),
    "window_effect": frozenset({"acrylic", "mica", "off"}),
    "evidence_memory": frozenset({"auto", "off"}),
    "embedding_backend": frozenset({"off", "ollama", "provider"}),
    "brain_mode": frozenset({"auto", "surface_only", "off"}),
    "brain_reflection": frozenset({"rules", "model", "off"}),
    "brain_memory_writer": frozenset({"off", "idle"}),
    "mcp_mode": frozenset({"auto", "off"}),
    "tools_mode": frozenset({"auto", "always", "off"}),
    "agent_planning": frozenset({"auto", "off"}),
}
SETTING_RANGES = {
    "temperature": (0.0, 2.0),
    "voice_volume": (0.0, 1.0),
    "voice_rate": (-30, 30),
    "mic_gain": (50, 300),
    "mic_sensitivity": (50, 200),
    "wake_timeout": (5, 120),
    "companion_height": (100, 2000),
    "follow_strength": (0.0, 2.0),
    "motion_strength": (0.0, 2.0),
    "eye_live_min_interval_seconds": (1, 60),
    "eye_live_max_frames_per_minute": (1, 60),
    "news_feed_interval_hours": (1, 24),
    "web_research_max_searches": (1, 20),
    "web_research_max_pages": (1, 25),
    "web_research_max_seconds": (15, 300),
    "web_research_max_chars": (2500, 14000),
    "tools_max_rounds": (1, 6),
    "agent_max_steps": (2, 15),
    "agent_max_replans": (0, 5),
    "memory_context_limit": (1, 100),
    "memory_top_k": (1, 50),
    "appearance.brightness": (40, 150),
    "appearance.glow": (0, 100),
    "appearance.transparency": (0, 80),
    "providers.ollama.num_ctx": (1024, 32768),
    "route_cooldown": (0, 3600),
    "routes.timeout.cloud": (5, 60),
    "routes.timeout.local": (10, 600),
    "routes.cooldown": (0, 3600),
}

# Free-tier Google vision chain in fallback order (enable these Routes in this order in the Models panel).
# All accept screenshots; each has its own free quota. Hydrogen is the optional deep-reasoning route (hard
# puzzles/bosses, thinking_level low by default) because its daily quota drains first; the Gemma 4 models
# have a free quota separate from Gemini. Verify the exact IDs with the models list before relying on them.
GOOGLE_FREE_VISION_CHAIN = ("gemini-3.8-flash", "gemini-3.6-flash", "gemini-3.5-flash-lite", "gemini-3.1-flash-lite",
                            "gemma-4-31b-it", "gemma-4-26b-a4b-it")
GOOGLE_DEEP_REASONING_MODEL = "gemini-4-hydrogen"

# Preferred starting models are selected only if a provider actually reports them.
# They are policy defaults, not live observations.
PROVIDER_DEFAULT_MODELS = {
    "groq": (DEFAULTS["providers"]["groq"]["model"],),
    "mistral": (DEFAULTS["providers"]["mistral"]["model"],),
    "cloudflare": (DEFAULTS["providers"]["cloudflare"]["model"],),
    "openrouter": (),
    # ONE starting model: the first of these that the account really lists (see api_manager.pick_default_model).
    "google": ("gemini-3.8-flash", "gemini-3.6-flash", "gemini-3.5-flash-lite", "gemini-3.1-flash-lite",
               "gemini-flash-latest", "gemini-2.5-flash"),
    "apinex": ("free/deepseek-v4.1-flash", "free/gemini-3.8-flash", "free/qwen-3.8-max"),
}
