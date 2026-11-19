"""Route model: Providers and Routes are separate things.

* A **Provider** is a connection (API key, base URL, account id, local/cloud). Stored in settings["providers"].
* A **Route** is one model reachable through a provider, with its own enabled flag, timeout, cooldown and priority.
  Stored in settings["routes"]; the list order IS the priority / failover order.

Settings written by v1.4.x / v1.5.0 (no "routes" key) are migrated without touching any API key or option:
one route per old provider, in the old provider_order.  Pure logic, no Qt, fully unit-tested.
"""
from __future__ import annotations

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


def update_provider(settings, pid, *, label=None, base_url=None, api_key=None, account_id=None, local=None):
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


def make_route(route_id, provider, model, enabled=True, timeout=None, cooldown=None, kind=None, **extra):
    kind = kind or provider_kind(provider)
    route = {"id": str(route_id), "provider": str(provider), "model": str(model or "").strip(), "enabled": bool(enabled),
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
    """Persistable migration: make settings["routes"] exist, clean, with unique ids. Idempotent."""
    settings.setdefault("providers", {})
    stored = settings.get("routes")
    routes = derive_routes(settings) if not isinstance(stored, list) else stored
    clean, seen = [], set()
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
        clean.append(item)
    for name in BUILTIN:                                         # built-in providers always keep at least one route
        if not any(r["provider"] == name for r in clean):
            cfg = settings["providers"].get(name) or {}
            model = (settings.get("model") if name == "ollama" else cfg.get("model")) or BUILTIN[name]["model"]
            rid = name if name not in seen else f"{name}-2"
            clean.append(make_route(rid, name, model, name == "ollama" and bool(cfg.get("enabled", True)), cfg.get("timeout")))
            seen.add(rid)
    settings["routes"] = clean
    ids = {r["id"] for r in clean}
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
    sync_legacy(settings)
    return route


def update_route(settings, route_id, **changes):
    route = next((r for r in _mutable(settings) if r["id"] == route_id), None)
    if route is None:
        raise KeyError(route_id)
    kind = provider_kind(route["provider"], settings.get("providers", {}).get(route["provider"]))
    if "model" in changes:
        model = str(changes["model"] or "").strip()
        if not model:
            raise ValueError("شناسه‌ی مدل (Model ID) خالی است.")
        route["model"] = model
    if "enabled" in changes:
        route["enabled"] = bool(changes["enabled"])
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


def reconcile_provider_models(settings, provider, available_models):
    """Remove stale routes after a successful, non-empty provider catalog refresh.

    If every route for a built-in provider points at a removed model, retain the
    first route identity and retarget it to a currently advertised model. This
    preserves default/manual references and avoids recreating a stale built-in
    fallback on the next settings migration.
    """
    available = {str(model or "").strip() for model in (available_models or ())}
    available.discard("")
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
        update_route(settings, keeper["id"], model=sorted(available)[0])
    for route in stale:
        remove_route(settings, route["id"])
        removed.append(route["id"])
    sync_legacy(settings)
    return removed


def snapshot(settings):
    return deepcopy(get_routes(settings))
