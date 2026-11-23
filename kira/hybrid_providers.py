"""Hybrid AI: provider adapters (cloud + local), Route-based router with failover, cooldowns, streaming and speed metrics.

Routes (kira/routes.py) say WHICH model to try and in what order; providers say HOW to talk to it.
Secrets come from the local settings file and are redacted from every error message and every log line.
"""
from __future__ import annotations

import contextlib
import contextvars
import json
import os
import re
import threading
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
import requests
from http.client import HTTPException
from urllib3.exceptions import HTTPError as Urllib3HTTPError
from typing import Any

from . import routes as route_model
from .leak_guard import LeakGuard, clean_final
from .request_trace import trace as request_trace, gemini_trace
from .ollama_client import OllamaClient, OllamaError
from .core.interfaces.chat_provider import ChatProvider
from .infrastructure.providers import ProviderRegistry
from .think_filter import ThinkFilter

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


def _gemini_finish(obj):
    try:
        return str(obj["choices"][0].get("finish_reason") or "")
    except (KeyError, IndexError, TypeError, AttributeError):
        pass
    try:
        return str(obj["candidates"][0].get("finishReason") or "").lower()
    except (KeyError, IndexError, TypeError, AttributeError):
        return ""


def _gemini_usage(obj):
    """Scalar token counts from an OpenAI-style 'usage' block (incl. thinking tokens when Google reports them)."""
    usage = obj.get("usage") if isinstance(obj, dict) else None
    meta = obj.get("usageMetadata") if isinstance(obj, dict) else None
    if isinstance(meta, dict) and not isinstance(usage, dict):                      # native shape
        out = {}
        for src, dst in (("promptTokenCount", "prompt_tokens"), ("candidatesTokenCount", "completion_tokens"),
                         ("totalTokenCount", "total_tokens"), ("thoughtsTokenCount", "thinking_tokens")):
            if isinstance(meta.get(src), int):
                out[dst] = meta[src]
        return out
    if not isinstance(usage, dict):
        return {}
    out = {}
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        if isinstance(usage.get(key), int):
            out[key] = usage[key]
    details = usage.get("completion_tokens_details")
    if isinstance(details, dict) and isinstance(details.get("reasoning_tokens"), int):
        out["thinking_tokens"] = details["reasoning_tokens"]
    return out



# --- Gemini native transport -------------------------------------------------------------------------------
# Google's OpenAI-compatible layer (/v1beta/openai) was timing out / returning 503 for the newest models while the
# native generateContent API answered. Kira keeps building OpenAI-shaped payloads (tests, tools, history all unchanged);
# for the models below the payload is translated to the native format at send time and the reply is translated back.
NATIVE_GEMINI_MODELS = {"gemini-3.8-flash", "gemini-4-hydrogen"}
_THOUGHT_SIG_BYPASS = "skip_thought_signature_validator"   # Google's documented value for history that carries no signature
_FINISH_MAP = {"STOP": "stop", "MAX_TOKENS": "length", "SAFETY": "content_filter", "RECITATION": "content_filter",
               "BLOCKLIST": "content_filter", "PROHIBITED_CONTENT": "content_filter", "SPII": "content_filter"}


def _native_parts(content):
    if isinstance(content, str):
        return [{"text": content}] if content.strip() else []
    parts = []
    for item in content or []:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "text" and str(item.get("text") or "").strip():
            parts.append({"text": str(item["text"])})
        elif item.get("type") == "image_url":
            url = str((item.get("image_url") or {}).get("url") or "")
            m = re.match(r"data:([^;,]+);base64,(.+)$", url, re.DOTALL)
            if m:
                parts.append({"inlineData": {"mimeType": m.group(1), "data": m.group(2)}})
    return parts


