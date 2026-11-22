"""Hybrid AI: provider adapters (cloud + local), Route-based router with failover, cooldowns, streaming and speed metrics.

Routes (kira/routes.py) say WHICH model to try and in what order; providers say HOW to talk to it.
Secrets come from the local settings file and are redacted from every error message and every log line.
"""
from __future__ import annotations

import contextlib
import contextvars
import json
import re
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
from .request_trace import trace as request_trace
from .ollama_client import OllamaClient, OllamaError
from .core.interfaces.chat_provider import ChatProvider
from .infrastructure.providers import ProviderRegistry

COOLDOWN_RATE_LIMIT = 300      # seconds after HTTP 429 (or Retry-After, capped)
COOLDOWN_TRANSIENT = 45        # network / timeout / 5xx (default; each route can override it)
COOLDOWN_CONFIG = 60           # bad key / bad model: stop retrying on every message (reset when settings are saved)
THINKING_MIN_MAX_TOKENS = 1024  # floor for max_tokens on Gemini thinking models (thinking shares this budget)
METRICS_KEEP = 200            # in-memory history of request metrics (bounded: no memory growth)

# Brain-role scope is per logical request, not per router instance: two sessions (or a
# background reviewer and the visible chat) may use the same router from different threads.
_ROLE = contextvars.ContextVar("kira_route_role", default="")
_PREFER = contextvars.ContextVar("kira_route_prefer", default="")
_VISION_ONLY = contextvars.ContextVar("kira_vision_only", default=False)



class ProviderError(RuntimeError):
    def __init__(self, provider: str, message: str, retryable: bool = True,
                 status_code: int | None = None, kind: str = "error", retry_after: float | None = None):
        super().__init__(message)
        self.provider = provider
        self.retryable = retryable
        self.status_code = status_code
        self.kind = kind                # auth | model | request | rate | server | network | timeout | response | empty
        self.retry_after = retry_after
        self.quota = ""                 # 429 only: "no_free" | "daily" | "" (see quota_kind)


def normalize_messages(messages, preserve_tool_messages=False):
    """Provider-neutral cleanup. Native OpenAI-compatible tool turns may preserve assistant/tool messages."""
    out = []
    allowed = ("user", "assistant", "tool") if preserve_tool_messages else ("user", "assistant")
    for item in messages or []:
        role = item.get("role")
        if role not in allowed:
            continue
        content = str(item.get("content") or "").strip()
        images = [i for i in (item.get("images") or []) if isinstance(i, dict) and i.get("b64")] if role == "user" else []
        tool_calls = item.get("tool_calls") if role == "assistant" and preserve_tool_messages else None
        if role == "tool":
            call_id = str(item.get("tool_call_id") or "").strip()
            if not call_id or not content:
                continue
            out.append({"role": "tool", "tool_call_id": call_id, "name": str(item.get("name") or ""), "content": content})
            continue
        if not (content or images or tool_calls):
            continue
        content = content or ("(تصویر ضمیمه)" if images else "")
        if out and out[-1]["role"] == role and role != "tool" and not tool_calls and not out[-1].get("tool_calls"):
            out[-1]["content"] += ("\n\n" if out[-1]["content"] and content else "") + content
            if images:
                out[-1].setdefault("images", []).extend(images)
        else:
            entry = {"role": role, "content": content}
            if images:
                entry["images"] = list(images)
            if tool_calls:
                entry["tool_calls"] = list(tool_calls)
            out.append(entry)
    while out and out[0]["role"] == "assistant" and not out[0].get("tool_calls"):
        out.pop(0)
    while out and out[-1]["role"] == "assistant" and not out[-1].get("tool_calls"):
        out.pop()
    return out


def _openai_message(item):
    """OpenAI-style message, preserving native tool-call turns and image parts."""
    role = item["role"]
    if role == "tool":
        return {"role": "tool", "tool_call_id": item["tool_call_id"], "name": item.get("name") or "", "content": item["content"]}
    if item.get("tool_calls"):
        return {"role": "assistant", "content": item.get("content") or None, "tool_calls": item["tool_calls"]}
    images = item.get("images")
    if not images:
        return {"role": role, "content": item["content"]}
    parts = [{"type": "text", "text": item["content"]}]
    for img in images:
        parts.append({"type": "image_url", "image_url": {"url": f"data:{img.get('mime') or 'image/png'};base64,{img['b64']}"}})
    return {"role": role, "content": parts}


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


