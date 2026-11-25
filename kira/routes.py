"""Route model: Providers and Routes are separate things.

* A **Provider** is a connection (API key, base URL, account id, local/cloud). Stored in settings["providers"].
* A **Route** is one model reachable through a provider, with its own enabled flag, timeout, cooldown and priority.
  Stored in settings["routes"]; the list order IS the priority / failover order.

Settings written by v1.4.x / v1.5.0 (no "routes" key) are migrated without touching any API key or option:
one route per old provider, in the old provider_order.  Pure logic, no Qt, fully unit-tested.
"""
from __future__ import annotations

import ast
import re
from copy import deepcopy

BUILTIN = {
    "groq": {"label": "Groq", "kind": "cloud", "type": "openai_compat", "model": "openai/gpt-oss-120b"},
    "cloudflare": {"label": "Cloudflare Workers AI", "kind": "cloud", "type": "cloudflare", "model": "@cf/meta/llama-3.1-8b-instruct"},
    "mistral": {"label": "Mistral", "kind": "cloud", "type": "openai_compat", "model": "mistral-small-latest"},
    "openrouter": {"label": "OpenRouter", "kind": "cloud", "type": "openai_compat", "model": ""},
    "ollama": {"label": "Ollama", "kind": "local", "type": "ollama", "model": "qwen3.5:4b"},
}
DEFAULT_ORDER = ["groq", "cloudflare", "mistral", "openrouter", "ollama"]
CLOUD_TIMEOUT = (5, 60)
LOCAL_TIMEOUT = (10, 600)
DEFAULT_CLOUD_TIMEOUT = 18
DEFAULT_LOCAL_TIMEOUT = 180
DEFAULT_COOLDOWN = 45                  # seconds after a transient failure (network / timeout / 5xx)
COOLDOWN_RANGE = (0, 3600)


# ---------------- provider helpers ----------------
def provider_type(name, cfg=None):
    if name in BUILTIN:
        return BUILTIN[name]["type"]
    return str((cfg or {}).get("type") or "openai_compat")


def provider_kind(name, cfg=None):
    """'cloud' or 'local'."""
    if name in BUILTIN:
        return BUILTIN[name]["kind"]
    return "local" if (cfg or {}).get("local") else "cloud"


def provider_label(name, cfg=None):
    if name in BUILTIN:
        return BUILTIN[name]["label"]
    return str((cfg or {}).get("label") or name)


def requires_key(name, cfg=None):
    """Whether the provider needs an API key. Ollama is the only built-in keyless provider."""
    return provider_type(name, cfg) != "ollama" and not (cfg or {}).get("local")


def slugify(text):
    s = re.sub(r"[^a-z0-9]+", "-", str(text or "").lower()).strip("-")
    return s[:24] or "provider"


def new_provider_id(settings, label):
    base = "custom-" + slugify(label)
    providers = settings.get("providers", {})
    pid, n = base, 2
    while pid in providers or pid in BUILTIN:
        pid, n = f"{base}-{n}", n + 1
    return pid


def add_provider(settings, label, base_url, api_key="", local=False, enabled=True):
    """Add a custom OpenAI-compatible provider (LM Studio, vLLM, Together, DeepInfra, ...). Returns its id."""
    label, base_url = str(label or "").strip(), str(base_url or "").strip().rstrip("/")
    if not label:
        raise ValueError("نام Provider خالی است.")
    if not re.match(r"^https?://", base_url, re.I):
        raise ValueError("آدرس باید با http:// یا https:// شروع شود.")
    pid = new_provider_id(settings, label)
    settings.setdefault("providers", {})[pid] = {
        "type": "openai_compat", "label": label, "base_url": base_url, "api_key": str(api_key or "").strip(),
        "local": bool(local), "enabled": bool(enabled), "timeout": DEFAULT_LOCAL_TIMEOUT if local else DEFAULT_CLOUD_TIMEOUT}
    return pid


def _check_url(url):
    url = str(url or "").strip().rstrip("/")
    if not re.match(r"^https?://\S+$", url, re.I):
        raise ValueError("آدرس باید با http:// یا https:// شروع شود و فاصله نداشته باشد.")
    return url