def _openai_to_native(payload):
    """OpenAI chat-completions payload -> Gemini generateContent body."""
    system, contents = [], []

    def push(role, parts):
        if not parts:
            return
        if contents and contents[-1]["role"] == role:
            contents[-1]["parts"].extend(parts)
        else:
            contents.append({"role": role, "parts": list(parts)})

    for msg in payload.get("messages") or []:
        role = msg.get("role")
        if role == "system":
            if str(msg.get("content") or "").strip():
                system.append(str(msg["content"]))
        elif role == "tool":
            push("user", [{"functionResponse": {"name": str(msg.get("name") or "tool"),
                                                "response": {"result": str(msg.get("content") or "")}}}])
        elif role == "assistant":
            parts = _native_parts(msg.get("content") or "")
            for i, call in enumerate(msg.get("tool_calls") or []):
                fn = call.get("function") or {}
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except (TypeError, ValueError):
                    args = {}
                part = {"functionCall": {"name": str(fn.get("name") or ""), "args": args if isinstance(args, dict) else {}}}
                sig = ((call.get("extra_content") or {}).get("google") or {}).get("thought_signature") or (_THOUGHT_SIG_BYPASS if i == 0 else None)
                if sig:
                    part["thoughtSignature"] = sig
                parts.append(part)
            push("model", parts)
        else:
            push("user", _native_parts(msg.get("content")))
    body = {"contents": contents}
    if system:
        body["systemInstruction"] = {"parts": [{"text": "\n\n".join(system)}]}
    gen = {}
    if payload.get("temperature") is not None:
        gen["temperature"] = payload["temperature"]
    if payload.get("max_tokens"):
        gen["maxOutputTokens"] = int(payload["max_tokens"])
    if payload.get("reasoning_effort"):
        gen["thinkingConfig"] = {"thinkingLevel": str(payload["reasoning_effort"])}
    if gen:
        body["generationConfig"] = gen
    decls = []
    for tool in payload.get("tools") or []:
        fn = tool.get("function") if isinstance(tool, dict) else None
        if isinstance(fn, dict) and fn.get("name"):
            decl = {"name": fn["name"], "description": fn.get("description") or ""}
            if fn.get("parameters"):
                decl["parametersJsonSchema"] = fn["parameters"]
            decls.append(decl)
    if decls:
        body["tools"] = [{"functionDeclarations": decls}]
    return body


def _native_to_openai(data):
    """Gemini generateContent reply (or one stream chunk) -> the OpenAI chat-completions shape the rest of Kira reads."""
    if not isinstance(data, dict) or "choices" in data or "candidates" not in data and "promptFeedback" not in data:
        return data
    cands = data.get("candidates") or []
    cand = cands[0] if cands and isinstance(cands[0], dict) else {}
    parts = (cand.get("content") or {}).get("parts") or []
    text = "".join(str(p.get("text")) for p in parts if isinstance(p, dict) and p.get("text") and not p.get("thought"))
    calls = []
    for i, part in enumerate(parts):
        fc = part.get("functionCall") if isinstance(part, dict) else None
        if isinstance(fc, dict) and fc.get("name"):
            call = {"id": str(fc.get("id") or f"gem_call_{i}"), "type": "function",
                    "function": {"name": fc["name"], "arguments": json.dumps(fc.get("args") or {}, ensure_ascii=False)}}
            if part.get("thoughtSignature"):
                call["extra_content"] = {"google": {"thought_signature": part["thoughtSignature"]}}
            calls.append(call)
    reason = str(cand.get("finishReason") or "")
    if calls:
        finish = "tool_calls"
    elif reason:
        finish = _FINISH_MAP.get(reason, reason.lower())
    else:
        finish = "content_filter" if (data.get("promptFeedback") or {}).get("blockReason") else ""
    message = {"role": "assistant", "content": text}
    if calls:
        message["tool_calls"] = calls
    out = {"choices": [{"message": message, "finish_reason": finish}]}
    meta = data.get("usageMetadata")
    if isinstance(meta, dict):
        prompt = int(meta.get("promptTokenCount") or 0)
        thoughts = int(meta.get("thoughtsTokenCount") or 0)
        completion = int(meta.get("candidatesTokenCount") or 0) + thoughts
        out["usage"] = {"prompt_tokens": prompt, "completion_tokens": completion,
                        "total_tokens": int(meta.get("totalTokenCount") or (prompt + completion)),
                        "completion_tokens_details": {"reasoning_tokens": thoughts}}
    return out