_REPLACEMENT_MODEL = re.compile(r"(?:use|switch to|migrate to)\s+models/([A-Za-z0-9._\-]+)", re.IGNORECASE)


def _suggested_model(response, current=""):
    """Replacement model named by the provider itself in a 404 body ('... please use models/gemini-3.8-flash ...').

    Reads the whole body: _api_message() is truncated and the suggestion sits at the end of Google's sentence."""
    try:
        text = response.text or ""
    except Exception:
        return ""
    found = _REPLACEMENT_MODEL.search(text)
    suggestion = found.group(1) if found else ""
    return suggestion if suggestion and suggestion != _bare_model_id(current) else ""


def quota_kind(response):
    """Why a 429 happened, from the provider's own body: 'no_free' (limit 0: this model has no free quota),
    'daily' (per-day quota used up) or '' (ordinary per-minute rate limit / unknown)."""
    try:
        text = (response.text or "").lower()
    except Exception:
        return ""
    if re.search(r"limit:\s*0\b", text) or '"limit": 0' in text:
        return "no_free"
    if "perday" in text.replace("_", "").replace(" ", "") or "per day" in text or "daily" in text:
        return "daily"
    return ""


_QUOTA_TEXT = {
    "no_free": "این مدل در پلن رایگان سهمیه‌ای ندارد (limit: 0)؛ مدل Flash یا Flash-Lite دیگری را انتخاب کن.",
    "daily": "سهمیه‌ی روزانه‌ی این مدل تمام شده؛ تا بازنشانی (حدود نیمه‌شب وقت آمریکا) صبر کن یا مدل دیگری را امتحان کن.",
}


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
    def __init__(self, data: bytes, callback, cancel_event=None):
        self._data, self._pos, self._cb, self._last = data, 0, callback, -1
        self._cancel_event = cancel_event

    def __len__(self):
        return len(self._data)

    def read(self, size=-1):
        if self._cancel_event is not None and self._cancel_event.is_set():
            raise RuntimeError("درخواست لغو شده است.")
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


