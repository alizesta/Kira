"""Hybrid AI: provider adapters (cloud + local), Route-based router with failover, cooldowns, streaming and speed metrics.

Routes (kira/routes.py) say WHICH model to try and in what order; providers say HOW to talk to it.
Secrets come from the local settings file and are redacted from every error message and every log line.
"""
from __future__ import annotations

import contextlib
import json
import threading
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
import requests
from typing import Any

from . import routes as route_model
from .leak_guard import LeakGuard, clean_final
from .ollama_client import OllamaClient, OllamaError

COOLDOWN_RATE_LIMIT = 300      # seconds after HTTP 429 (or Retry-After, capped)
COOLDOWN_TRANSIENT = 45        # network / timeout / 5xx (default; each route can override it)
COOLDOWN_CONFIG = 60           # bad key / bad model: stop retrying on every message (reset when settings are saved)
METRICS_KEEP = 200             # in-memory history of request metrics (bounded: no memory growth)


class ProviderError(RuntimeError):
    def __init__(self, provider: str, message: str, retryable: bool = True,
                 status_code: int | None = None, kind: str = "error", retry_after: float | None = None):
        super().__init__(message)
        self.provider = provider
        self.retryable = retryable
        self.status_code = status_code
        self.kind = kind                # auth | model | request | rate | server | network | timeout | response | empty
        self.retry_after = retry_after


def normalize_messages(messages):
    """Provider-neutral cleanup: only user/assistant, no empty text, roles merged when repeated,
    starts and ends with a user message (several APIs reject anything else).
    A message may carry "images": [{"mime", "b64"}]; they are kept (and merged) for vision-capable adapters."""
    out = []
    for item in messages or []:
        role = item.get("role")
        content = str(item.get("content") or "").strip()
        images = [i for i in (item.get("images") or []) if isinstance(i, dict) and i.get("b64")] if role == "user" else []
        if role not in ("user", "assistant") or not (content or images):
            continue
        content = content or "(تصویر ضمیمه)"
        if out and out[-1]["role"] == role:
            out[-1]["content"] += "\n\n" + content
            if images:
                out[-1].setdefault("images", []).extend(images)
        else:
            entry = {"role": role, "content": content}
            if images:
                entry["images"] = list(images)
            out.append(entry)
    while out and out[0]["role"] == "assistant":
        out.pop(0)
    while out and out[-1]["role"] == "assistant":
        out.pop()
    return out


def _openai_message(item):
    """OpenAI-style message; a user message with images becomes a list of text + image_url parts."""
    images = item.get("images")
    if not images:
        return {"role": item["role"], "content": item["content"]}
    parts = [{"type": "text", "text": item["content"]}]
    for img in images:
        parts.append({"type": "image_url", "image_url": {"url": f"data:{img.get('mime') or 'image/png'};base64,{img['b64']}"}})
    return {"role": item["role"], "content": parts}


def redact(text, *secrets):
    text = str(text)
    for secret in secrets:
        secret = str(secret or "")
        if len(secret) >= 6:
            text = text.replace(secret, "***")
    return text


def _api_message(response):
    try:
        data = response.json()
        err = data.get("error") if isinstance(data, dict) else None
        if isinstance(err, dict):
            return str(err.get("message") or err)[:300]
        if err:
            return str(err)[:300]
        if isinstance(data, dict) and data.get("errors"):
            return str(data["errors"])[:300]
    except ValueError:
        pass
    return (response.text or "")[:300].replace("\n", " ").strip()


class ThinkFilter:
    """Removes <think>...</think> blocks from a stream, even when a tag is split between two chunks."""
    OPEN, CLOSE = "<think>", "</think>"

    def __init__(self):
        self.buf = ""
        self.inside = False

    def feed(self, text):
        self.buf += text or ""
        out = []
        while True:
            if self.inside:
                i = self.buf.find(self.CLOSE)
                if i < 0:
                    self.buf = self.buf[-(len(self.CLOSE) - 1):]
                    break
                self.buf = self.buf[i + len(self.CLOSE):]
                self.inside = False
                continue
            i = self.buf.find(self.OPEN)
            if i >= 0:
                out.append(self.buf[:i])
                self.buf = self.buf[i + len(self.OPEN):]
                self.inside = True
                continue
            hold = 0
            for k in range(min(len(self.OPEN) - 1, len(self.buf)), 0, -1):
                if self.OPEN.startswith(self.buf[-k:]):
                    hold = k
                    break
            out.append(self.buf[:len(self.buf) - hold])
            self.buf = self.buf[len(self.buf) - hold:]
            break
        return "".join(out)

    def flush(self):
        rest = "" if self.inside else self.buf
        self.buf, self.inside = "", False
        return rest


def iter_sse(response):
    """Yield the payload of every 'data:' line of a Server-Sent-Events response (comments / other fields skipped)."""
    for raw in response.iter_lines():
        if not raw:
            continue
        line = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)
        if line.startswith(":") or not line.startswith("data:"):
            continue
        yield line[5:].strip()


class ProgressBody:
    """File-like request body that reports how much has been handed to the socket (requests reads it in blocks)."""
    def __init__(self, data: bytes, callback):
        self._data, self._pos, self._cb, self._last = data, 0, callback, -1

    def __len__(self):
        return len(self._data)

    def read(self, size=-1):
        end = len(self._data) if size is None or size < 0 else min(len(self._data), self._pos + size)
        chunk = self._data[self._pos:end]
        self._pos = end
        pct = int(self._pos * 100 / max(1, len(self._data)))
        if pct != self._last:
            self._last = pct
            try:
                self._cb(pct)
            except Exception:                                  # noqa: BLE001 - progress display must never break a request
                pass
        return chunk


