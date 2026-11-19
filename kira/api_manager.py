"""API Manager: one place to register, validate and manage API keys (the logic behind the Route page; no Qt).

The user only types a key. ``detect()`` works out which supported service it belongs to by asking the
service's OFFICIAL, light "list models" endpoint (the same request gives validation AND the model list, so nothing is asked twice).
``register()`` stores it in the existing settings layout, so the Route Engine / Hybrid Brain are untouched:

* an API = one entry of ``settings["providers"]`` (key, enabled flag, base URL ...), exactly as before;
* its models = ``settings["routes"]`` entries of that provider (the list order is still the failover priority);
* what the API reported (status, models, context window, rate limits, time) = ``settings["api_registry"][pid]`` - NO secrets in it.

Nothing here is guessed: a value the provider did not report stays ``None`` and is shown as Unknown / Not Available.
Keys are never put into messages, logs or the registry (``mask_key`` shows only the last four characters).
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from . import discovery
from . import routes as route_model
from .discovery import DiscoveryError

SERVICES = {
    "groq": {"label": "Groq", "base_url": "https://api.groq.com/openai/v1", "default_models": ("openai/gpt-oss-120b",)},
    "openrouter": {"label": "OpenRouter", "base_url": "https://openrouter.ai/api/v1", "default_models": ()},
    "mistral": {"label": "Mistral", "base_url": "https://api.mistral.ai/v1", "default_models": ("mistral-small-latest",)},
    "google": {"label": "Google AI Studio", "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
               "default_models": ("gemini-3.8-flash", "gemini-flash-latest", "gemini-2.5-flash")},
    "cloudflare": {"label": "Cloudflare Workers AI", "base_url": "", "default_models": ("@cf/meta/llama-3.1-8b-instruct",)},
}
BUILTIN_FOR = {"groq": "groq", "mistral": "mistral", "cloudflare": "cloudflare", "openrouter": "openrouter"}      # google has no built-in id: it is a registered provider
KEY_MIN, KEY_MAX = 16, 300
NEVER = 0


# ---------------- keys ----------------
def mask_key(key) -> str:
    """Never the whole key: only the last four characters are shown."""
    key = str(key or "").strip()
    return ("•" * 6 + key[-4:]) if len(key) >= 12 else ("•" * 6 if key else "")


def key_problem(key) -> str:
    """'' when the key looks usable, else a Persian message. No network."""
    key = str(key or "").strip()
    if not key:
        return "API Key را وارد کن."
    if any(ch.isspace() for ch in key) or not key.isascii():
        return "API Key نباید فاصله یا نویسه‌ی غیر انگلیسی داشته باشد (احتمالاً موقع کپی چیزی اضافه شده)."
    if not KEY_MIN <= len(key) <= KEY_MAX:
        return "طول API Key معتبر به نظر نمی‌رسد."
    return ""


def candidate_services(key) -> list[str]:
    """Which services this key may belong to, judged only by its public prefix, so a key is not sent to services it cannot belong to.
    A known prefix means ONE service; a key without a known prefix is checked against the two services whose keys have no prefix."""
    key = str(key or "").strip()
    if key.startswith("gsk_"):
        return ["groq"]
    if key.startswith(("sk-or-v1-", "sk-or-")):
        return ["openrouter"]
    if key.startswith("AIza"):
        return ["google"]
    return ["mistral", "cloudflare"]


# ---------------- detection ----------------
@dataclass
class Detection:
    """state: ok | invalid | ambiguous | unknown | needs_account | error"""
    state: str
    service: str = ""
    message: str = ""
    models: list = field(default_factory=list)
    account_id: str = ""
    rate_limit: dict = field(default_factory=dict)
    accounts: list = field(default_factory=list)          # Cloudflare: [(id, name)] when several accounts are visible

    @property
    def ok(self):
        return self.state == "ok"


_FAIL_STATE = {"auth": "invalid", "config": "invalid"}


def _probe_listing(service, key, timeout):
    """Groq / Mistral / Google: the official model list IS the validation. -> Detection"""
    meta = {}
    cfg = {"api_key": key}
    if service == "google":
        pid, cfg = "google", {"type": "openai_compat", "base_url": SERVICES["google"]["base_url"], "api_key": key}
    else:
        pid = service
    try:
        models = discovery.discover_models(pid, cfg, timeout, meta)
    except DiscoveryError as exc:
        return Detection(_FAIL_STATE.get(exc.kind, "error"), service, discovery.redact(str(exc), key))
    return Detection("ok", service, "", models, rate_limit=meta.get("rate_limit") or {})


def _cf_get(path, key, timeout, params=None):
    return discovery._get(f"{discovery.CLOUDFLARE_API}{path}", {"Authorization": f"Bearer {key}"}, key, timeout, params=params)


def _probe_cloudflare(key, account_id, timeout):
    """Cloudflare: verify the token, find the Account ID when the token may read accounts, then list Workers AI models."""
    account_id = str(account_id or "").strip()
    try:
        data = _cf_get(f"/accounts/{account_id}/tokens/verify" if account_id else "/user/tokens/verify", key, timeout)
        status = ((data or {}).get("result") or {}).get("status") if isinstance(data, dict) else None
        if not (isinstance(data, dict) and data.get("success") and status == "active"):
            return Detection("invalid", "cloudflare", "Cloudflare این توکن را فعال تأیید نکرد.")
    except DiscoveryError as exc:
        msg = discovery.redact(str(exc), key)
        if exc.kind == "auth" and not account_id:
            msg += " اگر توکن از نوع «Account API Token» است، Account ID را هم وارد کن."
        return Detection(_FAIL_STATE.get(exc.kind, "error"), "cloudflare", msg)
    if not account_id:
        try:
            data = _cf_get("/accounts", key, timeout, params={"per_page": 50})
            accounts = [(str(a.get("id")), str(a.get("name") or "")) for a in (data.get("result") or []) if isinstance(a, dict) and a.get("id")]
        except DiscoveryError:
            accounts = []
        if len(accounts) == 1:
            account_id = accounts[0][0]
        else:
            note = ("چند Account دیده شد؛ Account ID مورد نظر را وارد کن." if accounts else
                    "توکن معتبر است ولی اجازه‌ی خواندن Account ID را ندارد؛ Account ID را وارد کن.")
            return Detection("needs_account", "cloudflare", note, accounts=accounts)
    meta = {}
    try:
        models = discovery.discover_models("cloudflare", {"api_key": key, "account_id": account_id}, timeout, meta)
    except DiscoveryError as exc:
        return Detection("error", "cloudflare", "توکن معتبر است ولی فهرست مدل‌ها دریافت نشد: " + discovery.redact(str(exc), key))
    return Detection("ok", "cloudflare", "", models, account_id=account_id, rate_limit=meta.get("rate_limit") or {})


def probe(service, key, account_id="", timeout=12) -> Detection:
    return _probe_cloudflare(key, account_id, timeout) if service == "cloudflare" else _probe_listing(service, key, timeout)


def detect(key, account_id="", hint="", timeout=12) -> Detection:
    """Work out which service owns ``key`` and validate it. hint = the only service to try (re-validating a known API).
    Never registers anything; never puts the key into a message."""
    key = str(key or "").strip()
    problem = key_problem(key)
    if problem:
        return Detection("invalid", "", problem)
    services = [hint] if hint in SERVICES else candidate_services(key)
    results = [probe(s, key, account_id, timeout) for s in services]
    good = [r for r in results if r.ok]
    if len(good) == 1:
        return good[0]
    if len(good) > 1:
        names = " / ".join(SERVICES[r.service]["label"] for r in good)
        return Detection("ambiguous", "", f"این کلید با چند سرویس سازگار است ({names}) و Provider با قطعیت معلوم نشد؛ ثبت نشد.")
    for wanted in ("needs_account", "error"):
        hit = next((r for r in results if r.state == wanted), None)
        if hit:
            return hit
    if len(services) == 1:
        return results[0] if results else Detection("unknown", "", "Provider شناسایی نشد.")
    return Detection("unknown", "", "این کلید برای هیچ‌کدام از سرویس‌های پشتیبانی‌شده (Groq، Mistral، Google AI Studio، Cloudflare، OpenRouter) تأیید نشد؛ "
                                    "کلید را بررسی کن. ثبت نشد.")


def rediscover(pid, cfg, timeout=15) -> Detection:
    """Re-validate a registered API and read its model list again (Refresh / Edit). Known services go through the same detection
    code as Add (restricted to their own service); OpenRouter and hand-added providers use the generic model-list call."""
    cfg = dict(cfg or {})
    service = service_of(pid, cfg)
    key = str(cfg.get("api_key") or "").strip()
    if service in SERVICES:
        return detect(key, cfg.get("account_id", ""), hint=service, timeout=timeout)
    meta = {}
    try:
        models = discovery.discover_models(pid, cfg, timeout, meta)
    except DiscoveryError as exc:
        return Detection(_FAIL_STATE.get(exc.kind, "error"), service, discovery.redact(str(exc), key))
    return Detection("ok", service, "", models, rate_limit=meta.get("rate_limit") or {})


# ---------------- registry (state about each API, stored in settings["api_registry"]; never holds a key) ----------------
def service_of(pid, cfg=None) -> str:
    """groq | mistral | google | cloudflare | openrouter | custom (an OpenAI-compatible provider the user added by hand)."""
    cfg = cfg or {}
    if pid in ("groq", "mistral", "cloudflare", "openrouter"):
        return pid
    if cfg.get("service") in SERVICES:
        return cfg["service"]
    base = str(cfg.get("base_url") or "").lower()
    if "generativelanguage.googleapis.com" in base:
        return "google"
    if "api.groq.com" in base:
        return "groq"
    if "api.mistral.ai" in base:
        return "mistral"
    if route_model.provider_type(pid, cfg) == "cloudflare":
        return "cloudflare"
    return "custom"


def api_ids(settings) -> list[str]:
    """Registered APIs: every cloud/custom provider that holds a key (or was added through the manager), in priority order
    (the order in which their routes appear - the same order the Route Engine tries them)."""
    providers = settings.get("providers", {})
    order = []
    for r in route_model.get_routes(settings):
        if r["provider"] not in order:
            order.append(r["provider"])
    for pid in providers:
        if pid not in order:
            order.append(pid)
    out = []
    for pid in order:
        cfg = providers.get(pid)
        if pid == "ollama" or not isinstance(cfg, dict):
            continue
        if cfg.get("api_key") or cfg.get("service") or pid not in route_model.BUILTIN:
            out.append(pid)
    return out


def registry(settings) -> dict:
    return settings.setdefault("api_registry", {})


def ensure_registry(settings):
    """Idempotent migration: every API that already exists (keys saved by older versions) gets a registry entry, WITHOUT any network
    call and without touching keys, routes or priorities. Old APIs start as 'unchecked' until the user refreshes them."""
    reg = registry(settings)
    providers = settings.get("providers", {})
    for pid in api_ids(settings):
        cfg = providers[pid]
        entry = reg.setdefault(pid, {})
        entry.setdefault("service", service_of(pid, cfg))
        entry.setdefault("status", "unchecked")
        entry.setdefault("checked_at", NEVER)
        entry.setdefault("discovered_at", NEVER)
        entry.setdefault("models", {})
        entry.setdefault("rate_limit", {})
        entry.setdefault("last_error", "")
        for r in route_model.get_routes(settings):
            if r["provider"] == pid and r["model"] and r["model"] not in entry["models"]:
                entry["models"][r["model"]] = {"status": "unknown"}              # known from the old settings, not confirmed yet
    for pid in [p for p in reg if p not in providers]:
        reg.pop(pid)                                                            # provider gone: forget its state
    return reg


def _model_record(m, now, old=None):
    old = old or {}
    return {"status": "available", "name": m.get("name") or "", "info": m.get("info") or "", "free": m.get("free"),
            "context": m.get("context"), "max_output": m.get("max_output"),
            "text": m.get("text"), "vision": m.get("vision"), "tools": m.get("tools"),
            "first_seen": old.get("first_seen") or now, "last_seen": now}


def apply_models(settings, pid, models, rate_limit=None, now=None):
    """Merge a fresh model list into the registry. New models appear as available; models that were known but are no longer listed
    are marked 'unavailable' (never silently dropped). Routes are NOT changed here. Returns {'new': [...], 'gone': [...]}"""
    now = int(now if now is not None else time.time())
    ensure_registry(settings)
    entry = registry(settings)[pid]
    old = entry.get("models", {})
    fresh = {m["id"]: _model_record(m, now, old.get(m["id"])) for m in models if m.get("id")}
    new = [mid for mid in fresh if mid not in old]
    gone = []
    for mid, rec in old.items():
        if mid not in fresh:
            if rec.get("status") != "unavailable":
                gone.append(mid)
            fresh[mid] = {**rec, "status": "unavailable"}
    entry.update({"models": fresh, "status": "valid", "checked_at": now, "discovered_at": now, "last_error": "",
                  "rate_limit": {"as_of": now, "headers": rate_limit} if rate_limit else entry.get("rate_limit", {})})
    return {"new": new, "gone": gone}


def apply_failure(settings, pid, detection, now=None):
    """Remember that the last check failed (the saved key, routes and models stay as they were)."""
    now = int(now if now is not None else time.time())
    ensure_registry(settings)
    entry = registry(settings)[pid]
    entry.update({"status": "invalid" if detection.state == "invalid" else "error", "checked_at": now, "last_error": detection.message[:300]})


def find_duplicate(settings, key) -> str:
    """Id of the registered API that already uses this exact key ('' = none)."""
    key = str(key or "").strip()
    for pid, cfg in settings.get("providers", {}).items():
        if key and pid != "ollama" and str(cfg.get("api_key") or "").strip() == key:
            return pid
    return ""


def pick_default_model(service, models):
    """One sensible starting model, only if the provider really lists it. '' = none (the user enables models in the details)."""
    ids = {m["id"] for m in models}
    for mid in SERVICES[service]["default_models"]:
        if mid in ids:
            return mid
    return ""


def _unique_label(settings, label):
    taken = {route_model.provider_label(p, c).lower() for p, c in settings.get("providers", {}).items()}
    if label.lower() not in taken:
        return label
    n = 2
    while f"{label} ({n})".lower() in taken:
        n += 1
    return f"{label} ({n})"


def register(settings, detection, key, now=None) -> str:
    """Store a validated API. Raises ValueError for anything that is not a clean 'ok' detection or a duplicate key.
    The first key of a service reuses its existing entry (so saved routes / priorities stay attached); another key of the same
    service becomes an additional API. Returns the provider id."""
    if not detection.ok or detection.service not in SERVICES:
        raise ValueError(detection.message or "Provider با قطعیت شناسایی نشد.")
    key = str(key).strip()
    dup = find_duplicate(settings, key)
    if dup:
        raise ValueError(f"این کلید قبلاً به‌عنوان «{route_model.provider_label(dup, settings['providers'][dup])}» ثبت شده است.")
    service = detection.service
    providers = settings.setdefault("providers", {})
    ensure_registry(settings)
    pid = None
    builtin = BUILTIN_FOR.get(service)
    if builtin and not str(providers.get(builtin, {}).get("api_key") or "").strip():
        pid = builtin                                                           # reuse: old routes / priority / timeout stay
    elif service == "google":
        for p, c in providers.items():                                          # a Gemini provider the user created before, still without a key
            if p not in route_model.BUILTIN and service_of(p, c) == "google" and not str(c.get("api_key") or "").strip():
                pid = p
                break
    cfg_new = {"api_key": key, "enabled": True, "service": service}
    if service == "cloudflare":
        cfg_new["account_id"] = detection.account_id
    if pid:
        providers.setdefault(pid, {}).update(cfg_new)
    else:
        label = _unique_label(settings, SERVICES[service]["label"])
        if service == "cloudflare":
            pid = route_model.new_provider_id(settings, label)
            providers[pid] = {"type": "cloudflare", "label": label, "local": False, "timeout": route_model.DEFAULT_CLOUD_TIMEOUT, **cfg_new}
        else:
            pid = route_model.add_provider(settings, label, SERVICES[service]["base_url"], key, False, True)
            providers[pid]["service"] = service
    route_model.ensure_routes(settings)
    apply_models(settings, pid, detection.models, detection.rate_limit, now)
    start = pick_default_model(service, detection.models)
    has_route = any(r["provider"] == pid for r in route_model.get_routes(settings))
    if start and not any(r["provider"] == pid and r["model"] == start for r in route_model.get_routes(settings)):
        route_model.add_route(settings, pid, start, enabled=True)
    elif start and has_route:
        for r in route_model.get_routes(settings):                              # reused built-in: its default route is switched on
            if r["provider"] == pid and r["model"] == start:
                route_model.update_route(settings, r["id"], enabled=True)

    # Google is the explicitly preferred Chat provider: newly registered Gemini
    # routes must not be appended behind Cloudflare/Groq and silently lose to
    # their successful fallback. Keep each Google API's model order intact.
    if service == "google":
        current = route_model.get_routes(settings)
        google_ids = [r["id"] for r in current if r["provider"] == pid]
        if google_ids:
            other_ids = [r["id"] for r in current if r["provider"] != pid]
            route_model.reorder(settings, google_ids + other_ids)
            settings["default_route_id"] = google_ids[0]
    return pid


# ---------------- actions on a registered API ----------------
def set_api_enabled(settings, pid, enabled):
    if pid not in settings.get("providers", {}):
        raise KeyError(pid)
    settings["providers"][pid]["enabled"] = bool(enabled)


def set_model_enabled(settings, pid, model, enabled):
    """Switch one model on/off. Turning on a listed model that has no route yet creates it (at the end of the priority list)."""
    for r in route_model.get_routes(settings):
        if r["provider"] == pid and r["model"] == model:
            route_model.update_route(settings, r["id"], enabled=bool(enabled))
            return r["id"]
    if enabled:
        return route_model.add_route(settings, pid, model, enabled=True)["id"]
    return ""


def delete_api(settings, pid):
    """Remove an API completely. A custom/added provider disappears with its routes. A built-in one (Groq, Mistral, Cloudflare) keeps
    its slot (the Route Engine always has it) but loses key and account, is switched off and its routes are disabled."""
    if pid not in settings.get("providers", {}) or pid == "ollama":
        raise KeyError(pid)
    if pid in route_model.BUILTIN:
        cfg = settings["providers"][pid]
        cfg["api_key"] = ""
        cfg["enabled"] = False
        if "account_id" in cfg:
            cfg["account_id"] = ""
        cfg.pop("service", None)
        for r in route_model.get_routes(settings):
            if r["provider"] == pid:
                route_model.update_route(settings, r["id"], enabled=False)
        if settings.get("manual_route_id") and (route_model.find_route(settings, settings["manual_route_id"]) or {}).get("provider") == pid:
            settings["manual_route_id"] = ""
    else:
        route_model.remove_provider(settings, pid)
    registry(settings).pop(pid, None)


def move_api(settings, pid, delta):
    """Change the priority of a whole API: it swaps places with its neighbour among the REGISTERED APIs. Each API keeps its own model
    order, and providers that are not APIs (local Ollama, unregistered built-ins) stay exactly where they were. Returns the new API order."""
    routes = route_model.get_routes(settings)
    slots = []                                                 # provider order as the Route Engine sees it
    for r in routes:
        if r["provider"] not in slots:
            slots.append(r["provider"])
    apis = [p for p in api_ids(settings) if p in slots]
    if pid not in apis:
        raise KeyError(pid)
    i = apis.index(pid)
    j = max(0, min(len(apis) - 1, i + int(delta)))
    apis.insert(j, apis.pop(i))
    positions = [k for k, p in enumerate(slots) if p in set(apis)]
    for k, p in zip(positions, apis):
        slots[k] = p
    by = {p: [r["id"] for r in routes if r["provider"] == p] for p in slots}
    route_model.reorder(settings, [rid for p in slots for rid in by[p]])
    return apis


def unique_models(settings) -> dict:
    """{model id: [api ids]} - the same model reachable through several keys is ONE model with several routes to it."""
    ensure_registry(settings)
    out = {}
    for pid, entry in registry(settings).items():
        for mid, rec in entry.get("models", {}).items():
            if rec.get("status") != "unavailable":
                out.setdefault(mid, []).append(pid)
    return out


# ---------------- what the UI shows ----------------
def fmt_time(ts):
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts)) if ts else "هرگز"


def _tri(value):
    return "Unknown" if value is None else ("Yes" if value else "No")


def api_row(settings, pid) -> dict:
    ensure_registry(settings)
    cfg = settings["providers"][pid]
    entry = registry(settings)[pid]
    routes = [r for r in route_model.get_routes(settings) if r["provider"] == pid]
    discovered = bool(entry.get("discovered_at"))
    available = sum(1 for m in entry["models"].values() if m.get("status") == "available")
    order = api_ids(settings)
    if not cfg.get("api_key") and route_model.requires_key(pid, cfg):
        status = "no key"
    elif not cfg.get("enabled"):
        status = "disabled"
    else:
        status = {"valid": "valid", "invalid": "invalid", "error": "error"}.get(entry["status"], "not validated yet")
    return {"id": pid, "label": route_model.provider_label(pid, cfg), "service": entry["service"], "status": status,
            "key": mask_key(cfg.get("api_key")), "accessible": available if discovered else None,
            "active": sum(1 for r in routes if r.get("enabled")), "checked_at": entry.get("checked_at") or NEVER,
            "priority": order.index(pid) + 1, "enabled": bool(cfg.get("enabled")), "error": entry.get("last_error", "")}


def api_rows(settings) -> list[dict]:
    ensure_registry(settings)
    return [api_row(settings, pid) for pid in api_ids(settings)]


def api_details(settings, pid) -> dict:
    """Everything the details panel shows. Anything the provider did not report is None (shown as Unknown / Not Available)."""
    ensure_registry(settings)
    row = api_row(settings, pid)
    entry = registry(settings)[pid]
    routes = {r["model"]: r for r in route_model.get_routes(settings) if r["provider"] == pid}
    shared = unique_models(settings)
    models = []
    for mid in sorted(set(entry["models"]) | set(routes), key=str.lower):
        rec = entry["models"].get(mid, {"status": "unknown"})
        others = [route_model.provider_label(p, settings["providers"].get(p)) for p in shared.get(mid, []) if p != pid]
        models.append({"id": mid, "status": rec.get("status", "unknown"), "enabled": bool(routes.get(mid, {}).get("enabled")),
                       "has_route": mid in routes, "context": rec.get("context"), "max_output": rec.get("max_output"),
                       "text": _tri(rec.get("text")), "vision": _tri(rec.get("vision")), "tools": _tri(rec.get("tools")),
                       "free": rec.get("free"), "also_on": others})
    rl = entry.get("rate_limit") or {}
    return {**row, "models": models, "rate_limit": rl.get("headers") or None, "rate_limit_as_of": rl.get("as_of") or NEVER,
            "token_usage": None, "remaining_quota": None}


def describe_failure(detection: Detection) -> str:
    return {"invalid": "✕ ", "ambiguous": "⚠ ", "unknown": "✕ ", "needs_account": "ℹ ", "error": "✕ "}.get(detection.state, "") + detection.message