def update_provider(settings, pid, *, label=None, base_url=None, api_key=None, account_id=None, local=None, quota_scope=None):
    """Edit a registered provider in place. Its id never changes, so every route / model attached to it stays attached.

    None = leave as it is. api_key: None or "" keeps the saved key (changing it is optional). base_url "" on a built-in
    provider removes the override (official endpoint again). All values are validated BEFORE anything is changed.
    Returns the list of changed field names."""
    cfg = settings.get("providers", {}).get(pid)
    if cfg is None:
        raise KeyError(pid)
    builtin = pid in BUILTIN
    updates = {}
    if label is not None and not builtin:
        label = str(label).strip()
        if not label:
            raise ValueError("نام Provider خالی است.")
        if any(o != pid and provider_label(o, c).lower() == label.lower() for o, c in settings["providers"].items()):
            raise ValueError("Provider دیگری با همین نام وجود دارد.")
        updates["label"] = label
    if base_url is not None and pid != "cloudflare" and provider_type(pid, cfg) != "cloudflare":
        base_url = str(base_url).strip()
        if base_url:
            updates["base_url"] = _check_url(base_url)
        elif builtin:
            updates["base_url"] = None                      # back to the official endpoint
        else:
            raise ValueError("آدرس (Base URL) برای Provider سفارشی لازم است.")
    if account_id is not None and (pid == "cloudflare" or provider_type(pid, cfg) == "cloudflare"):
        account_id = str(account_id).strip()
        if not account_id:
            raise ValueError("Account ID خالی است.")
        updates["account_id"] = account_id
    if local is not None and not builtin:
        updates["local"] = bool(local)
    if api_key is not None and str(api_key).strip():
        updates["api_key"] = str(api_key).strip()
    if quota_scope is not None:
        scope = str(quota_scope).strip()[:100]
        updates["quota_scope"] = scope or None
    changed = []
    for key, value in updates.items():
        if value is None:
            if key in cfg:
                cfg.pop(key)
                changed.append(key)
        elif cfg.get(key) != value:
            cfg[key] = value
            changed.append(key)
    if "local" in changed:                                   # routes keep existing, but timeouts follow the new kind
        ensure_routes(settings)
    return changed


def remove_provider(settings, pid):
    """Only custom providers can be removed (built-ins keep their keys). Their routes go with them. Returns removed route ids."""
    if pid in BUILTIN:
        raise ValueError("Providerهای پیش‌فرض حذف نمی‌شوند؛ فقط می‌توان آن‌ها را غیرفعال کرد.")
    settings.get("providers", {}).pop(pid, None)
    routes = settings.get("routes")
    removed = []
    if routes is not None:
        keep = []
        for r in routes:
            (removed if r.get("provider") == pid else keep).append(r.get("id") if r.get("provider") == pid else r)
        settings["routes"] = [r for r in keep if isinstance(r, dict)]
    if settings.get("manual_route_id") in removed:
        settings["manual_route_id"] = ""
    sync_legacy(settings)
    return removed


# ---------------- route construction / normalisation ----------------
def is_google(provider, cfg=None):
    """True for Google AI Studio / Gemini providers (built in by id, or any provider pointing at its API)."""
    return provider == "google" or "generativelanguage.googleapis.com" in str((cfg or {}).get("base_url") or "").lower()


def effective_timeout(route, cfg):
    """Seconds a request on this route may take. Shared by chat and connection tests."""
    timeout = route.get("timeout") or (cfg or {}).get("timeout", DEFAULT_CLOUD_TIMEOUT)
    if is_google(route.get("provider"), cfg) and int(timeout or DEFAULT_CLOUD_TIMEOUT) <= DEFAULT_CLOUD_TIMEOUT:
        return CLOUD_TIMEOUT[1]
    return timeout


def clamp_timeout(value, kind):
    lo, hi = LOCAL_TIMEOUT if kind == "local" else CLOUD_TIMEOUT
    default = DEFAULT_LOCAL_TIMEOUT if kind == "local" else DEFAULT_CLOUD_TIMEOUT
    try:
        return max(lo, min(int(value), hi))
    except (TypeError, ValueError):
        return default


def clamp_cooldown(value):
    try:
        return max(COOLDOWN_RANGE[0], min(int(value), COOLDOWN_RANGE[1]))
    except (TypeError, ValueError):
        return DEFAULT_COOLDOWN


