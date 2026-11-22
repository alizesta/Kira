"""Model Discovery: ask a provider's OFFICIAL API which models the saved key can see.

* One function per provider family, registered in a table -> adding Gemini (or anything else) later is one new function + one line.
* Network only; runs in a worker thread (the UI never waits on it); keys are redacted from every message.
* A model appearing in the list is NOT a guarantee of access or quota - that is only known when it is actually used.
"""
from __future__ import annotations

from urllib.parse import quote

import requests

from . import routes as route_model
from .hybrid_ai import provider_class, redact


class DiscoveryError(RuntimeError):
    """kind: config | auth | unsupported | rate | server | network | timeout | response"""
    def __init__(self, kind, message):
        super().__init__(message)
        self.kind = kind


CLOUDFLARE_API = "https://api.cloudflare.com/client/v4"
PAGE_LIMIT = 10                      # safety bound for paged APIs (100 models per page)


NON_CHAT_HINTS = ("whisper", "embed", "tts", "guard", "moderation", "transcri", "rerank", "orpheus", "playai", "safeguard",
                  "-lora", "nano-banana", "imagen", "veo", "lyria", "ocr")      # speech / embedding / safety / media models


def _is_chat_model(mid):
    low = mid.lower()
    return not any(h in low for h in NON_CHAT_HINTS)


def _short(text, n=140):
    text = " ".join(str(text or "").split())
    return text if len(text) <= n else text[:n - 1] + "…"


def _int(value):
    """A positive whole number the provider really reported, else None (never a guess)."""
    try:
        n = int(float(str(value).replace(",", "")))
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def _rate_headers(resp):
    """Rate-limit headers the provider really sent (x-ratelimit-*, ratelimit-*, retry-after). {} when it sent none."""
    out = {}
    try:
        for k, v in (resp.headers or {}).items():
            low = str(k).lower()
            if low.startswith(("x-ratelimit", "ratelimit")) or low == "retry-after":
                out[low] = str(v)[:80]
    except (AttributeError, TypeError):
        pass
    return out


def _get(url, headers, secret, timeout, params=None, unsupported_on_404=False, meta=None):
    """GET -> decoded JSON, every failure turned into a DiscoveryError with a clear Persian message.
    meta (optional dict) receives {"rate_limit": {...}} from the response headers."""
    try:
        resp = requests.get(url, headers=headers, params=params, timeout=timeout)
    except requests.Timeout as exc:
        raise DiscoveryError("timeout", "مهلت دریافت فهرست مدل‌ها تمام شد (شبکه یا VPN را بررسی کن).") from exc
    except requests.RequestException as exc:
        raise DiscoveryError("network", redact(f"اتصال به سرویس برقرار نشد: {exc}", secret)[:300]) from exc
    code = resp.status_code
    if isinstance(meta, dict):
        meta["rate_limit"] = _rate_headers(resp)
    if code == 400 and ("api key not valid" in str(getattr(resp, "text", "")).lower() or "api_key_invalid" in str(getattr(resp, "text", "")).lower()):
        raise DiscoveryError("auth", "API Key نامعتبر است (400).")           # Google answers a wrong key with 400, not 401
    if code == 403:
        detail_text = str(getattr(resp, "text", "") or "").lower()
        try:
            detail_text += " " + str(resp.json()).lower()
        except (ValueError, AttributeError):
            pass
        if any(marker in detail_text for marker in ("network access denied", "ip address", "not available in your region", "geo restriction")):
            raise DiscoveryError("network", "سرویس درخواست را به‌دلیل محدودیت IP، منطقه یا شبکه رد کرد (403). کلید لزوماً نامعتبر نیست؛ VPN، IP خروجی و دسترسی شبکه را بررسی کن.")
        raise DiscoveryError("auth", "API Key نامعتبر است یا اجازه‌ی دیدن فهرست مدل‌ها را ندارد (403).")
    if code == 401:
        raise DiscoveryError("auth", "API Key نامعتبر است یا اجازه‌ی دیدن فهرست مدل‌ها را ندارد (401).")
    if code == 429:
        raise DiscoveryError("rate", "محدودیت درخواست سرویس (429)؛ کمی بعد دوباره امتحان کن.")
    if code in (404, 405) and unsupported_on_404:
        raise DiscoveryError("unsupported", f"این سرویس فهرست مدل‌ها را از این آدرس ارائه نمی‌دهد ({code}). مدل را دستی وارد کن.")
    if code >= 500:
        raise DiscoveryError("server", f"خطای سرور سرویس ({code}).")
    if code >= 400:
        try:
            detail = resp.json()
        except ValueError:
            detail = resp.text
        raise DiscoveryError("response", redact(f"دریافت فهرست ناموفق بود ({code}): {_short(detail, 200)}", secret))
    try:
        return resp.json()
    except ValueError as exc:
        raise DiscoveryError("response", "پاسخ سرویس قابل خواندن نبود (JSON نیست).") from exc