class BaseProvider(ChatProvider):
    name = "base"
    upload_progress = None                  # optional callback(percent) - set by the router; used when a request carries images
    auth_hint = "کلید API نامعتبر است یا دسترسی ندارد"
    needs_key = True

    def __init__(self, config: dict[str, Any], name: str | None = None):
        self.config = config or {}
        if name:
            self.name = name
        self.model = route_model.normalize_model_id(self.config.get("model", ""))
        base_url = str(self.config.get("base_url") or "").lower()
        if "generativelanguage.googleapis.com" in base_url and self.model.startswith("models/"):
            self.model = self.model[7:]
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
            quota = quota_kind(response)
            err = self._fail("سهمیه یا محدودیت درخواست تمام شده (429)." + (" " + _QUOTA_TEXT[quota] if quota else ""),
                             True, 429, "rate", retry_after)
            err.quota = quota
            raise err
        if code >= 500:
            raise self._fail(f"خطای سرور سرویس ({code}).", True, code, "server")
        if code == 403:
            detail = _api_message(response)
            low = detail.casefold()
            # Several providers use 403 for model/plan gates, not invalid credentials.
            model_access_terms = (
                "not available on the workers free plan", "not available for free",
                "model agreement", "submit the prompt 'agree'", "submit 'agree'",
                "paid version is available", "requires a paid plan", "requires payment",
                "model is not available", "model access is denied",
            )
            if any(term in low for term in model_access_terms):
                raise self._fail(f"مدل «{self.model}» در پلن یا سطح دسترسی فعلی قابل استفاده نیست ({code}). {detail}",
                                 False, code, "model")
            if "network settings" in low or "ip address" in low or "geo restriction" in low:
                raise self._fail(f"دسترسی شبکه به {self.name} رد شد ({code}). تنظیمات شبکه، VPN یا محدودیت IP را بررسی کن. {detail}",
                                 True, code, "network")
            raise self._fail(f"{self.auth_hint} ({code}). {detail}", False, code, "auth")
        if code == 401:
            raise self._fail(f"{self.auth_hint} ({code}). {_api_message(response)}", False, code, "auth")
        if code >= 400:
            detail = _api_message(response)
            low = detail.lower()
            if code == 404 or "model" in low and ("not found" in low or "does not exist" in low or "not_found" in low
                                                    or "decommissioned" in low or "no longer supported" in low
                                                    or "invalid model" in low or "unknown model" in low):
                suggestion = _suggested_model(response, self.model)
                hint = (f" — سرویس خودش مدل «{suggestion}» را پیشنهاد می‌دهد؛ Model ID همین Route را به آن تغییر بده."
                        if suggestion else "")
                raise self._fail(f"شناسه مدل «{self.model}» معتبر نیست یا حساب به آن دسترسی ندارد ({code}). {detail}{hint}",
                                 False, code, "model")
            hint = (" — تصویر ضمیمه شده بود؛ شاید این مدل بینایی (Vision) ندارد. یک مدل بینایی مثل Gemini انتخاب کن."
                    if getattr(self, "_sent_images", False) and code in (400, 415, 422) else "")
            raise self._fail(f"درخواست نامعتبر ({code}): {detail}{hint}", False, code, "request")

    def _send_args(self, headers, payload):
        """requests keyword args: plain json normally, a progress-reporting body when the upload is big (images / large files).
        A long prompt is not an upload: text-only requests keep the plain ``json=`` body."""
        if self.upload_progress:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            if getattr(self, "_sent_images", False) or len(body) > 1_000_000:
                return {"data": ProgressBody(body, self.upload_progress, getattr(self, "cancel_event", None)),
                        "headers": {**headers, "Content-Type": "application/json"}}
        return {"json": payload, "headers": headers}

    def _is_google_endpoint(self):
        base = str(self.config.get("base_url") or "").lower()
        return "generativelanguage.googleapis.com" in base

    def _post_once(self, url, headers, payload, *, stream=False):
        """Send exactly one provider request.

        Google free-tier request quotas may count failed 503 attempts toward the
        model's daily request limit. Retrying the same request here can therefore
        burn multiple RPD units before HybridRouter gets a chance to fail over.
        Let the router classify the single response and apply its normal cooldown.
        """
        kwargs = self._send_args(headers, payload)
        if stream:
            kwargs["stream"] = True
        timeout = (min(10, self.timeout), self.timeout) if stream else self.timeout
        started = time.monotonic()
        host = __import__("urllib.parse", fromlist=["urlsplit"]).urlsplit(url).hostname or "unknown"
        request_trace("http_send", provider=self.name, model=self.model, host=host, stream=bool(stream), connect_timeout=timeout[0] if isinstance(timeout, tuple) else timeout, read_timeout=timeout[1] if isinstance(timeout, tuple) else timeout)
        try:
            response = requests.post(url, timeout=timeout, **kwargs)
        except Exception as exc:
            request_trace("http_transport_error", provider=self.name, model=self.model, host=host, error_type=type(exc).__name__, elapsed_ms=int((time.monotonic()-started)*1000))
            raise
        request_trace("http_headers", provider=self.name, model=self.model, host=host, status_code=int(response.status_code), elapsed_ms=int((time.monotonic()-started)*1000), stream=bool(stream))
        return response

    def _post_json(self, url, headers, payload):
        """POST and return the decoded JSON body. Every failure becomes a classified ProviderError."""
        body_started = time.monotonic()
        try:
            response = self._post_once(url, headers, payload)
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
        request_trace("http_body_decoded", provider=self.name, model=self.model, elapsed_ms=int((time.monotonic()-body_started)*1000), response_shape="json")
        return data

    def _open_stream(self, url, headers, payload):
        """POST with stream=True; the status is checked before the first byte of the body is read."""
        try:
            response = self._post_once(url, headers, payload, stream=True)
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
        stream_started = time.monotonic()
        first_event = False
        try:
            for data in iter_sse(response):
                if not first_event:
                    first_event = True
                    request_trace("first_sse_event", provider=self.name, model=self.model, elapsed_ms=int((time.monotonic()-stream_started)*1000))
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
            request_trace("stream_read_timeout", provider=self.name, model=self.model, elapsed_ms=int((time.monotonic()-stream_started)*1000))
            raise self._fail("سرویس وسط پاسخ ساکت شد (Timeout).", True, kind="timeout") from exc
        except requests.RequestException as exc:
            raise self._fail(f"ارتباط وسط پاسخ قطع شد: {exc}", True, kind="network") from exc
        finally:
            request_trace("stream_closed", provider=self.name, model=self.model, elapsed_ms=int((time.monotonic()-stream_started)*1000))
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
        base = str(self.config.get("base_url") or self.endpoint).rstrip("/")
        # Google exposes its OpenAI-compatible Chat Completions API under
        # /v1beta/openai. Accept the common host-only and /v1beta base URLs
        # entered in API Manager, while preserving an already-correct path.
        if "://" in base:
            authority, _, path = base.split("://", 1)[1].partition("/")
            hostname = authority.rsplit("@", 1)[-1].split(":", 1)[0].lower()
            if hostname == "generativelanguage.googleapis.com":
                clean_path = "/" + path.rstrip("/") if path else ""
                if clean_path in ("", "/v1beta"):
                    base += "/v1beta/openai" if not clean_path else "/openai"
        return base

    def _prepare(self, messages, system_prompt, temperature, stream, max_tokens=None):
        if (self.needs_key and not self.secret) or not self.model:
            raise self._fail("API Key یا مدل تنظیم نشده است.", False, kind="auth")
        if not self._base():
            raise self._fail("آدرس (Base URL) تنظیم نشده است.", False, kind="request")
        clean = normalize_messages(messages, preserve_tool_messages=True)
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
        if self._is_google_endpoint() and self.model.casefold() in {
            "gemini-3.8-flash",
            "gemini-4-hydrogen",
        }:
            # Keep Google's low-latency Flash/Hydrogen chat routes responsive.
            # Hydrogen defaults to HIGH thinking; reasoning_effort maps to the
            # model's supported thinking_level on the OpenAI-compatible endpoint.
            payload["reasoning_effort"] = "low"
            if max_tokens:
                # Thinking tokens are paid from the same max_tokens budget as the
                # visible reply. A tiny cap (e.g. the 48-token Benchmark) would be
                # spent entirely on thinking: empty text, but quota still used.
                max_tokens = max(int(max_tokens), THINKING_MIN_MAX_TOKENS)
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
            finish = ""
            try:
                finish = str(data["choices"][0].get("finish_reason") or "")
            except (KeyError, IndexError, TypeError, AttributeError):
                pass
            if finish == "length":
                raise self._fail("مدل پاسخ خالی برگرداند: سقف توکن خروجی (شامل توکن‌های thinking) تمام شد.", True, kind="response")
            if finish:
                raise self._fail(f"مدل پاسخ خالی برگرداند (finish_reason={finish}).", True, kind="response")
            raise self._fail("مدل پاسخ خالی برگرداند.", True, kind="response")
        return content

    def chat_with_tools(self, messages, system_prompt, temperature=0.7, tools=None):
        """One non-streaming native function-calling round for OpenAI-compatible endpoints."""
        if not tools:
            return {"text": "", "tool_calls": []}
        url, headers, payload = self._prepare(messages, system_prompt, temperature, False)
        payload["tools"] = [{"type": "function", "function": schema} for schema in tools]
        payload["tool_choice"] = "auto"
        try:
            data = self._post_json(url, headers, payload)
        except ProviderError as exc:
            detail = str(exc).lower()
            unsupported = (
                "does not support tools",
                "doesn't support tools",
                "tool calling is not supported",
                "tools are not supported",
                "does not support tool calls",
                "unsupported tools",
                "tool use is not supported",
            )
            if exc.status_code in (400, 422) and any(term in detail for term in unsupported):
                return None
            raise
        try:
            message = data["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise self._fail("ساختار پاسخ Function Calling شناخته‌شده نیست.", True, kind="response") from exc
        content = message.get("content")
        if isinstance(content, list):
            content = "\n".join(str(x.get("text", "")) for x in content if isinstance(x, dict))
        calls = []
        for item in (message.get("tool_calls") or []):
            if not isinstance(item, dict):
                continue
            fn = item.get("function") or {}
            name = str(fn.get("name") or "").strip()
            raw_args = fn.get("arguments", "{}")
            try:
                args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
            except (TypeError, ValueError):
                args = None
            if name:
                calls.append({"id": str(item.get("id") or ""), "tool": name,
                              "args": args if isinstance(args, dict) else {}})
        return {"text": str(content or "").strip(), "tool_calls": calls}

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
        if any(item.get("images") for item in clean):
            raise self._fail("مدل انتخاب‌شده در Cloudflare این مسیر تصویر را پشتیبانی نمی‌کند؛ برای تحلیل تصویر یک مدل Vision انتخاب کن.", False, kind="request")
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
PROVIDER_REGISTRY = ProviderRegistry(PROVIDER_CLASSES)


def provider_class(name, cfg=None):
    """Resolve a registered adapter, then support configured OpenAI-compatible endpoints."""
    registered = PROVIDER_REGISTRY.resolve(name)
    if registered is not None:
        return registered
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


def probe_provider(name, config, provider_cls=None, *, timeout=None):
    """Real connection test used by the Route panel. Returns (ok, message).

    When timeout is supplied, it is an overall budget shared by model discovery
    and the tiny generation request, not a fresh timeout for each HTTP call.
    """
    config = dict(config or {})
    cls = provider_cls or provider_class(name, config)
    if not cls:
        return False, "سرویس ناشناخته است."
    provider = cls(config, name=name)
    deadline = None
    if timeout is not None:
        try:
            budget = max(1.0, float(timeout))
        except (TypeError, ValueError):
            budget = 15.0
        deadline = time.monotonic() + budget
        provider.timeout = min(float(provider.timeout), budget)

    def remaining(default):
        if deadline is None:
            return default
        left = deadline - time.monotonic()
        return max(0.0, min(float(default), left))

    try:
        if cls is not CloudflareProvider and cls is not OpenRouterProvider:
            base = provider._base()
            headers = {"Authorization": "Bearer " + provider.secret} if provider.secret else {}
            get_timeout = remaining(15)
            if get_timeout <= 0:
                return False, "مهلت تست مدل تمام شد."
            try:
                response = requests.get(base + "/models", headers=headers, timeout=get_timeout)
            except requests.Timeout:
                return False, "مهلت بررسی مدل‌ها تمام شد (شبکه یا VPN را بررسی کن)."
            except requests.RequestException as exc:
                return False, redact(f"خطای شبکه هنگام بررسی مدل‌ها: {exc}", provider.secret)[:400]
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
        for attempt in range(3):                                   # bounded retries within the test's shared time budget
            call_timeout = remaining(provider.timeout)
            if call_timeout <= 0:
                return False, "مهلت تست مدل تمام شد."
            provider.timeout = call_timeout
            try:
                provider.chat([{"role": "user", "content": "Reply with only: OK"}], "You are a connection test.", 0.1)
                return True, "اتصال و دریافت پاسخ موفق بود."
            except ProviderError as exc:
                last = exc
                # A probe is diagnostic, not a chat turn. Google may account a
                # timed-out or failed generation attempt against RPM/RPD even when
                # the client never receives a response. Never replay it: one probe
                # must produce at most one generation request for a Google model.
                if exc.status_code == 429 or getattr(exc, "quota", ""):
                    return False, str(exc)[:400]
                if provider._is_google_endpoint():
                    return False, str(exc)[:400]
                if exc.kind not in ("server", "rate") and exc.status_code not in (500, 502, 503, 504):
                    raise
                if attempt < 2:
                    delay = 2 * (attempt + 1)
                    if deadline is not None and remaining(delay) < delay:
                        return False, str(exc)[:400]
                    time.sleep(delay)
        if getattr(last, "quota", ""):                       # the message already says exactly what to do
            return False, str(last)[:400]
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