class BaseProvider:
    name = "base"
    upload_progress = None                  # optional callback(percent) - set by the router; used when a request carries images
    auth_hint = "کلید API نامعتبر است یا دسترسی ندارد"
    needs_key = True

    def __init__(self, config: dict[str, Any], name: str | None = None):
        self.config = config or {}
        if name:
            self.name = name
        self.model = str(self.config.get("model", "")).strip()
        kind = "local" if self.config.get("local") else "cloud"
        self.timeout = route_model.clamp_timeout(self.config.get("timeout", 18), kind)
        self._resp = None
        self.last_usage = None                  # token / cost numbers the provider REPORTED for the last request (kira/usage.py), else None
        if self.config.get("local"):
            self.needs_key = False

    @property
    def secret(self):
        return str(self.config.get("api_key", "")).strip()

    def enabled(self):
        return bool(self.config.get("enabled", False)) and (bool(self.secret) or not self.needs_key)

    def _fail(self, message, retryable, status=None, kind="error", retry_after=None):
        return ProviderError(self.name, redact(message, self.secret), retryable, status, kind, retry_after)

    def _note_usage(self, obj):
        try:
            from . import usage as _usage
            self.last_usage = _usage.merge_usage(self.last_usage, _usage.parse_usage(obj))
        except Exception:                                              # noqa: BLE001 - usage bookkeeping never breaks a request
            pass

    def abort(self):
        """Close the open stream from another thread (Stop button)."""
        resp, self._resp = self._resp, None
        if resp is not None:
            try:
                resp.close()
            except Exception:
                pass

    def _check_status(self, response):
        """Classify an HTTP error status; returns normally for 2xx."""
        code = response.status_code
        if code == 429:
            try:
                retry_after = float(response.headers.get("Retry-After", ""))
            except (TypeError, ValueError, AttributeError):
                retry_after = None
            raise self._fail("سهمیه یا محدودیت درخواست تمام شده (429).", True, 429, "rate", retry_after)
        if code >= 500:
            raise self._fail(f"خطای سرور سرویس ({code}).", True, code, "server")
        if code in (401, 403):
            raise self._fail(f"{self.auth_hint} ({code}). {_api_message(response)}", False, code, "auth")
        if code >= 400:
            detail = _api_message(response)
            low = detail.lower()
            if code == 404 or "model" in low and ("not found" in low or "does not exist" in low or "not_found" in low
                                                    or "decommissioned" in low or "no longer supported" in low
                                                    or "invalid model" in low or "unknown model" in low):
                raise self._fail(f"شناسه مدل «{self.model}» معتبر نیست یا حساب به آن دسترسی ندارد ({code}). {detail}",
                                 False, code, "model")
            hint = (" — تصویر ضمیمه شده بود؛ شاید این مدل بینایی (Vision) ندارد. یک مدل بینایی مثل Gemini انتخاب کن."
                    if getattr(self, "_sent_images", False) and code in (400, 415, 422) else "")
            raise self._fail(f"درخواست نامعتبر ({code}): {detail}{hint}", False, code, "request")

    def _send_args(self, headers, payload):
        """requests keyword args: plain json normally, a progress-reporting body when the upload is big (images / large files)."""
        if self.upload_progress:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            if getattr(self, "_sent_images", False) or len(body) > 20000:
                return {"data": ProgressBody(body, self.upload_progress), "headers": {**headers, "Content-Type": "application/json"}}
        return {"json": payload, "headers": headers}

    def _post_json(self, url, headers, payload):
        """POST and return the decoded JSON body. Every failure becomes a classified ProviderError."""
        try:
            response = requests.post(url, timeout=self.timeout, **self._send_args(headers, payload))
        except requests.Timeout as exc:
            raise self._fail("مهلت پاسخ‌گویی سرویس تمام شد.", True, kind="timeout") from exc
        except requests.RequestException as exc:
            raise self._fail(f"خطای شبکه: {exc}", True, kind="network") from exc
        self._check_status(response)
        try:
            data = response.json()
        except ValueError as exc:
            raise self._fail("پاسخ سرویس قابل خواندن نبود.", True, kind="response") from exc
        self._note_usage(data)
        return data

    def _open_stream(self, url, headers, payload):
        """POST with stream=True; the status is checked before the first byte of the body is read."""
        try:
            response = requests.post(url, timeout=(min(10, self.timeout), self.timeout), stream=True, **self._send_args(headers, payload))
        except requests.Timeout as exc:
            raise self._fail("مهلت اتصال به سرویس تمام شد.", True, kind="timeout") from exc
        except requests.RequestException as exc:
            raise self._fail(f"خطای شبکه: {exc}", True, kind="network") from exc
        try:
            self._check_status(response)
        except ProviderError:
            try:
                response.close()
            except Exception:
                pass
            raise
        self._resp = response
        return response

    def _stream_sse(self, url, headers, payload, extract, on_connect=None):
        response = self._open_stream(url, headers, payload)
        if on_connect:
            on_connect()
        flt = ThinkFilter()
        try:
            for data in iter_sse(response):
                if data == "[DONE]":
                    break
                try:
                    obj = json.loads(data)
                except ValueError:
                    continue
                self._note_usage(obj)
                if isinstance(obj, dict) and obj.get("error"):
                    err = obj["error"]
                    msg = err.get("message") if isinstance(err, dict) else err
                    raise self._fail(f"خطای سرویس وسط پاسخ: {str(msg)[:300]}", True, kind="server")
                piece = flt.feed(extract(obj) or "")
                if piece:
                    yield piece
            tail = flt.flush()
            if tail:
                yield tail
        except requests.Timeout as exc:
            raise self._fail("سرویس وسط پاسخ ساکت شد (Timeout).", True, kind="timeout") from exc
        except requests.RequestException as exc:
            raise self._fail(f"ارتباط وسط پاسخ قطع شد: {exc}", True, kind="network") from exc
        finally:
            self._resp = None
            try:
                response.close()
            except Exception:
                pass

    def chat(self, messages, system_prompt, temperature=0.7):
        raise NotImplementedError

    def stream(self, messages, system_prompt, temperature=0.7, on_connect=None, max_tokens=None):
        raise NotImplementedError


