from pathlib import Path
import json
import os
import time
from copy import deepcopy
from .secret_store import protect, unprotect
from . import routes as route_model
from .personality import STOCK_PERSONAS

ROOT = Path(__file__).resolve().parent.parent
LOCAL_UNCENSORED_MODEL = "kira-qwen3.5-9b-abliterated:q4_k_m"
LEGACY_LOCAL_CHAT_MODELS = {"qwen3.5:4b"}
from . import storage

# Persistent user data and AI caches live in A:\\Project KIRA\\Kira Attachments on Windows.
# KIRA_DATA_DIR overrides the location; an unwritable path falls back to the per-user data folder.
DATA_DIR = storage.default_data_dir(ROOT)
DATA_DIR.mkdir(parents=True, exist_ok=True)
CONFIG_PATH = DATA_DIR / "settings.json"
DB_PATH = DATA_DIR / "kira_memory.sqlite3"

APP_NAME = "Project Kira"  # change this to rebrand the desktop application
PROJECT_URL = "https://github.com/alizesta/Kira"
RELEASES_URL = PROJECT_URL + "/releases/latest"
VERSION = "1.1"

DEFAULTS = {
    "ollama_url": "http://localhost:11434",
    "model": LOCAL_UNCENSORED_MODEL,
    "assistant_name": "Kira",
    "active_character_id": "kira",
    # Extra user notes only. Kira's real character is defined in kira/personality.py and always applied.
    "persona": "",
    "temperature": 0.7,
    "web_search": True,                  # Kira may search the web when a message needs current information
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
    "voice_engine": "gemini_live",       # gemini_live = primary bidirectional voice; local = existing Qwen/Whisper + Piper
    "voice_engine_migrated": True,       # one-time migration guard; preserves an intentional local-primary choice
    "gemini_live_provider": "",          # provider id from the existing Google API Manager; never stores a second API key
    "gemini_live_model": "gemini-3.8-live",
    "voice_local_fallback": True,        # retain existing local STT/TTS as the fallback path
    "active_modes": True,                # per-message Active Mode (chat / task / plain answer): the request outranks the personality
    "stream_speech": True,               # speech starts from the first finished sentence while the reply is still being written
    "voice_rate": 0,                      # local Piper speech speed adjustment
    "voice_volume": 0.9,
    "voice_native_wav": True,             # Windows: play wav replies through winsound (Qt player was silent on some PCs)
    "output_device": "",                  # "" = Windows default speaker; otherwise the device description
    "mic_device": "",                     # "" = Windows default microphone; otherwise the device name
    "mic_gain": 100,                      # 50-300 %: software gain of the microphone (independent of the speaker volume)
    "local_voice_asr": True,              # selected offline ASR first; faster-whisper is the only fallback
    "local_voice_asr_backend": "qwen3",    # qwen3 | shenava
    "realtime_asr_enabled": True,          # local microphone ASR; file-based offline tests still work when disabled
    "local_voice_tts": True,              # Piper local TTS only; no network or Windows voice fallback
    "local_voice_asr_model": "Qwen/Qwen3-ASR-0.6B",
    "local_voice_tts_model": "",
    "model_filter_mode": "all",
    "appearance": {"background_color": "#0A0A1C", "brightness": 100, "glow": 58, "transparency": 28},
    "appearance_glow_adjusted": False,
    "appearance_neon_shooter_v1": False,
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
    "ui_lang": "fa",
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
    "companion_perch": True,             # after a drag she falls and sits on the window / taskbar under her (kira/pet.py)
    "companion_hang": True,              # while dragged she hangs from the cursor and swings
    "auto_dance": True,                  # dance by herself when music plays on the PC (needs PyAudioWPatch)
    "provider_order": ["groq", "cloudflare", "mistral", "openrouter", "ollama"],
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
    # Hard provider boundaries: normal/sensitive turns local, demanding analysis via Gemini only.
    "role_provider_allowlist": {"surface": ["ollama"], "deep": ["google"], "reflection": ["google"], "memory": ["ollama"]},
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
    "failover_enabled": True,       # a manual choice may still fall back to the next route
    "default_route_id": "",
    "route_free_only": True,        # catalog refresh switches off routes whose model is explicitly no longer free
    "model_catalog_refreshed_at": 0,  # epoch seconds of the last successful automatic/manual model catalog refresh
    "api_registry": {},             # API Manager: what each registered API reported (status, models, time). Never contains keys.
    "providers": {
        "groq": {"enabled": False, "api_key": "", "model": "openai/gpt-oss-120b", "timeout": 18},
        "cloudflare": {"enabled": False, "api_key": "", "account_id": "", "model": "@cf/meta/llama-3.1-8b-instruct", "timeout": 18},
        "mistral": {"enabled": False, "api_key": "", "model": "mistral-small-latest", "timeout": 18},
        "openrouter": {"enabled": False, "api_key": "", "model": "", "timeout": 18},
        # num_ctx / keep_alive keep the local model light while gaming (8 GB VRAM card).
        # "model" and "base_url" here mirror the top-level "model" / "ollama_url" keys.
        "ollama": {"enabled": True, "base_url": "http://localhost:11434", "model": LOCAL_UNCENSORED_MODEL,
                   "num_ctx": 6144, "keep_alive": "2m", "timeout": 180, "num_predict": 512}
    }
}