def _unique_sorted(models):
    seen, out = set(), []
    for m in models:
        if m["id"] and m["id"] not in seen:
            seen.add(m["id"])
            m.setdefault("free", None)                  # True = free, False = paid, None = unknown
            out.append(m)
    return sorted(out, key=lambda m: m["id"].lower())



# ---------------- Google Gemini: native GET /v1beta/models (has display names + supported methods) ----------------
GEMINI_HOST = "generativelanguage.googleapis.com"
_GEMINI_NOT_CHAT = ("embedding", "imagen", "veo", "tts", "image", "live", "aqa", "robotics", "audio", "lyria", "computer-use", "learnlm",
                    "nano-banana", "transcribe")


def _gemini_free(mid):
    """Free-tier classification for known Gemini model families.

    Google explicitly lists Gemini 4 Hydrogen as available on the Free tier;
    Flash / Flash-Lite remain free-tier families. Unknown models stay unknown
    rather than being optimistically mislabeled as free.
    """
    low = str(mid or "").strip().lower()
    if low == "gemini-4-hydrogen":
        return True
    if any(x in low for x in ("pro", "ultra", "argon", "carbon", "neon", "deep-research")):
        return False
    return True if "flash" in low else None


def _gemini(pid, cfg, timeout, meta=None):
    key = str(cfg.get("api_key") or "").strip()
    if not key:
        raise DiscoveryError("config", "ابتدا API Key را ثبت کن.")
    url = f"https://{GEMINI_HOST}/v1beta/models"
    headers = {"x-goog-api-key": key}
    items, token, page = [], None, 0
    while page < PAGE_LIMIT:
        params = {"pageSize": 1000}
        if token:
            params["pageToken"] = token
        data = _get(url, headers, key, timeout, params=params, meta=meta)
        if not isinstance(data, dict) or not isinstance(data.get("models"), list):
            raise DiscoveryError("response", "ساختار فهرست مدل‌های Gemini شناخته‌شده نیست.")
        items.extend(m for m in data["models"] if isinstance(m, dict))
        token = data.get("nextPageToken")
        page += 1
        if not token:
            break
    models = []
    for item in items:
        mid = str(item.get("name") or "").strip()
        mid = mid[7:] if mid.startswith("models/") else mid
        methods = item.get("supportedGenerationMethods")
        if not mid or (isinstance(methods, list) and "generateContent" not in methods):
            continue
        if any(x in mid.lower() for x in _GEMINI_NOT_CHAT) or not mid.lower().startswith("gemini"):
            continue
        models.append({"id": mid, "name": str(item.get("displayName") or "").strip() if str(item.get("displayName") or "") != mid else "",
                       "info": _short(item.get("description") or ""), "free": _gemini_free(mid),
                       "context": _int(item.get("inputTokenLimit")), "max_output": _int(item.get("outputTokenLimit")),
                       "text": True if isinstance(methods, list) and "generateContent" in methods else None, "vision": None, "tools": None})
    return _unique_sorted(models)

# ---------------- OpenAI-compatible: GET {base}/models  (Groq, Mistral, OpenRouter, user-added providers) ----------------
def _openai_compatible(pid, cfg, timeout, meta=None):
    cls = provider_class(pid, cfg)
    base = str(cfg.get("base_url") or getattr(cls, "endpoint", "") or "").rstrip("/")
    if GEMINI_HOST in base:
        return _gemini(pid, cfg, timeout, meta)
    if not base:
        raise DiscoveryError("config", "آدرس (Base URL) این Provider تنظیم نشده است.")
    key = str(cfg.get("api_key") or "").strip()
    if not key and route_model.requires_key(pid, cfg) and pid != "openrouter":       # OpenRouter's model list is public
        raise DiscoveryError("config", "ابتدا API Key را ثبت کن.")
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    data = _get(base + "/models", headers, key, timeout, unsupported_on_404=pid not in route_model.BUILTIN, meta=meta)
    items = data if isinstance(data, list) else (data.get("data") if isinstance(data, dict) else None)
    if items is None and isinstance(data, dict):
        items = data.get("models")
    if not isinstance(items, list):
        raise DiscoveryError("response", "ساختار فهرست مدل‌ها شناخته‌شده نیست.")
    models = []
    for item in items:
        if not isinstance(item, dict):
            continue
        mid = str(item.get("id") or item.get("name") or item.get("model") or "").strip()
        if mid.startswith("models/"):                                                 # Gemini lists "models/gemini-..."; the API accepts the bare id
            mid = mid[7:]
        if not mid or not _is_chat_model(mid) or item.get("active") is False:                                    # Groq marks retired models active=false
            continue
        caps = item.get("capabilities")
        if isinstance(caps, dict) and caps.get("completion_chat") is False:           # Mistral: skip embedding/moderation models
            continue
        name = str(item.get("name") or item.get("display_name") or "").strip()
        ctx = item.get("context_length") or item.get("context_window")
        info = _short(item.get("description") or "") or (f"context {ctx}" if ctx else "")
        entry = {"id": mid, "name": name if name and name != mid else "", "info": info}
        ctx_n = _int(ctx or item.get("max_context_length"))
        top = item.get("top_provider") if isinstance(item.get("top_provider"), dict) else {}
        entry.update({"context": ctx_n, "max_output": _int(item.get("max_completion_tokens") or top.get("max_completion_tokens")),
                      "text": None, "vision": None, "tools": None})
        if isinstance(caps, dict):                                                   # Mistral states these explicitly
            entry["text"] = caps.get("completion_chat") if isinstance(caps.get("completion_chat"), bool) else None
            entry["vision"] = caps.get("vision") if isinstance(caps.get("vision"), bool) else None
            entry["tools"] = caps.get("function_calling") if isinstance(caps.get("function_calling"), bool) else None
        arch = item.get("architecture")
        if isinstance(arch, dict) and isinstance(arch.get("input_modalities"), list):   # OpenRouter states these explicitly
            entry["vision"] = "image" in arch["input_modalities"]
        if isinstance(item.get("supported_parameters"), list):
            entry["tools"] = "tools" in item["supported_parameters"]
        pricing = item.get("pricing")
        if isinstance(pricing, dict) and "prompt" in pricing:                       # OpenRouter publishes per-model prices
            try:
                entry["free"] = float(pricing.get("prompt") or 0) == 0 and float(pricing.get("completion") or 0) == 0
            except (TypeError, ValueError):
                pass
        elif mid.endswith(":free"):
            entry["free"] = True
        models.append(entry)
    return _unique_sorted(models)