def _payload_shape(payload):
    """(messages, tools, reasoning_effort, max_tokens) of either payload shape, for the Gemini log."""
    gen = payload.get("generationConfig") or {}
    tools = 0
    for t in payload.get("tools") or []:
        if isinstance(t, dict):
            tools += len(t.get("functionDeclarations") or []) if "functionDeclarations" in t else 1
    return (len(payload.get("contents") or payload.get("messages") or []), tools,
            payload.get("reasoning_effort") or (gen.get("thinkingConfig") or {}).get("thinkingLevel"),
            payload.get("max_tokens") or gen.get("maxOutputTokens"))



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
            content_type = str(getattr(response, "headers", {}).get("Content-Type", "")).casefold()
            html_gateway_page = (
                "text/html" in content_type
                or bool(re.search(r"<\\s*(?:!doctype|html|head|title|meta)\\b", detail, re.IGNORECASE))
            )
            if html_gateway_page:
                raise self._fail(
                    f"درخواست از درگاه سرویس با صفحه HTML و کد 403 رد شد؛ این پاسخ به‌تنهایی نامعتبر بودن API Key را ثابت نمی‌کند. "
                    f"محدودیت IP/منطقه، VPN یا Proxy، محدودیت پروژه و محدودیت دسترسی Gemini API را بررسی کن. {detail}",
                    True, code, "network",
                )
            if "api_key_service_blocked" in low:
                raise self._fail(
                    f"کلید Google برای این API مجاز نیست؛ محدودیت API Key را روی Gemini API "
                    f"(generativelanguage.googleapis.com) تنظیم کن. {detail}",
                    False, code, "auth",
                )
            if "your project has been denied access" in low or "project is restricted" in low:
                raise self._fail(
                    f"دسترسی پروژه به سرویس «{self.name}» رد شده است؛ وضعیت و محدودیت‌های خود پروژه را بررسی کن. {detail}",
                    False, code, "permission",
                )
            if "model_permission_blocked" in low or "blocked at the project level" in low or "blocked at the organization level" in low:
                raise self._fail(
                    f"دسترسی مدل «{self.model}» در سطح پروژه یا سازمان «{self.name}» مسدود است؛ مجوز مدل را در تنظیمات Provider بررسی کن. {detail}",
                    False, code, "model",
                )
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
            raise self._fail(
                f"Provider دسترسی درخواست را رد کرد ({code})؛ ممکن است API Key معتبر باشد اما مجوز پروژه/سازمان یا دسترسی به مدل کافی نباشد. {detail}",
                False, code, "permission",
            )
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
        google = self._is_google_endpoint()
        if google:
            # Dedicated Gemini log: exactly where this request goes and with which settings (never prompts or keys).
            path = __import__("urllib.parse", fromlist=["urlsplit"]).urlsplit(url).path
            n_msgs, n_tools, effort, max_out = _payload_shape(payload)
            gemini_trace("request", route=self.name, model=self.model, host=host, path=path, stream=bool(stream),
                         api="native" if "contents" in payload else "openai-compat",
                         temperature=(payload.get("generationConfig") or payload).get("temperature"), reasoning_effort=effort,
                         max_tokens=max_out, messages=n_msgs, tools=n_tools,
                         has_images=bool(getattr(self, "_sent_images", False)),
                         read_timeout_s=timeout[1] if isinstance(timeout, tuple) else timeout)
        try:
            response = requests.post(url, timeout=timeout, **kwargs)
        except Exception as exc:
            request_trace("http_transport_error", provider=self.name, model=self.model, host=host, error_type=type(exc).__name__, elapsed_ms=int((time.monotonic()-started)*1000))
            if google:
                gemini_trace("transport_error", model=self.model, error_type=type(exc).__name__, elapsed_ms=int((time.monotonic()-started)*1000),
                             note="request was sent; Google may still count it against quota")
            raise
        request_trace("http_headers", provider=self.name, model=self.model, host=host, status_code=int(response.status_code), elapsed_ms=int((time.monotonic()-started)*1000), stream=bool(stream))
        if google:
            err = ""
            if response.status_code >= 400:
                try:
                    err = redact(_api_message(response), self.secret)
                except Exception:                                          # noqa: BLE001 - logging never breaks a request
                    err = ""
            gemini_trace("response", model=self.model, status_code=int(response.status_code), elapsed_ms=int((time.monotonic()-started)*1000),
                         retry_after=response.headers.get("Retry-After"), error=err or None)
        return response

    def _post_json(self, url, headers, payload):
        """POST and return the decoded JSON body. Every failure becomes a classified ProviderError."""
        body_started = time.monotonic()
        try:
            response = self._post_once(url, headers, payload)
        except requests.Timeout as exc:
            raise self._fail("مهلت پاسخ‌گویی سرویس تمام شد.", True, kind="timeout") from exc
        except (requests.RequestException, Urllib3HTTPError, HTTPException, OSError) as exc:
            raise self._fail(f"خطای شبکه: {exc}", True, kind="network") from exc
        self._check_status(response)
        try:
            data = response.json()
        except ValueError as exc:
            raise self._fail("پاسخ سرویس قابل خواندن نبود.", True, kind="response") from exc
        if ":generateContent" in url:
            data = _native_to_openai(data)
        self._note_usage(data)
        if self._is_google_endpoint():
            try:
                msg = (data.get("choices") or [{}])[0].get("message") or {}
                content = msg.get("content")
                chars = sum(len(str(x.get("text", ""))) for x in content if isinstance(x, dict)) if isinstance(content, list) else len(str(content or ""))
                gemini_trace("result", model=self.model, finish_reason=_gemini_finish(data) or None, content_chars=chars,
                             tool_calls=len(msg.get("tool_calls") or []), empty=(chars == 0 and not msg.get("tool_calls")),
                             **_gemini_usage(data))
            except Exception:                                              # noqa: BLE001
                pass
        request_trace("http_body_decoded", provider=self.name, model=self.model, elapsed_ms=int((time.monotonic()-body_started)*1000), response_shape="json")
        return data

    def _open_stream(self, url, headers, payload):
        """POST with stream=True; the status is checked before the first byte of the body is read."""
        try:
            response = self._post_once(url, headers, payload, stream=True)
        except requests.Timeout as exc:
            raise self._fail("مهلت اتصال به سرویس تمام شد.", True, kind="timeout") from exc
        except (requests.RequestException, Urllib3HTTPError, HTTPException, OSError) as exc:
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
        g_on = self._is_google_endpoint()
        g_chunks = g_raw = g_out = 0
        g_finish = ""
        g_usage = {}
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
                if g_on and isinstance(obj, dict):
                    g_chunks += 1
                    g_finish = _gemini_finish(obj) or g_finish
                    g_usage.update(_gemini_usage(obj))
                    g_raw += len(extract(obj) or "")
                if isinstance(obj, dict) and obj.get("error"):
                    err = obj["error"]
                    msg = err.get("message") if isinstance(err, dict) else err
                    raise self._fail(f"خطای سرویس وسط پاسخ: {str(msg)[:300]}", True, kind="server")
                piece = flt.feed(extract(obj) or "")
                if piece:
                    g_out += len(piece)
                    yield piece
            tail = flt.flush()
            if tail:
                g_out += len(tail)
                yield tail
        except requests.Timeout as exc:
            request_trace("stream_read_timeout", provider=self.name, model=self.model, elapsed_ms=int((time.monotonic()-stream_started)*1000))
            raise self._fail("سرویس وسط پاسخ ساکت شد (Timeout).", True, kind="timeout") from exc
        except (requests.RequestException, Urllib3HTTPError, HTTPException, OSError) as exc:
            request_trace(
                "stream_transport_error",
                provider=self.name,
                model=self.model,
                error_type=type(exc).__name__,
            )
            raise self._fail(f"ارتباط وسط پاسخ قطع شد: {exc}", True, kind="network") from exc
        finally:
            request_trace("stream_closed", provider=self.name, model=self.model, elapsed_ms=int((time.monotonic()-stream_started)*1000))
            if g_on:
                gemini_trace("stream_closed", model=self.model, elapsed_ms=int((time.monotonic()-stream_started)*1000), chunks=g_chunks,
                             raw_chars=g_raw, shown_chars=g_out, finish_reason=g_finish or None, empty=(g_out == 0), **g_usage)
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
        data = self._send_json(url, headers, payload)
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
            data = self._send_json(url, headers, payload)
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

    # ---- Gemini native transport (see NATIVE_GEMINI_MODELS) ----
    def _native_enabled(self):
        if not self._is_google_endpoint() or str(os.environ.get("KIRA_GEMINI_NATIVE", "1")).strip() in ("0", "false", "off"):
            return False
        if self.config.get("gemini_native", True) is False:
            return False
        return _bare_model_id(self.model).casefold() in NATIVE_GEMINI_MODELS

    def _maybe_native(self, url, headers, payload, stream):
        """(url, headers, body) for Google's native API, or the arguments unchanged when this route does not use it."""
        if not self._native_enabled():
            return url, headers, payload
        base = self._base()
        base = base[:-len("/openai")] if base.endswith("/openai") else base
        suffix = (f"/models/{_bare_model_id(self.model)}:streamGenerateContent?alt=sse" if stream
                  else f"/models/{_bare_model_id(self.model)}:generateContent")
        return base + suffix, {"Content-Type": "application/json", "x-goog-api-key": self.secret}, _openai_to_native(payload)

    @staticmethod
    def _native_rejected(exc):
        """Only a plain 400 means 'this request shape is not accepted': safe to retry once on the OpenAI-compatible route
        (a 400 does not consume quota; timeouts / 5xx / 429 are never replayed because they may)."""
        return getattr(exc, "status_code", None) == 400 and getattr(exc, "kind", "") == "request"

    def _send_json(self, url, headers, payload):
        n_url, n_headers, n_payload = self._maybe_native(url, headers, payload, False)
        if n_url == url:
            return self._post_json(url, headers, payload)
        try:
            return self._post_json(n_url, n_headers, n_payload)
        except ProviderError as exc:
            if not self._native_rejected(exc):
                raise
            gemini_trace("native_rejected_use_openai_compat", model=self.model, error=redact(str(exc), self.secret)[:200])
            return self._post_json(url, headers, payload)

    @staticmethod
    def _extract_native(obj):
        if isinstance(obj, dict) and "choices" in obj:
            return OpenAICompatibleProvider._extract(obj)
        try:
            parts = obj["candidates"][0]["content"]["parts"]
        except (KeyError, IndexError, TypeError):
            return ""
        return "".join(str(p.get("text")) for p in parts if isinstance(p, dict) and p.get("text") and not p.get("thought"))

    def stream(self, messages, system_prompt, temperature=0.7, on_connect=None, max_tokens=None):
        url, headers, payload = self._prepare(messages, system_prompt, temperature, True, max_tokens)
        n_url, n_headers, n_payload = self._maybe_native(url, headers, payload, True)
        if n_url == url:
            return self._stream_sse(url, headers, payload, self._extract, on_connect)
        return self._stream_native(n_url, n_headers, n_payload, (url, headers, payload), on_connect)

    def _stream_native(self, n_url, n_headers, n_payload, compat, on_connect):
        started = False
        inner = self._stream_sse(n_url, n_headers, n_payload, self._extract_native, on_connect)
        try:
            for piece in inner:
                started = True
                yield piece
            return
        except ProviderError as exc:
            if started or not self._native_rejected(exc):
                raise
            gemini_trace("native_rejected_use_openai_compat", model=self.model, error=redact(str(exc), self.secret)[:200])
        finally:
            inner.close()
        fallback = self._stream_sse(compat[0], compat[1], compat[2], self._extract, on_connect)
        try:
            yield from fallback
        finally:
            fallback.close()


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
        # Use Cloudflare's documented OpenAI-compatible Chat Completions API.
        # The legacy /ai/run/{model} endpoint expects model-specific input shapes;
        # it is not a universal chat endpoint for classification/embedding models.
        url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/v1/chat/completions"
        headers = {"Authorization": f"Bearer {self.secret}", "Content-Type": "application/json"}
        payload = {"model": self.model,
                   "messages": [{"role": "system", "content": system_prompt}, *[{"role": m["role"], "content": m["content"]} for m in clean]],
                   "temperature": float(temperature), "stream": bool(stream)}
        if max_tokens:
            payload["max_tokens"] = int(max_tokens)
        return url, headers, payload

    def chat(self, messages, system_prompt, temperature=0.7):
        url, headers, payload = self._prepare(messages, system_prompt, temperature, False)
        data = self._post_json(url, headers, payload)
        try:
            choices = data.get("choices")
            content = (
                choices[0].get("message", {}).get("content")
                if isinstance(choices, list) and choices else None
            )
            if not content:
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