CLOUD_PROVIDERS = ("groq", "cloudflare", "mistral", "openrouter")
# Models Groq has retired -> current replacement (only applied to the exact retired IDs).
RETIRED_GROQ_MODELS = {
    "llama-3.3-70b-versatile": "openai/gpt-oss-120b",
    "llama-3.1-8b-instant": "openai/gpt-oss-20b",
}

# Human-readable notes produced while loading (shown in the chat window at startup).
LOAD_WARNINGS: list[str] = []


def normalize_provider_order(order):
    """Keep a stable priority order for every cloud and local route."""
    valid = (*CLOUD_PROVIDERS, "ollama")
    result = []
    for name in (order or []):
        if (name in valid or str(name).startswith("custom-")) and name not in result:
            result.append(name)
    for name in DEFAULTS["provider_order"]:
        if name not in result:
            result.append(name)
    return result


def _backup_corrupt(path):
    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup = path.with_name(f"{path.name}.corrupt-{stamp}")
    try:
        backup.write_bytes(path.read_bytes())
        return backup
    except OSError:
        return None


def prepare_user_data():
    """Carry old data over (copy only) and keep a rolling backup. Never raises."""
    notes = [storage.DATA_DIR_WARNING] if storage.DATA_DIR_WARNING else []
    try:
        if not storage.DATA_DIR_WAS_EXPLICIT or storage.is_preferred_data_dir(DATA_DIR):
            note = storage.migrate_legacy(DATA_DIR, storage.legacy_candidates(ROOT))
            if note:
                notes.append(note)
        storage.backup_user_data(DATA_DIR)
    except Exception as exc:                       # a failed copy/backup must never stop Kira from starting
        notes.append(f"پشتیبان‌گیری یا انتقال اطلاعات قدیمی انجام نشد: {exc}")
    return notes