def normalize_model_id(value):
    """Extract a provider model ID from catalog objects and legacy stringified dictionaries."""
    if isinstance(value, dict):
        for key in ("id", "model", "name"):
            candidate = value.get(key)
            if candidate is not None and candidate != "":
                return normalize_model_id(candidate)
        return ""
    if value is None:
        return ""
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("{") and text.endswith("}"):
            try:
                parsed = ast.literal_eval(text)
            except (SyntaxError, ValueError):
                parsed = None
            if isinstance(parsed, dict):
                return normalize_model_id(parsed)
        return text
    return str(value).strip()


def make_route(route_id, provider, model, enabled=True, timeout=None, cooldown=None, kind=None, **extra):
    kind = kind or provider_kind(provider)
    route = {"id": str(route_id), "provider": str(provider), "model": normalize_model_id(model), "enabled": bool(enabled),
             "timeout": clamp_timeout(timeout, kind), "cooldown": clamp_cooldown(cooldown if cooldown is not None else DEFAULT_COOLDOWN)}
    for key in ("num_ctx", "num_predict"):                       # optional per-route Ollama overrides (0/absent = inherit)
        if extra.get(key):
            route[key] = int(extra[key])
    return route


def derive_routes(settings):
    """Routes implied by the old layout (provider_order + one model per provider). Does not modify settings."""
    providers = settings.get("providers", {})
    order = []
    for name in list(settings.get("provider_order") or []) + DEFAULT_ORDER + [p for p in providers if p not in DEFAULT_ORDER]:
        if name not in order and (name in BUILTIN or name in providers):
            order.append(name)
    routes = []
    for name in order:
        cfg = providers.get(name) or {}
        kind = provider_kind(name, cfg)
        if name == "ollama":
            model = settings.get("model") or cfg.get("model") or BUILTIN["ollama"]["model"]
            enabled = bool(cfg.get("enabled", True))
        else:
            model = cfg.get("model", BUILTIN.get(name, {}).get("model", ""))
            enabled = True                  # provider-level "enabled" (+ key) still gates it; the route itself is on
        routes.append(make_route(name, name, model, enabled, cfg.get("timeout"), None, kind,
                                 num_ctx=cfg.get("num_ctx") if name == "ollama" else None,
                                 num_predict=cfg.get("num_predict") if name == "ollama" else None))
    return routes


def get_routes(settings):
    """The live route list: stored routes if present, otherwise derived from the legacy layout."""
    stored = settings.get("routes")
    if isinstance(stored, list):
        return [r for r in stored if isinstance(r, dict) and r.get("id") and r.get("provider")]
    return derive_routes(settings)