# ---------------- Cloudflare Workers AI: GET /accounts/{id}/ai/models/search ----------------
def _cloudflare(pid, cfg, timeout, meta=None):
    account = str(cfg.get("account_id") or "").strip()
    key = str(cfg.get("api_key") or "").strip()
    if not key or not account:
        raise DiscoveryError("config", "API Token و Account ID هر دو لازم‌اند.")
    url = f"{CLOUDFLARE_API}/accounts/{quote(account, safe='')}/ai/models/search"
    headers = {"Authorization": f"Bearer {key}"}
    items, page = [], 1
    while page <= PAGE_LIMIT:
        data = _get(url, headers, key, timeout, params={"per_page": 100, "page": page}, meta=meta)
        if not isinstance(data, dict) or data.get("success") is False:
            errors = data.get("errors") if isinstance(data, dict) else None
            raise DiscoveryError("auth", redact(f"Cloudflare فهرست را رد کرد: {_short(errors, 200)}", key))
        result = data.get("result") or []
        items.extend(r for r in result if isinstance(r, dict))
        total = int((data.get("result_info") or {}).get("total_pages") or 1)
        if page >= total or not result:
            break
        page += 1
    models = []
    for item in items:
        mid = str(item.get("name") or item.get("id") or "").strip()
        task = str((item.get("task") or {}).get("name") or "").lower().replace("-", " ")
        if not mid or not _is_chat_model(mid) or (task and task != "text generation"):                          # chat needs text-generation models
            continue
        props = {}
        for prop in item.get("properties") or []:                      # Cloudflare lists facts as [{"property_id": ..., "value": ...}]
            if isinstance(prop, dict) and prop.get("property_id"):
                props[str(prop["property_id"])] = prop.get("value")
        fc = props.get("function_calling")
        models.append({"id": mid, "name": "", "info": _short(item.get("description") or ""),
                       "context": _int(props.get("context_window") or props.get("max_total_tokens")), "max_output": None,
                       "text": True if task == "text generation" else None, "vision": None,
                       "tools": (str(fc).lower() == "true") if fc is not None else None})
    return _unique_sorted(models)


# ---------------- registry (extend here) ----------------
BY_PROVIDER = {"groq": _openai_compatible, "mistral": _openai_compatible, "openrouter": _openai_compatible, "cloudflare": _cloudflare}
BY_TYPE = {"openai_compat": _openai_compatible, "cloudflare": _cloudflare}


def find_discoverer(pid, cfg):
    return BY_PROVIDER.get(pid) or BY_TYPE.get(route_model.provider_type(pid, cfg))


def supports(pid, cfg):
    return find_discoverer(pid, cfg) is not None


def discover_models(pid, cfg, timeout=15, meta=None):
    """Models the saved credentials can list. Raises DiscoveryError (never leaks the key).
    meta (optional dict) receives {"rate_limit": {...}} when the provider sent rate-limit headers."""
    fn = find_discoverer(pid, cfg or {})
    if fn is None:
        raise DiscoveryError("unsupported", "برای این Provider دریافت خودکار فهرست مدل‌ها پشتیبانی نمی‌شود؛ مدل را دستی وارد کن.")
    return fn(pid, dict(cfg or {}), timeout, meta)
