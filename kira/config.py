from pathlib import Path
import json
import math
import os
import time
from copy import deepcopy
from .secret_store import protect, unprotect
from . import routes as route_model
from .personality import STOCK_PERSONAS
from .settings_schema import (
    DEFAULT_OLLAMA_URL,
    DEFAULTS,
    LEGACY_LOCAL_CHAT_MODELS,
    LOCAL_UNCENSORED_MODEL,
    SETTINGS_SCHEMA_VERSION,
    SETTING_CHOICES,
    SETTING_RANGES,
)

ROOT = Path(__file__).resolve().parent.parent
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
VERSION = "1.2.6"
CLOUD_PROVIDERS = ("groq", "cloudflare", "mistral", "openrouter")
# Models Groq has retired -> current replacement (only applied to the exact retired IDs).
RETIRED_GROQ_MODELS = {
    "llama-3.3-70b-versatile": "openai/gpt-oss-120b",
    "llama-3.1-8b-instant": "openai/gpt-oss-20b",
}

# Human-readable notes produced while loading (shown in the chat window at startup).
LOAD_WARNINGS: list[str] = []


def ocr_runtime_paths():
    """Return the single supported source of native OCR executable/data paths.

    KIRA_TESSERACT_CMD and KIRA_TESSDATA_DIR are Kira-specific overrides.
    TESSERACT_CMD and TESSDATA_PREFIX remain supported as standard fallbacks.
    No native OCR binary or language pack is downloaded by the application.
    """
    def configured_path(*names):
        for name in names:
            value = str(os.environ.get(name) or "").strip().strip('"').strip("'")
            if value:
                return str(Path(os.path.expandvars(value)).expanduser())
        return ""

    executable = configured_path("KIRA_TESSERACT_CMD", "TESSERACT_CMD")
    tessdata_dir = configured_path("KIRA_TESSDATA_DIR", "TESSDATA_PREFIX")
    candidates = []
    if not executable:
        for variable in ("ProgramFiles", "ProgramFiles(x86)"):
            root = str(os.environ.get(variable) or "").strip()
            if root:
                candidates.append(str(Path(root) / "Tesseract-OCR" / "tesseract.exe"))
        local = str(os.environ.get("LOCALAPPDATA") or "").strip()
        if local:
            candidates.append(str(Path(local) / "Programs" / "Tesseract-OCR" / "tesseract.exe"))
    return {
        "executable": executable,
        "executable_candidates": tuple(candidates),
        "tessdata_dir": tessdata_dir,
    }


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


def _default_settings():
    """Return a fresh runtime settings snapshot carrying the current schema version."""
    settings = deepcopy(DEFAULTS)
    settings["settings_version"] = SETTINGS_SCHEMA_VERSION
    return settings


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


def _migrate_v0_to_v1(data):
    """Remove settings retired before schema versioning; preserve all supported choices."""
    for key in ("web_engine", "web_read_pages", "voice_fa", "voice_en", "voice_ja",
                "voice_pitch", "voice_style", "voice_style_degree", "cloud_voice_provider",
                "cloud_voice_id", "cloud_voices"):
        data.pop(key, None)
    profiles = data.get("character_voice")
    if isinstance(profiles, dict):
        for profile in profiles.values():
            if isinstance(profile, dict):
                for key in ("voice_fa", "voice_en", "voice_ja", "voice_pitch", "voice_style",
                            "voice_style_degree", "cloud_voice_provider", "cloud_voice_id"):
                    profile.pop(key, None)
    return data