def ensure_routes(settings):
    """Persist and repair routes, collapsing duplicate provider/model entries."""
    settings.setdefault("providers", {})
    # Remove configurations persisted by the retired browser-backed Reverse API.
    settings["providers"].pop("reverse_api", None)
    stored = settings.get("routes")
    routes = derive_routes(settings) if not isinstance(stored, list) else stored
    clean, seen, model_positions, id_remap = [], set(), {}, {}
    for r in routes:
        if not isinstance(r, dict) or not r.get("provider"):
            continue
        provider = str(r["provider"])
        if provider not in BUILTIN and provider not in settings["providers"]:
            continue                                            # provider was removed: drop the orphan route
        rid = str(r.get("id") or provider)
        base, n = rid, 2
        while rid in seen:
            rid, n = f"{base}-{n}", n + 1
        seen.add(rid)
        kind = provider_kind(provider, settings["providers"].get(provider))
        item = make_route(rid, provider, r.get("model", ""), r.get("enabled", True), r.get("timeout"), r.get("cooldown"), kind,
                          num_ctx=r.get("num_ctx"), num_predict=r.get("num_predict"))
        if r.get("label"):
            item["label"] = str(r["label"])[:60]

        model = str(item.get("model") or "").strip()
        model_key = (provider, model.casefold()) if model else None
        if model_key and model_key in model_positions:
            # add_route already prevents duplicate model IDs. Collapse duplicates
            # left by older builds or repeated imports, preserving enabled state
            # and the largest per-route generation limits.
            existing = clean[model_positions[model_key]]
            existing["enabled"] = bool(existing.get("enabled", True) or item.get("enabled", True))
            for option in ("num_ctx", "num_predict"):
                values = []
                for candidate in (existing.get(option), item.get(option)):
                    try:
                        number = int(candidate or 0)
                    except (TypeError, ValueError):
                        number = 0
                    if number > 0:
                        values.append(number)
                if values:
                    existing[option] = max(values)
                else:
                    existing.pop(option, None)
            id_remap[rid] = existing["id"]
            continue

        if model_key:
            model_positions[model_key] = len(clean)
        clean.append(item)

    for name in BUILTIN:                                         # built-in providers always keep at least one route
        if not any(r["provider"] == name for r in clean):
            cfg = settings["providers"].get(name) or {}
            model = (settings.get("model") if name == "ollama" else cfg.get("model")) or BUILTIN[name]["model"]
            rid = name if name not in seen else f"{name}-2"
            clean.append(make_route(rid, name, model, name == "ollama" and bool(cfg.get("enabled", True)), cfg.get("timeout")))
            seen.add(rid)

    # Keep manual/default choices and route health notes attached to the
    # surviving route when a duplicate ID is collapsed.
    for field in ("manual_route_id", "default_route_id"):
        selected = settings.get(field)
        if selected in id_remap:
            settings[field] = id_remap[selected]
    notes = settings.get("route_notes")
    if isinstance(notes, dict):
        for old_id, new_id in id_remap.items():
            if old_id in notes:
                notes.setdefault(new_id, notes[old_id])
                notes.pop(old_id, None)

    settings["routes"] = clean
    ids = {r["id"] for r in clean}
    notes = settings.get("route_notes")
    if isinstance(notes, dict):
        for route_id in tuple(notes):
            if route_id not in ids:
                notes.pop(route_id, None)
    if settings.get("manual_route_id") not in ids:
        settings["manual_route_id"] = ""
    if settings.get("default_route_id") not in ids:
        settings["default_route_id"] = clean[0]["id"] if clean else ""
    settings.setdefault("failover_enabled", True)
    sync_legacy(settings)
    return settings
def sync_legacy(settings):
    """Keep the old provider_order (and the Ollama model mirror) consistent with the routes (older versions can still read it)."""
    routes = settings.get("routes")
    if not isinstance(routes, list):
        return
    order = []
    for r in routes:
        if r["provider"] not in order:
            order.append(r["provider"])
    for name in DEFAULT_ORDER:
        if name not in order:
            order.append(name)
    settings["provider_order"] = order


def find_route(settings, route_id):
    for r in get_routes(settings):
        if r["id"] == route_id:
            return r
    return None


# ---------------- mutations (all return the affected route/ids; callers save settings) ----------------
def _mutable(settings):
    if not isinstance(settings.get("routes"), list):
        ensure_routes(settings)
    return settings["routes"]


def unique_route_id(settings, provider):
    ids = {r["id"] for r in _mutable(settings)}
    rid, n = provider, 2
    while rid in ids:
        rid, n = f"{provider}-{n}", n + 1
    return rid


def add_route(settings, provider, model, enabled=True, timeout=None, cooldown=None, position=None, **extra):
    routes = _mutable(settings)
    cfg = settings.get("providers", {}).get(provider)
    if provider not in BUILTIN and cfg is None:
        raise ValueError("Provider ناشناخته است.")
    model = str(model or "").strip()
    if not model:
        raise ValueError("شناسه‌ی مدل (Model ID) خالی است.")
    if any(r["provider"] == provider and r["model"] == model for r in routes):
        raise ValueError(f"این مدل از قبل برای {provider} وجود دارد.")
    route = make_route(unique_route_id(settings, provider), provider, model, enabled, timeout, cooldown,
                       provider_kind(provider, cfg), **extra)
    if position is None:
        routes.append(route)
    else:
        routes.insert(max(0, min(position, len(routes))), route)
    # Enabling a local Ollama Route must also enable its shared Provider.
    # Otherwise the Route switch appears green while HybridRouter rejects it
    # at provider-level eligibility before sending any request.
    if provider == "ollama" and enabled:
        settings.setdefault("providers", {}).setdefault("ollama", {})["enabled"] = True
    sync_legacy(settings)
    return route