def load_settings():
    LOAD_WARNINGS.clear()
    LOAD_WARNINGS.extend(prepare_user_data())
    if CONFIG_PATH.exists():
        try:
            saved = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if not isinstance(saved, dict):
                raise ValueError("ساختار فایل تنظیمات معتبر نیست.")
        except Exception as exc:
            # Never crash on start-up and never destroy the user's file: keep a copy, run with defaults.
            backup = _backup_corrupt(CONFIG_PATH)
            where = f" نسخه‌ی پشتیبان: {backup.name}" if backup else ""
            LOAD_WARNINGS.append(f"فایل تنظیمات خراب بود و خوانده نشد ({exc}). با تنظیمات پیش‌فرض اجرا شد.{where}")
            return deepcopy(DEFAULTS)
        merged = {**DEFAULTS, **saved}
        # Earlier Voice pages exposed only the local pipeline and wrote "local"
        # automatically. That legacy value must not silently override the new
        # Gemini Live primary + local fallback default.
        if not bool(saved.get("voice_engine_migrated", False)):
            if str(saved.get("voice_engine") or "").strip().lower() == "local":
                merged["voice_engine"] = "gemini_live"
            merged["voice_engine_migrated"] = True
        # Remove obsolete cloud TTS voice selections; Gemini Live is primary and local Piper remains fallback.
        for stale_voice_key in (
            "voice_fa", "voice_en", "voice_ja", "voice_pitch", "voice_style", "voice_style_degree",
            "cloud_voice_provider", "cloud_voice_id", "cloud_voices",
        ):
            merged.pop(stale_voice_key, None)
        profiles = merged.get("character_voice")
        if isinstance(profiles, dict):
            for profile in profiles.values():
                if isinstance(profile, dict):
                    for stale_voice_key in ("voice_fa", "voice_en", "voice_ja", "voice_pitch", "voice_style",
                                            "voice_style_degree", "cloud_voice_provider", "cloud_voice_id"):
                        profile.pop(stale_voice_key, None)
        merged["api_registry"] = deepcopy(saved["api_registry"]) if isinstance(saved.get("api_registry"), dict) else {}      # never share DEFAULTS' dict
        # Stock persona texts from earlier versions are not user customisation: Kira's character now
        # lives in kira/personality.py, so clear them. A persona the user really edited is preserved
        # and is applied as "extra notes" below the core identity.
        if str(saved.get("persona") or "").strip() in STOCK_PERSONAS:
            merged["persona"] = DEFAULTS["persona"]
        saved_providers = saved.get("providers") if isinstance(saved.get("providers"), dict) else {}
        merged["providers"] = {**DEFAULTS["providers"], **saved_providers}
        for key, value in DEFAULTS["providers"].items():
            user_cfg = merged["providers"].get(key)
            merged["providers"][key] = {**value, **(user_cfg if isinstance(user_cfg, dict) else {})}
        merged["provider_order"] = normalize_provider_order(saved.get("provider_order"))
        # Migrate retired Groq model IDs (the old ID would only produce 404/400 errors).
        groq_cfg = merged["providers"]["groq"]
        old_model = groq_cfg.get("model")
        if old_model in RETIRED_GROQ_MODELS:
            groq_cfg["model"] = RETIRED_GROQ_MODELS[old_model]
            LOAD_WARNINGS.append(f"مدل Groq «{old_model}» توسط Groq بازنشسته شده؛ به {groq_cfg['model']} تغییر کرد.")
        for provider, pcfg in list(merged["providers"].items()):
            if not isinstance(pcfg, dict):
                merged["providers"].pop(provider)
                continue
            if provider == "ollama":
                continue
            pcfg["timeout"] = route_model.clamp_timeout(pcfg.get("timeout", 18), route_model.provider_kind(provider, pcfg))
            key = pcfg.get("api_key", "")
            if isinstance(key, str) and key.startswith("dpapi:"):
                try:
                    pcfg["api_key"] = unprotect(key)
                except Exception as exc:
                    pcfg["api_key"] = ""
                    LOAD_WARNINGS.append(
                        f"کلید {provider} با این حساب ویندوز رمزگشایی نشد ({exc}). کلید را دوباره در بخش Route وارد کن.")
        tkey = merged.get("tavily_api_key", "")
        if isinstance(tkey, str) and tkey.startswith("dpapi:"):
            try:
                merged["tavily_api_key"] = unprotect(tkey)
            except Exception as exc:
                merged["tavily_api_key"] = ""
                LOAD_WARNINGS.append(f"کلید Tavily با این حساب ویندوز رمزگشایی نشد ({exc}). دوباره وارد کن.")
        for stale in ("web_engine", "web_read_pages"):               # removed options (Google-through-Gemini / DuckDuckGo)
            merged.pop(stale, None)
        route_model.ensure_routes(merged)
        # 6144 tokens balance prompt capacity and KV-cache memory on 8 GB GPUs.
        # Upgrade known bundled defaults; custom values remain user-controlled.
        migrated_local_context = False
        ollama_cfg = merged.get("providers", {}).get("ollama") or {}
        try:
            if int(ollama_cfg.get("num_ctx") or 0) in (2048, 8192):
                ollama_cfg["num_ctx"] = 6144
                migrated_local_context = True
        except (TypeError, ValueError):
            pass
        for local_route in route_model.get_routes(merged):
            if local_route.get("provider") != "ollama":
                continue
            try:
                if int(local_route.get("num_ctx") or 0) in (2048, 8192):
                    route_model.update_route(merged, local_route["id"], num_ctx=6144)
                    migrated_local_context = True
            except (TypeError, ValueError):
                continue

        # Repair configurations written by versions where a local Route could be
        # switched on while the Ollama Provider master switch stayed off.
        migrated_local_route_state = False
        ollama_cfg = merged.get("providers", {}).get("ollama") or {}
        if (
            not bool(ollama_cfg.get("enabled", True))
            and any(route.get("provider") == "ollama" and route.get("enabled", True)
                    for route in route_model.get_routes(merged))
        ):
            ollama_cfg["enabled"] = True
            migrated_local_route_state = True

        # Migrate only the former bundled default; keep any user-selected model intact.
        migrated_local_model = False
        if str(ollama_cfg.get("model") or "").strip().lower() in LEGACY_LOCAL_CHAT_MODELS:
            ollama_cfg["model"] = LOCAL_UNCENSORED_MODEL
            migrated_local_model = True
        if str(merged.get("model") or "").strip().lower() in LEGACY_LOCAL_CHAT_MODELS:
            merged["model"] = LOCAL_UNCENSORED_MODEL
            migrated_local_model = True
        for local_route in route_model.get_routes(merged):
            if local_route.get("provider") == "ollama" and str(local_route.get("model") or "").strip().lower() in LEGACY_LOCAL_CHAT_MODELS:
                route_model.update_route(merged, local_route["id"], model=LOCAL_UNCENSORED_MODEL)
                migrated_local_model = True
        allowlist = merged.get("role_provider_allowlist")
        if not isinstance(allowlist, dict):
            merged["role_provider_allowlist"] = deepcopy(DEFAULTS["role_provider_allowlist"])
        else:
            for role, default_values in DEFAULTS["role_provider_allowlist"].items():
                value = allowlist.get(role)
                merged["role_provider_allowlist"][role] = list(value) if isinstance(value, (list, tuple)) else list(default_values)
        model_allowlist = merged.get("role_route_models")
        if not isinstance(model_allowlist, dict):
            merged["role_route_models"] = deepcopy(DEFAULTS["role_route_models"])
        else:
            for role, default_values in DEFAULTS["role_route_models"].items():
                value = model_allowlist.get(role)
                merged["role_route_models"][role] = list(value) if isinstance(value, (list, tuple)) else list(default_values)
        # The previous migration changed the Ollama model and Route but left the
        # role-level exact model allowlist untouched. That silently filtered the
        # only permitted local route, making ordinary chat report that Ollama
        # was unavailable even when the new model was installed and running.
        model_allowlist = merged.get("role_route_models") or {}
        for role, value in list(model_allowlist.items()):
            if not isinstance(value, (list, tuple)):
                continue
            migrated = [
                LOCAL_UNCENSORED_MODEL
                if str(model or "").strip().lower() in LEGACY_LOCAL_CHAT_MODELS
                else model
                for model in value
            ]
            if migrated != list(value):
                model_allowlist[role] = migrated
                migrated_local_model = True
        if migrated_local_model:
            LOAD_WARNINGS.append("مدل محلی پیش‌فرض به Qwen3.5-9B Abliterated Q4_K_M مهاجرت کرد.")
        if migrated_local_route_state:
            LOAD_WARNINGS.append("وضعیت قدیمی Ollama اصلاح شد: Provider محلی برای Route فعال دوباره روشن شد.")
        if migrated_local_context:
            LOAD_WARNINGS.append("ظرفیت Context مدل محلی از مقدار قدیمی ۲۰۴۸ به ۸۱۹۲ افزایش یافت.")
        if migrated_local_model or migrated_local_route_state or migrated_local_context:
            save_settings(merged)
        return merged
    fresh = deepcopy(DEFAULTS)
    route_model.ensure_routes(fresh)
    save_settings(fresh)
    return fresh


def save_settings(settings):
    stored = deepcopy(settings)
    stored["provider_order"] = normalize_provider_order(stored.get("provider_order"))
    if isinstance(stored.get("routes"), list):
        route_model.sync_legacy(stored)
    for provider, cfg in stored.get("providers", {}).items():
        if provider != "ollama" and isinstance(cfg, dict) and cfg.get("api_key"):
            cfg["api_key"] = protect(str(cfg["api_key"]))
    if stored.get("tavily_api_key"):
        stored["tavily_api_key"] = protect(str(stored["tavily_api_key"]))
    payload = json.dumps(stored, ensure_ascii=False, indent=2)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    temp_path = CONFIG_PATH.with_suffix(".json.tmp")
    temp_path.write_text(payload, encoding="utf-8")
    temp_path.replace(CONFIG_PATH)