def _migrate_v1_to_v2(data, warnings=None):
    """Replace retired Groq model IDs in every persisted reference, without touching user choices."""
    migrated = {}

    providers = data.get("providers")
    groq = providers.get("groq") if isinstance(providers, dict) else None
    if isinstance(groq, dict):
        old_model = groq.get("model")
        if old_model in RETIRED_GROQ_MODELS:
            migrated[old_model] = RETIRED_GROQ_MODELS[old_model]
            groq["model"] = migrated[old_model]

    # Routes are the live provider/model references. Updating only the legacy
    # provider mirror leaves a stale route that can still be selected at runtime.
    routes = data.get("routes")
    if isinstance(routes, list):
        for route in routes:
            if not isinstance(route, dict) or route.get("provider") != "groq":
                continue
            old_model = route.get("model")
            if old_model in RETIRED_GROQ_MODELS:
                migrated.setdefault(old_model, RETIRED_GROQ_MODELS[old_model])
                route["model"] = migrated[old_model]

    # Role model allowlists are exact model-ID filters. Keep their structure and
    # order while replacing only the provider IDs that are known to be retired.
    model_allowlist = data.get("role_route_models")
    role_providers = data.get("role_provider_allowlist")
    if isinstance(model_allowlist, dict):
        for role, models in list(model_allowlist.items()):
            if not isinstance(models, (list, tuple)):
                continue
            allowed = (
                role_providers.get(role)
                if isinstance(role_providers, dict)
                else DEFAULTS["role_provider_allowlist"].get(role, ())
            )
            if not isinstance(allowed, (list, tuple)) or "groq" not in allowed:
                continue
            updated = [
                RETIRED_GROQ_MODELS.get(model, model)
                if isinstance(model, str) else model
                for model in models
            ]
            if updated != list(models):
                model_allowlist[role] = updated
                for old_model in models:
                    if isinstance(old_model, str) and old_model in RETIRED_GROQ_MODELS:
                        migrated.setdefault(old_model, RETIRED_GROQ_MODELS[old_model])

    if warnings is not None:
        for old_model, new_model in migrated.items():
            warnings.append(
                f"مدل Groq «{old_model}» بازنشسته شده؛ تمام ارجاع‌های آن به {new_model} مهاجرت کردند."
            )
    return data


def _migrate_v2_to_v3(data, warnings=None):
    """Honor a disabled Ollama Provider by disabling contradictory enabled routes."""
    providers = data.get("providers")
    ollama = providers.get("ollama") if isinstance(providers, dict) else None
    routes = data.get("routes")
    disabled_routes = []
    if isinstance(ollama, dict) and ollama.get("enabled") is False and isinstance(routes, list):
        for route in routes:
            if (
                isinstance(route, dict)
                and route.get("provider") == "ollama"
                and route.get("enabled", True)
            ):
                route["enabled"] = False
                disabled_routes.append(str(route.get("id") or "ollama"))
    if disabled_routes and warnings is not None:
        warnings.append(
            "Routeهای Ollama خاموش شدند، چون Provider در تنظیمات کاربر غیرفعال بود: "
            + ", ".join(disabled_routes)
        )
    return data


def _migrate_v3_to_v4(data, warnings=None):
    """Move provider/model discovery observations out of persistent user settings."""
    for key in ("api_registry", "ollama_models", "model_catalog_refreshed_at", "model_tests"):
        data.pop(key, None)
    return data


def _migrate_v4_to_v5(data, warnings=None):
    """Remove the obsolete Voice migration marker; the selected Voice engine is user data."""
    data.pop("voice_engine_migrated", None)
    return data


def _migrate_v5_to_v6(data, warnings=None):
    """Remove obsolete appearance migration flags without changing the user's appearance."""
    data.pop("appearance_glow_adjusted", None)
    data.pop("appearance_neon_shooter_v1", None)
    return data


def _migrate_v6_to_v7(data, warnings=None):
    """Move automatic route-health explanations out of persistent user settings."""
    old_notes = data.pop("route_notes", None)
    if old_notes and warnings is not None:
        warnings.append(
            "یادداشت‌های خودکار وضعیت Route به دادهٔ تشخیص موقت منتقل شدند؛ "
            "تنظیمات انتخابی Route حفظ شد."
        )
    return data