def set_provider_enabled(settings, provider, enabled):
    """Set a provider's master switch without leaving contradictory enabled routes.

    Disabling local Ollama disables all of its routes. Re-enabling the provider
    leaves model routes off until the user explicitly enables the desired model.
    """
    cfg = settings.setdefault("providers", {}).get(provider)
    if not isinstance(cfg, dict):
        raise KeyError(provider)
    cfg["enabled"] = bool(enabled)
    if provider == "ollama" and not enabled:
        for route in list(_mutable(settings)):
            if route.get("provider") == "ollama" and route.get("enabled", True):
                update_route(settings, route["id"], enabled=False)
    return cfg["enabled"]


def update_route(settings, route_id, **changes):
    route = next((r for r in _mutable(settings) if r["id"] == route_id), None)
    if route is None:
        raise KeyError(route_id)
    kind = provider_kind(route["provider"], settings.get("providers", {}).get(route["provider"]))
    if "model" in changes:
        model = normalize_model_id(changes["model"])
        if not model:
            raise ValueError("شناسه‌ی مدل (Model ID) خالی است.")
        route["model"] = model
    if "enabled" in changes:
        route["enabled"] = bool(changes["enabled"])
        # The Route and Provider switches are both required by eligibility().
        # When a user explicitly enables a local Ollama Route, bring its
        # Provider online as part of the same settings mutation.
        if route["provider"] == "ollama" and route["enabled"]:
            settings.setdefault("providers", {}).setdefault("ollama", {})["enabled"] = True
    if "timeout" in changes:
        route["timeout"] = clamp_timeout(changes["timeout"], kind)
    if "cooldown" in changes:
        route["cooldown"] = clamp_cooldown(changes["cooldown"])
    for key in ("num_ctx", "num_predict"):
        if key in changes:
            if changes[key]:
                route[key] = int(changes[key])
            else:
                route.pop(key, None)
    if "label" in changes:
        if changes["label"]:
            route["label"] = str(changes["label"])[:60]
        else:
            route.pop("label", None)
    sync_legacy(settings)
    return route


def remove_route(settings, route_id):
    routes = _mutable(settings)
    if not any(r["id"] == route_id for r in routes):
        raise KeyError(route_id)
    settings["routes"] = [r for r in routes if r["id"] != route_id]
    if settings.get("manual_route_id") == route_id:
        settings["manual_route_id"] = ""
    if settings.get("default_route_id") == route_id:
        settings["default_route_id"] = settings["routes"][0]["id"] if settings["routes"] else ""
    sync_legacy(settings)


def set_enabled(settings, route_id, enabled):
    return update_route(settings, route_id, enabled=enabled)


def move_route(settings, route_id, new_index):
    routes = _mutable(settings)
    idx = next((i for i, r in enumerate(routes) if r["id"] == route_id), None)
    if idx is None:
        raise KeyError(route_id)
    item = routes.pop(idx)
    routes.insert(max(0, min(int(new_index), len(routes))), item)
    sync_legacy(settings)
    return [r["id"] for r in routes]


def reorder(settings, ordered_ids):
    """Apply an order coming from drag & drop. Unknown ids are ignored; routes not mentioned keep their relative order at the end."""
    routes = _mutable(settings)
    by_id = {r["id"]: r for r in routes}
    new = [by_id[i] for i in ordered_ids if i in by_id]
    seen = {r["id"] for r in new}
    new += [r for r in routes if r["id"] not in seen]
    settings["routes"] = new
    sync_legacy(settings)
    return [r["id"] for r in new]


def set_default(settings, route_id):
    """The default route is the one tried first when no manual choice exists: it moves to the top and is remembered."""
    move_route(settings, route_id, 0)
    settings["default_route_id"] = route_id
    return route_id


def set_manual(settings, route_id):
    """Manual choice ('' = automatic). Wins over priority; failover (if enabled) may still move on to the next route."""
    if route_id and not find_route(settings, route_id):
        raise KeyError(route_id)
    settings["manual_route_id"] = route_id or ""