class OpenAICompatibleProvider(BaseProvider):
    endpoint = ""

    def _base(self):
        return str(self.config.get("base_url") or self.endpoint).rstrip("/")

    def _prepare(self, messages, system_prompt, temperature, stream, max_tokens=None):
        if (self.needs_key and not self.secret) or not self.model:
            raise self._fail("API Key یا مدل تنظیم نشده است.", False, kind="auth")
        if not self._base():
            raise self._fail("آدرس (Base URL) تنظیم نشده است.", False, kind="request")
        clean = normalize_messages(messages)
        if not clean:
            raise self._fail("هیچ پیام کاربری برای ارسال وجود ندارد.", False, kind="request")
        url = self._base() + "/chat/completions"
        headers = {"Content-Type": "application/json"}
        if self.secret:
            headers["Authorization"] = f"Bearer {self.secret}"
        payload = {"model": self.model,
                   "messages": [{"role": "system", "content": system_prompt}, *[_openai_message(m) for m in clean]],
                   "temperature": float(temperature), "stream": bool(stream)}
        self._sent_images = any(m.get("images") for m in clean)
        if max_tokens:
            payload["max_tokens"] = int(max_tokens)
        if stream and self.name in ("groq", "openrouter") and self.config.get("usage_stream_options", True):
            payload["stream_options"] = {"include_usage": True}        # the last chunk then carries the token counts (kira/usage.py)
        if self.name == "openrouter":
            headers["HTTP-Referer"] = "https://project-kira.local"
            headers["X-Title"] = "Project Kira"
        return url, headers, payload

    def chat(self, messages, system_prompt, temperature=0.7):
        url, headers, payload = self._prepare(messages, system_prompt, temperature, False)
        data = self._post_json(url, headers, payload)
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise self._fail("ساختار پاسخ سرویس شناخته‌شده نیست.", True, kind="response") from exc
        if isinstance(content, list):
            content = "\n".join(str(x.get("text", "")) for x in content if isinstance(x, dict))
        content = str(content or "").strip()
        if not content:
            raise self._fail("مدل پاسخ خالی برگرداند.", True, kind="response")
        return content

    @staticmethod
    def _extract(obj):
        try:
            choice = obj["choices"][0]
        except (KeyError, IndexError, TypeError):
            return ""
        delta = choice.get("delta") or choice.get("message") or {}
        content = delta.get("content")
        if isinstance(content, list):
            content = "".join(str(x.get("text", "")) for x in content if isinstance(x, dict))
        return content if isinstance(content, str) else ""

    def stream(self, messages, system_prompt, temperature=0.7, on_connect=None, max_tokens=None):
        url, headers, payload = self._prepare(messages, system_prompt, temperature, True, max_tokens)
        return self._stream_sse(url, headers, payload, self._extract, on_connect)


class GroqProvider(OpenAICompatibleProvider):
    name = "groq"
    endpoint = "https://api.groq.com/openai/v1"


class MistralProvider(OpenAICompatibleProvider):
    name = "mistral"
    endpoint = "https://api.mistral.ai/v1"


class OpenRouterProvider(OpenAICompatibleProvider):
    name = "openrouter"
    endpoint = "https://openrouter.ai/api/v1"


class CustomOpenAIProvider(OpenAICompatibleProvider):
    """User-added provider that speaks the OpenAI chat-completions protocol (LM Studio, vLLM, Together, DeepInfra...)."""
    name = "custom"


class CloudflareProvider(BaseProvider):
    name = "cloudflare"
    auth_hint = "توکن یا Account ID Cloudflare معتبر نیست یا دسترسی ندارد"

    def _prepare(self, messages, system_prompt, temperature, stream, max_tokens=None):
        account_id = str(self.config.get("account_id", "")).strip()
        if not account_id or not self.secret or not self.model:
            raise self._fail("Account ID، API Token و مدل باید تنظیم شوند.", False, kind="auth")
        clean = normalize_messages(messages)
        if not clean:
            raise self._fail("هیچ پیام کاربری برای ارسال وجود ندارد.", False, kind="request")
        url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/{self.model}"
        headers = {"Authorization": f"Bearer {self.secret}", "Content-Type": "application/json"}
        payload = {"messages": [{"role": "system", "content": system_prompt}, *[{"role": m["role"], "content": m["content"]} for m in clean]],
                   "temperature": float(temperature), "stream": bool(stream)}      # Cloudflare text models: images are not sent
        if max_tokens:
            payload["max_tokens"] = int(max_tokens)
        return url, headers, payload

    def chat(self, messages, system_prompt, temperature=0.7):
        url, headers, payload = self._prepare(messages, system_prompt, temperature, False)
        data = self._post_json(url, headers, payload)
        try:
            result = data.get("result") or {}
            content = result.get("response") or result.get("output_text")
            if not content and isinstance(result.get("choices"), list):
                content = result["choices"][0].get("message", {}).get("content")
        except (AttributeError, IndexError, TypeError) as exc:
            raise self._fail("ساختار پاسخ Cloudflare شناخته‌شده نیست.", True, kind="response") from exc
        if not content:
            raise self._fail("Cloudflare پاسخ خالی برگرداند.", True, kind="response")
        return str(content).strip()

    @staticmethod
    def _extract(obj):
        if not isinstance(obj, dict):
            return ""
        if isinstance(obj.get("response"), str):
            return obj["response"]
        return OpenAICompatibleProvider._extract(obj)

    def stream(self, messages, system_prompt, temperature=0.7, on_connect=None, max_tokens=None):
        url, headers, payload = self._prepare(messages, system_prompt, temperature, True, max_tokens)
        return self._stream_sse(url, headers, payload, self._extract, on_connect)