def _migrate_settings(saved, *, warnings=None):
    """Apply each schema migration once to a private copy, reporting side effects explicitly."""
    if not isinstance(saved, dict):
        raise ValueError("ساختار فایل تنظیمات معتبر نیست.")
    migrated = deepcopy(saved)
    raw_version = migrated.get("settings_version", 0)
    if isinstance(raw_version, bool):
        raise ValueError("نسخهٔ تنظیمات معتبر نیست.")
    try:
        version = int(raw_version)
    except (TypeError, ValueError) as exc:
        raise ValueError("نسخهٔ تنظیمات معتبر نیست.") from exc
    if isinstance(raw_version, float) and not raw_version.is_integer():
        raise ValueError("نسخهٔ تنظیمات معتبر نیست.")
    if version < 0 or version > SETTINGS_SCHEMA_VERSION:
        raise ValueError(f"نسخهٔ تنظیمات پشتیبانی نمی‌شود: {version}")
    migrations = {
        0: _migrate_v0_to_v1,
        1: lambda value: _migrate_v1_to_v2(value, warnings=warnings),
        2: lambda value: _migrate_v2_to_v3(value, warnings=warnings),
        3: lambda value: _migrate_v3_to_v4(value, warnings=warnings),
        4: lambda value: _migrate_v4_to_v5(value, warnings=warnings),
        5: lambda value: _migrate_v5_to_v6(value, warnings=warnings),
        6: lambda value: _migrate_v6_to_v7(value, warnings=warnings),
    }
    while version < SETTINGS_SCHEMA_VERSION:
        migrated = migrations[version](migrated)
        version += 1
        migrated["settings_version"] = version
    migrated["settings_version"] = SETTINGS_SCHEMA_VERSION
    return migrated


def _validate_value(value, default, path, repaired):
    """Validate a known schema value recursively while preserving unknown user keys."""
    valid = True
    if isinstance(default, bool):
        valid = isinstance(value, bool)
    elif isinstance(default, int):
        valid = isinstance(value, int) and not isinstance(value, bool)
    elif isinstance(default, float):
        try:
            valid = (isinstance(value, (int, float)) and not isinstance(value, bool)
                     and math.isfinite(value))
        except (OverflowError, TypeError):
            valid = False
    elif isinstance(default, str):
        valid = isinstance(value, str)
    elif isinstance(default, list):
        valid = isinstance(value, list)
        if valid and default and isinstance(default[0], str):
            valid = all(isinstance(item, str) for item in value)
    elif isinstance(default, dict):
        valid = isinstance(value, dict)
        if valid:
            for child_key, child_default in default.items():
                if child_key in value:
                    value[child_key] = _validate_value(
                        value[child_key], child_default, f"{path}.{child_key}", repaired
                    )
                else:
                    value[child_key] = deepcopy(child_default)
                    repaired.append(f"{path}.{child_key}")
    choices = SETTING_CHOICES.get(path)
    if valid and choices is not None and value not in choices:
        valid = False
    bounds = SETTING_RANGES.get(path)
    if valid and bounds is not None:
        try:
            valid = bounds[0] <= value <= bounds[1]
        except (TypeError, ValueError, OverflowError):
            valid = False
    if not valid:
        repaired.append(path)
        return deepcopy(default)
    return value


def _validate_settings(settings):
    """Repair malformed known values against the canonical schema, retaining unknown keys."""
    if not isinstance(settings, dict):
        raise ValueError("ساختار تنظیمات معتبر نیست.")
    repaired = []
    for key, default in DEFAULTS.items():
        if key in settings:
            settings[key] = _validate_value(settings[key], default, key, repaired)

    # Third-party providers are extensible, but each provider entry must remain a mapping.
    providers = settings.get("providers")
    if isinstance(providers, dict):
        for provider, value in tuple(providers.items()):
            if not isinstance(value, dict):
                providers.pop(provider)
                repaired.append(f"providers.{provider}")
    if repaired:
        LOAD_WARNINGS.append(
            "مقادیر نامعتبر تنظیمات با پیش‌فرض معتبر جایگزین شدند: " + ", ".join(repaired)
        )
    settings["settings_version"] = SETTINGS_SCHEMA_VERSION
    return settings