def add_ollama_models(settings, installed_names, enabled=False):
    """Add one route per installed Ollama model that has none yet. New ones are OFF so nothing heavy starts by surprise."""
    have = {r["model"] for r in _mutable(settings) if r["provider"] == "ollama"}
    added = []
    for name in installed_names:
        name = str(name or "").strip()
        if name and name not in have:
            added.append(add_route(settings, "ollama", name, enabled=enabled))
            have.add(name)
    return added


def catalog_entries(models):
    """Discovery results as a list of dicts with an 'id'. Accepts the list of dicts discovery returns, a dict keyed by id,
    or plain id strings, so callers never have to guess the shape."""
    entries = []
    items = models.items() if isinstance(models, dict) else ((None, m) for m in (models or ()))
    for key, item in items:
        if isinstance(item, dict):
            entry = dict(item)
            if key is not None:
                entry.setdefault("id", key)
        else:
            entry = {"id": key if key is not None else item}
        mid = str(entry.get("id") or "").strip()
        if mid:
            entry["id"] = mid
            entries.append(entry)
    return entries


def catalog_ids(models):
    return [e["id"] for e in catalog_entries(models)]


def catalog_free(models):
    """{model id: True | False | None} - the 'free' flag discovery reported (None = unknown)."""
    return {e["id"]: e.get("free") for e in catalog_entries(models)}


AUTO_DISABLE_AFTER = 2          # consecutive "model not available" answers before a route is switched off by itself


def disable_route(settings, route_id, reason):
    """Switch a route OFF (never deletes it) and remember why in settings["route_notes"].

    Explicitly unavailable routes must be allowed to turn off even when they are
    the last enabled route. Keeping a broken local route artificially enabled
    makes every request fail instead of reporting that no route is configured.
    Returns True when the route was actually disabled."""
    route = find_route(settings, route_id)
    if route is None or not route.get("enabled", True):
        return False
    update_route(settings, route_id, enabled=False)
    settings.setdefault("route_notes", {})[route_id] = str(reason)[:200]
    return True


def route_note(settings, route_id):
    """Why a route was switched off automatically ('' once the user turned it back on)."""
    route = find_route(settings, route_id)
    if route is None or route.get("enabled", True):
        return ""
    return str((settings.get("route_notes") or {}).get(route_id) or "")


def _pick_replacement(available, prefer, free):
    for model in prefer or ():
        if model in available:
            return model
    for model in sorted(available):
        if (free or {}).get(model) is True:
            return model
    return sorted(available)[0]


def reconcile_provider_models(settings, provider, available_models, *, free=None, prefer=()):
    """Remove stale routes after a successful, non-empty provider catalog refresh.

    If every route for a built-in provider points at a removed model, retain the
    first route identity and retarget it to a currently advertised model (one of
    ``prefer`` first, then a free one). This preserves default/manual references
    and avoids recreating a stale built-in fallback on the next settings migration.
    """
    available = set(catalog_ids(available_models))
    if not available:
        return []                         # an empty/partial discovery is not proof that every model was deleted
    routes = _mutable(settings)
    owned = [route for route in routes if route.get("provider") == provider]
    stale = [route for route in owned if str(route.get("model") or "").strip() not in available]
    if not stale:
        return []
    survivors = [route for route in owned if route not in stale]
    removed = []
    if not survivors:
        keeper = stale.pop(0)
        update_route(settings, keeper["id"], model=_pick_replacement(available, prefer, free))
    for route in stale:
        remove_route(settings, route["id"])
        removed.append(route["id"])
    sync_legacy(settings)
    return removed


def disable_non_free_routes(settings, provider, free):
    """Switch off enabled routes of ``provider`` whose model the catalog now marks as NOT free (``free[model] is False``).

    Unknown (None) is left alone: only an explicit "paid" answer disables a route, and only while
    settings["route_free_only"] is on (default). Returns the ids that were disabled."""
    if not settings.get("route_free_only", True) or not free:
        return []
    disabled = []
    for route in list(_mutable(settings)):
        if route.get("provider") == provider and route.get("enabled", True) and free.get(route.get("model")) is False:
            if disable_route(settings, route["id"], "این مدل دیگر رایگان نیست"):
                disabled.append(route["id"])
    return disabled


def snapshot(settings):
    return deepcopy(get_routes(settings))