PROVIDER_CLASSES = {
    "groq": GroqProvider,
    "cloudflare": CloudflareProvider,
    "mistral": MistralProvider,
    "openrouter": OpenRouterProvider,
}


def provider_class(name, cfg=None):
    """Adapter class for a provider id (built-in or user-added). None when unknown / local Ollama."""
    if name in PROVIDER_CLASSES:
        return PROVIDER_CLASSES[name]
    if name == "ollama":
        return None
    if cfg is not None and route_model.provider_type(name, cfg) == "openai_compat":
        return CustomOpenAIProvider
    if cfg is not None and route_model.provider_type(name, cfg) == "cloudflare":          # a second Cloudflare account added through the API Manager
        return CloudflareProvider
    return None


def _bare_model_id(value):
    """'models/gemini-2.5-flash' -> 'gemini-2.5-flash' (Google prefixes ids with 'models/')."""
    value = str(value or "").strip()
    return value[7:] if value.startswith("models/") else value


def probe_provider(name, config, provider_cls=None):
    """Real connection test used by the Route panel. Returns (ok, message).

    Order: list models with the key (separates a bad key from a bad model) -> one tiny real chat request that
    includes a user message. Works for built-in and user-added OpenAI-compatible providers."""
    config = dict(config or {})
    cls = provider_cls or provider_class(name, config)
    if not cls:
        return False, "سرویس ناشناخته است."
    provider = cls(config, name=name)
    try:
        if cls is not CloudflareProvider and cls is not OpenRouterProvider:
            base = provider._base()
            headers = {"Authorization": "Bearer " + provider.secret} if provider.secret else {}
            try:
                response = requests.get(base + "/models", headers=headers, timeout=15)
            except requests.Timeout:
                return False, "مهلت بررسی کلید تمام شد (شبکه یا VPN را بررسی کن)."
            except requests.RequestException as exc:
                return False, redact(f"خطای شبکه هنگام بررسی کلید: {exc}", provider.secret)[:400]
            if response.status_code in (401, 403):
                return False, redact(f"کلید یا دسترسی رد شد ({response.status_code}): {_api_message(response)}", provider.secret)
            if response.status_code == 200:
                try:
                    payload = response.json()
                    items = payload.get("data") if isinstance(payload, dict) and "data" in payload else payload.get("models", [])
                    # Gemini (OpenAI-compat) lists ids as "models/gemini-2.5-flash"; compare without that prefix.
                    models = {_bare_model_id(item.get("id") or item.get("name")) for item in items if isinstance(item, dict)}
                    models.discard("")
                except (ValueError, AttributeError, TypeError):
                    models = set()
                if models and _bare_model_id(provider.model) not in models:
                    return False, f"کلید معتبر است، اما مدل «{provider.model}» در فهرست مدل‌های قابل دسترس این حساب نیست."
            elif response.status_code != 404:
                return False, redact(f"خطای بررسی کلید ({response.status_code}): {_api_message(response)}", provider.secret)
        last = None
        for attempt in range(3):                                   # 503 / 429 are usually momentary overload: retry briefly
            try:
                provider.chat([{"role": "user", "content": "Reply with only: OK"}], "You are a connection test.", 0.1)
                return True, "اتصال و دریافت پاسخ موفق بود."
            except ProviderError as exc:
                last = exc
                if exc.kind not in ("server", "rate") and exc.status_code not in (429, 500, 502, 503, 504):
                    raise
                if attempt < 2:
                    time.sleep(2 * (attempt + 1))
        hint = (" — این خطا از سمت سرویس است (شلوغی یا محدودیت موقت)، نه کلید یا مدل. چند دقیقه بعد دوباره تست کن "
                "یا مدل دیگری (مثلاً Flash-Lite) را امتحان کن.")
        return False, (str(last)[:400] + hint)
    except ProviderError as exc:
        return False, str(exc)[:500]
    except Exception as exc:
        return False, redact(str(exc), provider.secret)[:500]


def classify(exc):
    """(kind, status_code, retryable, retry_after) for any exception raised by a provider."""
    if isinstance(exc, ProviderError):
        return exc.kind, exc.status_code, exc.retryable, exc.retry_after
    if isinstance(exc, OllamaError):
        return exc.kind, None, exc.kind not in ("missing", "request"), None
    return "unexpected", None, True, None