def _validate_route_overrides(settings):
    """Drop malformed optional route limits before routes.ensure_routes converts them."""
    routes = settings.get("routes")
    if not isinstance(routes, list):
        return False
    repaired = []
    for index, route in enumerate(routes):
        if not isinstance(route, dict):
            continue
        for key in ("num_ctx", "num_predict"):
            if key not in route:
                continue
            value = route[key]
            if value is None or value == "" or (not isinstance(value, bool) and value == 0):
                continue
            try:
                number = int(value) if not isinstance(value, bool) else 0
            except (TypeError, ValueError, OverflowError):
                number = 0
            if number <= 0:
                route.pop(key, None)
                repaired.append(f"routes[{index}].{key}")
            else:
                route[key] = number
    if repaired:
        LOAD_WARNINGS.append(
            "محدودیت‌های نامعتبر Route حذف شدند تا مقدار Provider به ارث برسد: "
            + ", ".join(repaired)
        )
    return bool(repaired)


def load_settings():
    LOAD_WARNINGS.clear()
    LOAD_WARNINGS.extend(prepare_user_data())
    if CONFIG_PATH.exists():
        try:
            saved = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            source_settings_version = saved.get("settings_version", 0) if isinstance(saved, dict) else 0
            saved = _migrate_settings(saved, warnings=LOAD_WARNINGS)
            if not isinstance(saved, dict):
                raise ValueError("ساختار فایل تنظیمات معتبر نیست.")
            # These names are reserved for process-local observations even when a
            # file claims to be at the current schema version.
            runtime_keys = ("api_registry", "ollama_models", "model_catalog_refreshed_at", "model_tests", "route_notes")
            stripped_runtime_keys = [key for key in runtime_keys if key in saved]
            for key in stripped_runtime_keys:
                saved.pop(key, None)
            if stripped_runtime_keys:
                LOAD_WARNINGS.append(
                    "داده‌های موقت تشخیص از فایل تنظیمات حذف شدند: "
                    + ", ".join(stripped_runtime_keys)
                )
        except Exception as exc:
            # Never crash on start-up and never destroy the user's file: keep a copy, run with defaults.
            backup = _backup_corrupt(CONFIG_PATH)
            where = f" نسخه‌ی پشتیبان: {backup.name}" if backup else ""
            LOAD_WARNINGS.append(f"فایل تنظیمات خراب بود و خوانده نشد ({exc}). با تنظیمات پیش‌فرض اجرا شد.{where}")
            return _default_settings()
        merged = {**DEFAULTS, **saved}
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
        # Validate merged provider values before route normalization: routes.make_route
        # converts numeric overrides and must never be handed malformed persisted data.
        before_validation = deepcopy(merged)
        merged = _validate_settings(merged)
        settings_repaired = merged != before_validation or bool(stripped_runtime_keys)
        merged["provider_order"] = normalize_provider_order(saved.get("provider_order"))
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
        settings_repaired = _validate_route_overrides(merged) or settings_repaired
        route_model.ensure_routes(merged)
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
        before_final_validation = deepcopy(merged)
        merged = _validate_settings(merged)
        settings_repaired = settings_repaired or merged != before_final_validation
        if (int(source_settings_version or 0) < SETTINGS_SCHEMA_VERSION
                or settings_repaired):
            save_settings(merged)
        return merged
    fresh = _default_settings()
    route_model.ensure_routes(fresh)
    save_settings(fresh)
    return fresh


def save_settings(settings):
    stored = deepcopy(settings)
    # Runtime and detected observations are process-local; never write them to settings.json.
    for runtime_key in ("api_registry", "ollama_models", "model_catalog_refreshed_at", "model_tests", "route_notes"):
        stored.pop(runtime_key, None)
    # Every persistence boundary validates against the same schema as load-time recovery.
    stored = _validate_settings(stored)
    _validate_route_overrides(stored)
    stored["settings_version"] = SETTINGS_SCHEMA_VERSION
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