class HybridRouter:
    """Ordered Route router: manual choice > priority order; per-route timeout and cooldown; failover; streaming; metrics."""

    def __init__(self, settings: dict):
        self.settings = settings
        self.cooldowns: dict[str, float] = {}
        self.states: dict[str, dict] = {}              # route id -> health / last error / last response time (runtime only)
        self.metrics = deque(maxlen=METRICS_KEEP)       # per-request speed records (metadata only)
        self.benchmarks = deque(maxlen=50)
        self.last_provider = None
        self.last_model = None
        self.last_route_id = None
        self.last_kind = None
        self.last_error = None
        self.last_duration_ms = None
        self.last_attempts = []
        self.last_metrics = None
        self._lock = threading.Lock()
        self._cancel = threading.Event()
        self._active = None
        self._role = ""                                # brain role of the request in progress (surface | deep | reflection | memory); "" = unspecified
        self._prefer = ""                              # route id the role asked for first ("" = the normal order)

    # ---------- logging ----------
    @staticmethod
    def _write_telemetry(record, filename="provider_telemetry.jsonl"):
        """Append metadata-only diagnostics. Never store prompts, replies, or credentials."""
        try:
            import os
            log_dir = Path(os.environ.get("KIRA_LOG_DIR") or (Path(__file__).resolve().parent.parent / "logs"))
            log_dir.mkdir(parents=True, exist_ok=True)
            path = log_dir / filename
            safe = {"timestamp": datetime.now(timezone.utc).isoformat(), **record}
            with path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(safe, ensure_ascii=False) + "\n")
        except OSError:
            # Diagnostics must never break a chat request.
            pass

    # ---------- route inspection ----------
    def routes(self):
        return route_model.get_routes(self.settings)

    def _provider_cfg(self, route):
        return (self.settings.get("providers") or {}).get(route["provider"]) or {}

    def route_info(self, route):
        cfg = self._provider_cfg(route)
        return {"route_id": route["id"], "provider": route["provider"], "label": route_model.provider_label(route["provider"], cfg),
                "model": route["model"], "kind": route_model.provider_kind(route["provider"], cfg)}

    def eligibility(self, route):
        """(ok, reason). reason: ok | disabled | no_provider | provider_off | no_key | no_model | cooldown."""
        provider = route["provider"]
        cfg = self._provider_cfg(route)
        if provider != "ollama" and not cfg and provider not in route_model.BUILTIN:
            return False, "no_provider"
        if not route.get("enabled", True):
            return False, "disabled"
        if provider == "ollama":
            if not bool(cfg.get("enabled", True)):
                return False, "provider_off"
        else:
            if not cfg.get("enabled"):
                return False, "provider_off"
            if route_model.requires_key(provider, cfg) and not cfg.get("api_key"):
                return False, "no_key"
        if not route.get("model") and provider != "ollama":
            return False, "no_model"
        if self.cooldowns.get(route["id"], 0) - time.monotonic() > 0:
            return False, "cooldown"
        return True, "ok"

    @contextlib.contextmanager
    def role_scope(self, role="", route_id=""):
        """Requests made inside this block belong to a brain role: the role is written to the metrics, and `route_id` (when it names an
        existing route) is tried FIRST. If that route is unusable the normal order follows, so a role never stops the conversation."""
        previous = (self._role, self._prefer)
        self._role, self._prefer = str(role or ""), str(route_id or "")
        try:
            yield self
        finally:
            self._role, self._prefer = previous

    def _candidates(self):
        """Routes in the order they will be tried: a role's own route (if any), then the manual choice, then priority order (unless failover is off)."""
        routes = self.routes()
        manual = self.settings.get("manual_route_id") or ""
        chosen = next((r for r in routes if r["id"] == manual), None) if manual else None
        if chosen is None:
            base = routes
        elif not self.settings.get("failover_enabled", True):
            base = [chosen]
        else:
            base = [chosen] + [r for r in routes if r["id"] != chosen["id"]]
        prefer = self._prefer
        try:
            from . import usage as _usage
            if prefer and not _usage.role_allowed(self._role):
                prefer = ""                                            # an expensive role over its blocking limit goes back to the normal path
            base = _usage.apply_limits(base, lambda r: self.eligibility(r)[0])
        except Exception:                                              # noqa: BLE001
            pass
        preferred = next((r for r in routes if r["id"] == prefer and r in base), None) if prefer else None
        if preferred is None:
            return base
        return [preferred] + [r for r in base if r["id"] != preferred["id"]]

    def preview_route(self):
        """The route the next request would try first (for the indicator before sending). None if nothing is usable."""
        for route in self._candidates():
            ok, _ = self.eligibility(route)
            if ok:
                return self.route_info(route)
        return None

    def available_routes(self):
        """Routes a person may pick by hand: enabled and fully configured (cooldown does not hide them)."""
        out = []
        for route in self.routes():
            ok, reason = self.eligibility(route)
            if ok or reason == "cooldown":
                out.append(self.route_info(route))
        return out

    def reset_cooldowns(self, route_id=None):
        if route_id:
            self.cooldowns.pop(route_id, None)
        else:
            self.cooldowns.clear()

    # ---------- provider construction ----------
    def _make_provider(self, route):
        cfg = self._provider_cfg(route)
        if route["provider"] == "ollama":
            client = OllamaClient.from_settings(self.settings)
            client.model = route["model"] or client.model
            client._resolved = None
            try:
                client.timeout = max(10, int(route.get("timeout") or client.timeout))
                if route.get("num_ctx"):
                    from .ollama_client import clamp_num_ctx
                    client.num_ctx = clamp_num_ctx(route["num_ctx"])
                if route.get("num_predict"):
                    from .ollama_client import clamp_num_predict
                    client.num_predict = clamp_num_predict(route["num_predict"])
            except (TypeError, ValueError):
                pass
            return client
        cls = provider_class(route["provider"], cfg)
        if cls is None:
            raise ProviderError(route["provider"], "نوع Provider پشتیبانی نمی‌شود.", False, kind="request")
        merged = {**cfg, "model": route["model"], "timeout": route.get("timeout") or cfg.get("timeout", 18)}
        return cls(merged, name=route["provider"])

    # ---------- health / cooldown bookkeeping ----------
    def _state(self, rid):
        return self.states.setdefault(rid, {"health": "unknown", "last_error": None, "last_ms": None, "last_ok_at": None,
                                            "last_attempt_at": None, "failures": 0, "last_kind": None})

    def _mark_success(self, route, ms):
        st = self._state(route["id"])
        st.update(health="healthy", last_error=None, last_ms=ms, last_ok_at=time.time(), last_attempt_at=time.time(),
                  failures=0, last_kind=None)
        self.cooldowns.pop(route["id"], None)

    def _mark_failure(self, route, exc, secrets=()):
        kind, status, retryable, retry_after = classify(exc)
        base = int(route.get("cooldown", COOLDOWN_TRANSIENT) or 0)
        if kind == "rate" or status == 429:
            cooldown = min(max(retry_after or COOLDOWN_RATE_LIMIT, 30, base), 600)
        elif kind in ("auth", "model", "request", "missing"):
            cooldown = max(COOLDOWN_CONFIG, base)
        elif kind == "offline":
            cooldown = 0                          # connection refused answers instantly: nothing to wait for, retry freely
        else:
            cooldown = base
        if cooldown > 0:
            self.cooldowns[route["id"]] = time.monotonic() + cooldown
        st = self._state(route["id"])
        st["failures"] += 1
        st["last_kind"] = kind
        st["last_attempt_at"] = time.time()
        st["last_error"] = redact(str(exc), *secrets)[:300]
        st["health"] = "down" if kind in ("auth", "model", "request", "missing", "offline") else "degraded"
        return kind, status, cooldown

    # ---------- cancellation ----------
    def cancel(self):
        """Stop the running request as soon as possible (Stop button). Safe to call from any thread."""
        self._cancel.set()
        active = self._active
        if active is not None:
            try:
                active.abort()
            except Exception:
                pass

    @property
    def busy(self):
        return self._lock.locked()

    # ---------- the request loop ----------
    def _execute(self, messages, system_prompt, temperature, stream, on_chunk=None, on_event=None, retry_index=0):
        if not self._lock.acquire(blocking=False):
            raise RuntimeError("درخواست قبلی هنوز در حال انجام است؛ درخواست تکراری ارسال نشد.")
        self._cancel.clear()
        try:
            started = time.monotonic()
            messages = normalize_messages(messages)
            self.last_attempts = []
            if not messages:
                raise RuntimeError("هیچ پیام کاربری برای ارسال وجود ندارد.")
            metrics = {"request_id": uuid.uuid4().hex[:8], "started_at": datetime.now(timezone.utc).isoformat(),
                       "stream": bool(stream), "retries": int(retry_index), "failovers": 0, "provider": None, "model": None,
                       "route_id": None, "kind": None, "connect_ms": None, "first_token_ms": None, "total_ms": None,
                       "result": None, "chars": 0, "role": self._role or None}
            failures = []
            emit = on_event or (lambda e: None)
            for route in self._candidates():
                if self._cancel.is_set():
                    break
                ok, reason = self.eligibility(route)
                rid = route["id"]
                if reason == "cooldown":
                    remaining = int(self.cooldowns.get(rid, 0) - time.monotonic())
                    failures.append(f"{rid}: در حالت استراحت ({remaining} ثانیه دیگر)")
                    self.last_attempts.append({"provider": route["provider"], "route_id": rid, "result": "cooldown"})
                    continue
                if not ok:
                    continue
                info = self.route_info(route)
                secrets = (self._provider_cfg(route).get("api_key"),)
                emit({"phase": "connecting" if not failures and metrics["failovers"] == 0 else "failover",
                      "failovers": metrics["failovers"], **info})
                attempt_started = time.monotonic()
                parts, first_at, connect_at = [], None, None
                provider = None
                try:
                    provider = self._make_provider(route)
                    provider.upload_progress = lambda pct, _i=info: emit({"phase": "uploading", "percent": pct, **_i})
                    guard = LeakGuard()                                   # internal analysis never becomes part of the answer
                    if not stream:
                        answer = clean_final(provider.chat(messages, system_prompt, temperature))
                        parts = [answer] if answer else []
                        connect_at = first_at = time.monotonic()
                    else:
                        self._active = provider

                        def on_connect():
                            nonlocal connect_at
                            connect_at = time.monotonic()
                            emit({"phase": "waiting", "failovers": metrics["failovers"], **info})
                        gen = provider.stream(messages, system_prompt, temperature, on_connect=on_connect)
                        try:
                            for chunk in gen:
                                if not chunk:
                                    continue
                                if first_at is None:
                                    first_at = time.monotonic()
                                    emit({"phase": "streaming", "failovers": metrics["failovers"], **info})
                                chunk = guard.feed(chunk)
                                if chunk:
                                    parts.append(chunk)
                                    if on_chunk:
                                        on_chunk(chunk)
                                if self._cancel.is_set():
                                    break
                            if not self._cancel.is_set():
                                tail = guard.finish()
                                if tail:
                                    parts.append(tail)
                                    if on_chunk:
                                        on_chunk(tail)
                        finally:
                            gen.close()                                   # closes the HTTP stream even after Stop
                        if not parts and not self._cancel.is_set():
                            raise ProviderError(route["provider"], ("مدل فقط متن تحلیل داخلی برگرداند و چیزی برای نمایش نبود؛ Route بعدی امتحان می‌شود."
                                                                    if guard.leaked else "مدل پاسخ خالی برگرداند."), True, kind="empty")
                except Exception as exc:                                  # noqa: BLE001 - every provider failure is contained here
                    if self._cancel.is_set():                             # user pressed Stop: not a failure of the route
                        return self._finish(route, info, parts, metrics, started, attempt_started, connect_at, first_at, provider,
                                            stopped=True, failures=failures)
                    safe = RuntimeError(redact(exc, *secrets)) if not isinstance(exc, (ProviderError, OllamaError)) else exc
                    kind, status, cooldown = self._mark_failure(route, exc, secrets)
                    note = f"{rid}: {redact(exc, *secrets)}" if kind != "unexpected" else \
                        f"{rid}: خطای پیش‌بینی‌نشده ({redact(exc, *secrets)})"
                    failures.append(note)
                    self.last_error = redact(str(exc), *secrets)
                    self.last_attempts.append({"provider": route["provider"], "route_id": rid, "model": route["model"], "result": "error",
                                               "error_kind": kind, "status_code": status,
                                               "duration_ms": int((time.monotonic() - attempt_started) * 1000)})
                    if parts:                                             # connection died mid-answer: keep what arrived, never repeat it
                        return self._finish(route, info, parts, metrics, started, attempt_started, connect_at, first_at, provider,
                                            interrupted=str(safe), failures=failures)
                    metrics["failovers"] += 1
                    continue
                return self._finish(route, info, parts, metrics, started, attempt_started, connect_at, first_at, provider,
                                    stopped=self._cancel.is_set(), failures=failures)
            # nothing worked
            self.last_provider = self.last_model = self.last_route_id = self.last_kind = None
            self.last_error = "; ".join(failures) or "هیچ Route فعالی تنظیم نشده است."
            self.last_duration_ms = int((time.monotonic() - started) * 1000)
            if self._cancel.is_set():
                metrics.update(result="stopped", total_ms=self.last_duration_ms)
                self.metrics.append(metrics)
                self.last_metrics = metrics
                return {"text": "", "stopped": True, "interrupted": None, "metrics": metrics, **{"provider": None, "model": None, "route_id": None,
                        "kind": None, "label": None}}
            metrics.update(result="failed", total_ms=self.last_duration_ms)
            self.metrics.append(metrics)
            self.last_metrics = metrics
            self._ledger(metrics, "failed")
            self._write_telemetry({"provider": None, "result": "failed", "duration_ms": self.last_duration_ms,
                                   "attempts": self.last_attempts, "request_id": metrics["request_id"], "stream": bool(stream),
                                   "failovers": metrics["failovers"], "retries": metrics["retries"]})
            raise RuntimeError("تمام Routeهای فعال ناموفق بودند یا غیرفعال‌اند:\n" + ("\n".join(failures) or self.last_error))
        finally:
            self._active = None
            self._lock.release()

    def _ledger(self, metrics, status, provider=None, stats=None, kind=None):
        """One usage-ledger row per request (success, stopped, interrupted or failed). Only numbers the provider reported are stored."""
        try:
            from . import usage as _usage
            nums, source = dict(getattr(provider, "last_usage", None) or {}), "provider"
            if not nums and isinstance(stats, dict) and (stats.get("prompt_tokens") or stats.get("eval_tokens")):
                nums, source = {"tokens_in": stats.get("prompt_tokens"), "tokens_out": stats.get("eval_tokens")}, "ollama"
            causes = [a.get("error_kind") or a.get("result") for a in self.last_attempts if a.get("result") in ("error", "cooldown")]
            _usage.record({**nums, "request_id": metrics.get("request_id"), "role": metrics.get("role"), "provider": metrics.get("provider"),
                           "model": metrics.get("model"), "route_id": metrics.get("route_id"), "status": status, "failovers": metrics.get("failovers"),
                           "failover_causes": causes, "connect_ms": metrics.get("connect_ms"), "first_token_ms": metrics.get("first_token_ms"),
                           "total_ms": metrics.get("total_ms"), "tokens_source": source, "kind": kind or metrics.get("kind"),
                           "error_kind": causes[-1] if causes and status == "failed" else None})
        except Exception:                                              # noqa: BLE001
            pass

    def _finish(self, route, info, parts, metrics, started, attempt_started, connect_at, first_at, provider,
                stopped=False, interrupted=None, failures=()):
        now = time.monotonic()
        text = "".join(parts)
        ms = lambda t: int((t - started) * 1000) if t else None                       # noqa: E731
        stats = getattr(provider, "last_stats", None) if provider is not None else None
        stats = stats if isinstance(stats, dict) else None
        model = info["model"]
        active = getattr(provider, "active_model", None)
        if isinstance(active, str) and active:
            model = active
        if parts and not interrupted:
            self._mark_success(route, int((now - attempt_started) * 1000))
        self.last_provider, self.last_model = route["provider"], model
        self.last_route_id, self.last_kind = route["id"], info["kind"]
        self.last_error = "; ".join(failures) or None
        self.last_duration_ms = int((now - started) * 1000)
        self.last_attempts.append({"provider": route["provider"], "route_id": route["id"], "model": model,
                                   "result": "stopped" if stopped else ("interrupted" if interrupted else "success"),
                                   "duration_ms": int((now - attempt_started) * 1000)})
        metrics.update(provider=route["provider"], model=model, route_id=route["id"], kind=info["kind"],
                       connect_ms=ms(connect_at), first_token_ms=ms(first_at), total_ms=self.last_duration_ms,
                       result="stopped" if stopped else ("interrupted" if interrupted else "success"), chars=len(text))
        if stats:
            metrics.update(load_ms=stats.get("load_ms"), eval_tokens=stats.get("eval_tokens"), eval_ms=stats.get("eval_ms"))
        self.metrics.append(metrics)
        self.last_metrics = metrics
        self._ledger(metrics, metrics["result"], provider, stats)
        self._write_telemetry({"provider": route["provider"], "model": model, "result": metrics["result"],
                               "duration_ms": self.last_duration_ms, "attempts": self.last_attempts,
                               **{k: metrics.get(k) for k in ("request_id", "route_id", "kind", "stream", "connect_ms",
                                                              "first_token_ms", "total_ms", "retries", "failovers", "role")}})
        return {"text": text, "stopped": stopped, "interrupted": interrupted, "metrics": metrics,
                "provider": route["provider"], "model": model, "route_id": route["id"], "kind": info["kind"], "label": info["label"]}

    # ---------- public API ----------
    def chat(self, messages, system_prompt, temperature=0.7):
        """Whole answer at once (kept for tests, tools and as the non-streaming fallback)."""
        return self._execute(messages, system_prompt, temperature, False)["text"]

    def chat_stream(self, messages, system_prompt, temperature=0.7, on_chunk=None, on_event=None, retry_index=0):
        """Streamed answer. on_chunk(text) gets each piece; on_event(dict) gets phase changes
        (connecting / waiting / streaming / failover) with the REAL route taken from the router.

        Failover happens only before the first token. Once text has arrived it is never repeated: a connection that dies
        later ends the answer as 'interrupted' (result["interrupted"] holds the reason). Returns the result dict."""
        return self._execute(messages, system_prompt, temperature, True, on_chunk, on_event, retry_index)

    # ---------- tests / benchmark (explicit, one route at a time, never parallel) ----------
    def test_route(self, route_id):
        """Real connection test of ONE route. Returns (ok, message, ms) and updates its health."""
        route = next((r for r in self.routes() if r["id"] == route_id), None)
        if route is None:
            return False, "این Route وجود ندارد.", None
        cfg = self._provider_cfg(route)
        t0 = time.monotonic()
        try:
            if route["provider"] == "ollama":
                client = self._make_provider(route)
                client.num_predict = 32
                client.chat([{"role": "user", "content": "OK"}], "Reply with only: OK", 0.1)
                ok, msg = True, "اتصال و دریافت پاسخ موفق بود."
            else:
                merged = {**cfg, "model": route["model"], "timeout": min(int(route.get("timeout") or 15), 30)}
                ok, msg = probe_provider(route["provider"], merged)
        except Exception as exc:                                                    # noqa: BLE001
            ok, msg = False, redact(exc, cfg.get("api_key"))[:400]
        ms = int((time.monotonic() - t0) * 1000)
        st = self._state(route_id)
        st["last_attempt_at"] = time.time()
        if ok:
            self._mark_success(route, ms)
        else:
            st.update(health="down", last_error=redact(msg, cfg.get("api_key"))[:300], last_ms=None)
            st["failures"] += 1
        return ok, msg, ms

    def benchmark(self, route_ids, prompt="سلام! خودت را در یک جمله کوتاه معرفی کن.", max_tokens=48, on_progress=None):
        """Measure connect time, time-to-first-token, total time and speed for the chosen routes, ONE AT A TIME.
        Cloud routes use a little API quota (48 tokens each), so the caller asks the person first."""
        if not self._lock.acquire(blocking=False):
            raise RuntimeError("یک درخواست دیگر در حال انجام است؛ بعد از پایان آن Benchmark را اجرا کن.")
        try:
            return self._benchmark_locked(route_ids, prompt, max_tokens, on_progress)
        finally:
            self._active = None
            self._lock.release()

    def _benchmark_locked(self, route_ids, prompt, max_tokens, on_progress):
        results = []
        by_id = {r["id"]: r for r in self.routes()}
        self._cancel.clear()
        for rid in route_ids:
            route = by_id.get(rid)
            if route is None or self._cancel.is_set():
                continue
            info = self.route_info(route)
            if on_progress:
                on_progress({"phase": "running", **info})
            row = {**info, "ok": False, "connect_ms": None, "first_token_ms": None, "total_ms": None, "chars": 0,
                   "tokens": None, "speed": None, "unit": "chars/s", "error": None}
            t0 = time.monotonic()
            connect_at = first_at = None
            parts = []
            provider = None
            secrets = (self._provider_cfg(route).get("api_key"),)
            try:
                provider = self._make_provider(route)
                self._active = provider

                def on_connect():
                    nonlocal connect_at
                    connect_at = time.monotonic()
                for chunk in provider.stream([{"role": "user", "content": prompt}], "پاسخ را کوتاه بده.", 0.3,
                                             on_connect=on_connect, max_tokens=max_tokens):
                    if chunk and first_at is None:
                        first_at = time.monotonic()
                    parts.append(chunk)
                    if self._cancel.is_set():
                        break
                end = time.monotonic()
                text = "".join(parts)
                row.update(ok=bool(text), chars=len(text), total_ms=int((end - t0) * 1000),
                           connect_ms=int((connect_at - t0) * 1000) if connect_at else None,
                           first_token_ms=int((first_at - t0) * 1000) if first_at else None)
                stats = getattr(provider, "last_stats", None)
                if isinstance(stats, dict) and stats.get("eval_tokens") and stats.get("eval_ms"):
                    row.update(tokens=stats["eval_tokens"], speed=round(stats["eval_tokens"] / (stats["eval_ms"] / 1000), 1), unit="tok/s",
                               load_ms=stats.get("load_ms"))
                elif first_at and end > first_at and text:
                    row["speed"] = round(len(text) / (end - first_at), 1)
                if route["provider"] == "ollama" and hasattr(provider, "running"):       # RAM / VRAM share of the loaded model
                    try:
                        for m in provider.running():
                            if str(m.get("name", "")).split(":")[0] == str(getattr(provider, "active_model", "")).split(":")[0]:
                                size, vram = int(m.get("size") or 0), int(m.get("size_vram") or 0)
                                if size:
                                    row.update(model_gb=round(size / 1e9, 1), gpu_pct=round(100 * vram / size))
                                break
                    except Exception:                                                     # noqa: BLE001 - optional extra info
                        pass
                if not text:
                    row["error"] = "پاسخ خالی"
                if row["ok"]:
                    self._mark_success(route, row["total_ms"])
            except Exception as exc:                                              # noqa: BLE001
                row["error"] = redact(exc, *secrets)[:200]
                self._mark_failure(route, exc, secrets)
            finally:
                self._active = None
            self.benchmarks.append(row)
            self._write_telemetry({"benchmark": True, **{k: row.get(k) for k in ("provider", "model", "kind", "ok", "connect_ms", "first_token_ms",
                                                                                 "total_ms", "chars", "tokens", "speed", "unit")}},
                                  "route_benchmark.jsonl")
            results.append(row)
            if on_progress:
                on_progress({"phase": "done", **row})
        return results

    def status(self):
        now = time.monotonic()
        out = []
        for route in self.routes():
            ok, reason = self.eligibility(route)
            st = self._state(route["id"])
            out.append({"name": route["id"], "provider": route["provider"], "model": route["model"],
                        "kind": route_model.provider_kind(route["provider"], self._provider_cfg(route)),
                        "enabled": ok or reason == "cooldown", "reason": reason,
                        "cooldown": max(0, int(self.cooldowns.get(route["id"], 0) - now)),
                        "health": st["health"], "last_error": st["last_error"], "last_ms": st["last_ms"]})
        return out
