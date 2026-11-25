"""Hybrid AI router: route selection, failover, cooldowns, streaming and speed metrics."""
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
from .app.detected_capabilities import DetectedCapabilities
from .request_trace import trace as request_trace, set_request_id as set_trace_request_id, reset_request_id as reset_trace_request_id
from .leak_guard import LeakGuard, clean_final
from .route_policy import RoutePolicyEngine
from .ollama_client import OllamaClient, OllamaError
from .core.interfaces.chat_provider import ChatProvider
from .hybrid_providers import (  # noqa: F401 - re-exported for backward compatibility
    COOLDOWN_CONFIG,
    COOLDOWN_RATE_LIMIT,
    COOLDOWN_TRANSIENT,
    METRICS_KEEP,
    PROVIDER_CLASSES,
    PROVIDER_REGISTRY,
    BaseProvider,
    CloudflareProvider,
    CustomOpenAIProvider,
    GroqProvider,
    MistralProvider,
    OpenAICompatibleProvider,
    OpenRouterProvider,
    ProgressBody,
    ProviderError,
    ProviderRegistry,
    ThinkFilter,
    _PREFER,
    _ROLE,
    _VISION_ONLY,
    _api_message,
    _bare_model_id,
    _openai_message,
    _suggested_model,
    classify,
    iter_sse,
    normalize_messages,
    probe_provider,
    provider_class,
    quota_kind,
    redact,
)

class HybridRouter:
    """Ordered Route router: manual choice > priority order; per-route timeout and cooldown; failover; streaming; metrics."""

    def __init__(self, settings: dict, *, detected_capabilities: DetectedCapabilities | None = None):
        self.settings = settings
        self.detected_capabilities = detected_capabilities or DetectedCapabilities()
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
        self._vision_capability_cache = {}
        self.route_policy = RoutePolicyEngine()
        self.last_route_decisions = []

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

    def eligibility(self, route, *, include_cooldown=True):
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
        if include_cooldown and self.cooldowns.get(route["id"], 0) - time.monotonic() > 0:
            return False, "cooldown"
        return True, "ok"

    @property
    def _role(self):
        """The active brain role for this context (read-only view of the ContextVar)."""
        return _ROLE.get()

    @property
    def _prefer(self):
        """The route a role asked for first in this context (read-only view of the ContextVar)."""
        return _PREFER.get()

    @contextlib.contextmanager
    def role_scope(self, role="", route_id=""):
        """Requests made inside this block belong to a brain role: the role is written to the metrics, and `route_id` (when it names an
        existing route) is tried FIRST. If that route is unusable the normal order follows, so a role never stops the conversation.
        The scope is stored in a ContextVar, so concurrent requests on the same router cannot overwrite each other."""
        role_token = _ROLE.set(str(role or ""))
        route_token = _PREFER.set(str(route_id or ""))
        try:
            yield self
        finally:
            _PREFER.reset(route_token)
            _ROLE.reset(role_token)

    def _candidates(self):
        """Return the ordered plan produced by RoutePolicyEngine.

        Network permission, role allowlists, vision constraints and manual priority
        are policy. Provider health and cooldown are runtime state and are evaluated
        separately when a candidate is actually considered.
        """
        ordered, decisions = self.route_policy.select(
            self.routes(),
            self.settings,
            role=_ROLE.get(),
            preferred_route_id=_PREFER.get(),
            vision_only=_VISION_ONLY.get(),
            provider_cfg=self._provider_cfg,
            provider_kind=route_model.provider_kind,
            is_google=route_model.is_google,
            is_eligible=lambda route: self.eligibility(route, include_cooldown=False)[0],
            supports_vision=self._route_supports_vision,
        )
        self.last_route_decisions = [
            {"route_id": item.route_id, "allowed": item.allowed, "reason": item.reason}
            for item in decisions
        ]
        return ordered

    def vision_route_id(self):
        """Return an eligible vision route, independent of the active text-role allowlist.

        Unknown models are deliberately excluded: a text-only route must never receive a screen frame.
        Custom providers can opt in with providers[provider].vision_enabled = true.
        """
        token = _VISION_ONLY.set(True)
        try:
            for route in self._candidates():
                ok, _ = self.eligibility(route)
                if ok and self._route_supports_vision(route, self._provider_cfg(route)):
                    return str(route.get("id") or "")
            return None
        finally:
            _VISION_ONLY.reset(token)

    def _route_supports_vision(self, route, cfg):
        model = str(route.get("model") or "").lower()
        provider = str(route.get("provider") or "").lower()
        known = (
            "gemini", "gpt-4o", "gpt-4.1", "gpt-5", "claude-3", "claude-sonnet",
            "claude-opus", "claude-haiku", "claude-4", "llava", "qwen-vl", "qwen2.5-vl", "qwen3-vl",
            "qwen3.5", "qwen35", "minicpm-v", "pixtral", "molmo", "internvl",
            "llama-3.2-vision",
        )
        if cfg.get("vision_enabled") is True:
            return True
        # Embedding endpoints do not accept conversational image input, even when
        # their provider family also offers multimodal generation models.
        if "embedding" in model or model.startswith("text-embedding"):
            return False
        if provider == "ollama":
            # Capabilities belong to a specific Ollama server + model pair.
            endpoint = str(self.settings.get("ollama_url") or "http://localhost:11434").rstrip("/")
            key = (provider, endpoint, model)
            cached = self._vision_capability_cache.get(key)
            now = time.monotonic()
            if cached and now - cached[0] < 300:
                return cached[1]
            capable = any(token in model for token in known)
            cacheable = False
            try:
                client = self._make_provider(route)
                response = client._post("/api/show", {"model": route.get("model") or client.model}, 6)
                if response.status_code < 400:
                    data = response.json()
                    caps = data.get("capabilities")
                    if isinstance(caps, list):
                        capable = any(str(item).lower() == "vision" for item in caps)
                        cacheable = True
                    else:
                        # Older Ollama versions omit capabilities; use conservative model-family hints.
                        cacheable = True
            except Exception:
                # An unavailable server is not evidence that the model lacks Vision.
                pass
            if cacheable:
                self._vision_capability_cache[key] = (now, capable)
            return capable
        return any(token in model for token in known)

    @contextlib.contextmanager
    def vision_scope(self, route_id=""):
        """Restrict this request and all failovers to routes known to accept images."""
        prefer_token = _PREFER.set(str(route_id or ""))
        vision_token = _VISION_ONLY.set(True)
        try:
            yield self
        finally:
            _VISION_ONLY.reset(vision_token)
            _PREFER.reset(prefer_token)

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
        timeout = route_model.effective_timeout(route, cfg)
        merged = {**cfg, "model": route["model"], "timeout": timeout}
        return cls(merged, name=route["provider"])

    # ---------- health / cooldown bookkeeping ----------
    def _state(self, rid):
        return self.states.setdefault(rid, {"health": "unknown", "last_error": None, "last_ms": None,
                                            "latency_ms": None, "last_ok_at": None,
                                            "last_attempt_at": None, "failures": 0, "last_kind": None})

    def _mark_success(self, route, ms, latency_ms=None):
        st = self._state(route["id"])
        measured = latency_ms if isinstance(latency_ms, (int, float)) and latency_ms >= 0 else ms
        st.update(health="healthy", last_error=None, last_ms=ms, latency_ms=measured,
                  last_ok_at=time.time(), last_attempt_at=time.time(), failures=0, last_kind=None, model_failures=0)
        self.cooldowns.pop(route["id"], None)

    def _google_quota_scope(self, route):
        """Google's rate limits are shared per project and model, not per API key."""
        cfg = self._provider_cfg(route)
        if not route_model.is_google(route.get("provider"), cfg):
            return None
        model = _bare_model_id(route.get("model") or "").strip().casefold()
        project_scope = str(cfg.get("quota_scope") or "").strip().casefold()
        if project_scope:
            return ("google-project-model", project_scope, model)
        return ("google-provider-model", str(route.get("provider") or "").strip().casefold(), model)

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
            cooldown_until = time.monotonic() + cooldown
            self.cooldowns[route["id"]] = cooldown_until
            if kind == "rate" or status == 429:
                quota_scope = self._google_quota_scope(route)
                if quota_scope is not None:
                    # Google quota buckets are project + model scoped. quota_scope
                    # lets separate API entries for the same project share that model bucket.
                    for sibling in self.routes():
                        if self._google_quota_scope(sibling) == quota_scope:
                            self.cooldowns[sibling["id"]] = cooldown_until
        st = self._state(route["id"])
        st["failures"] += 1
        st["last_kind"] = kind
        st["last_attempt_at"] = time.time()
        st["last_error"] = redact(str(exc), *secrets)[:300]
        st["health"] = "down" if kind in ("auth", "model", "request", "missing", "offline") else "degraded"
        # Quota exhaustion and permanent model/configuration errors affect runtime
        # health only. They must never rewrite route.enabled or any other user setting.
        if kind == "model":
            st["model_failures"] = st.get("model_failures", 0) + 1
        else:
            st["model_failures"] = 0
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
    def _execute(self, messages, system_prompt, temperature, stream, on_chunk=None, on_event=None, retry_index=0, cancel_event=None):
        if not self._lock.acquire(blocking=False):
            raise RuntimeError("درخواست قبلی هنوز در حال انجام است؛ درخواست تکراری ارسال نشد.")
        if cancel_event is not None and cancel_event.is_set():
            self._lock.release()
            raise RuntimeError("درخواست لغو شده است.")
        self._cancel.clear()
        trace_token = None
        try:
            started = time.monotonic()
            messages = normalize_messages(messages)
            self.last_attempts = []
            if not messages:
                raise RuntimeError("هیچ پیام کاربری برای ارسال وجود ندارد.")
            metrics = {"request_id": uuid.uuid4().hex[:8], "started_at": datetime.now(timezone.utc).isoformat(),
                       "stream": bool(stream), "retries": int(retry_index), "failovers": 0, "provider": None, "model": None,
                       "route_id": None, "kind": None, "connect_ms": None, "first_token_ms": None, "total_ms": None,
                       "result": None, "chars": 0, "role": _ROLE.get() or None}
            trace_token = set_trace_request_id(metrics["request_id"])
            candidates = self._candidates()
            request_trace("request_start", stream=bool(stream), retry_index=int(retry_index), role=_ROLE.get() or "chat",
                          candidates=len(candidates), network_policy=self.settings.get("network_policy", "cloud_permitted"),
                          route_decisions=self.last_route_decisions)
            failures = []
            emit = on_event or (lambda e: None)
            # Record every skipped cooldown route up front. Cooldown routes are
            # deliberately sorted behind healthy routes, so a successful fallback
            # could otherwise return before their skip was reflected in telemetry.
            cooldown_routes = set()
            # A single logical turn must not retry an identical endpoint/model/
            # credential merely because it is configured as multiple Routes.
            # This avoids apparent model-hopping that only repeats the same backend.
            attempted_route_targets = set()
            for candidate in candidates:
                if self._cancel.is_set() or (cancel_event is not None and cancel_event.is_set()):
                    break
                _, candidate_reason = self.eligibility(candidate)
                if candidate_reason == "cooldown":
                    candidate_id = candidate["id"]
                    cooldown_routes.add(candidate_id)
                    remaining = max(0, int(self.cooldowns.get(candidate_id, 0) - time.monotonic()))
                    failures.append(f"{candidate_id}: در حالت استراحت ({remaining} ثانیه دیگر)")
                    self.last_attempts.append({"provider": candidate["provider"], "route_id": candidate_id,
                                               "result": "cooldown", "cooldown_remaining_seconds": remaining})
            for route in candidates:
                if self._cancel.is_set() or (cancel_event is not None and cancel_event.is_set()):
                    break
                rid = route["id"]
                if rid in cooldown_routes:
                    continue
                ok, reason = self.eligibility(route)
                if reason == "cooldown":
                    remaining = max(0, int(self.cooldowns.get(rid, 0) - time.monotonic()))
                    failures.append(f"{rid}: در حالت استراحت ({remaining} ثانیه دیگر)")
                    self.last_attempts.append({"provider": route["provider"], "route_id": rid, "result": "cooldown",
                                               "cooldown_remaining_seconds": remaining})
                    continue
                if not ok:
                    continue
                info = self.route_info(route)
                route_cfg = self._provider_cfg(route)
                endpoint = str(route_cfg.get("base_url") or route.get("provider") or "").strip().rstrip("/").casefold()
                target_key = (endpoint, str(route.get("model") or "").strip().casefold(),
                              str(route_cfg.get("api_key") or ""))
                if target_key in attempted_route_targets:
                    failures.append(f"{rid}: همین endpoint/model/credential در این درخواست قبلاً امتحان شد؛ تکرار حذف شد.")
                    self.last_attempts.append({"provider": route["provider"], "route_id": rid,
                                               "model": route["model"], "result": "duplicate_target_skipped"})
                    continue
                attempted_route_targets.add(target_key)
                secrets = (route_cfg.get("api_key"),)
                request_trace("route_selected", route_id=rid, provider=route.get("provider"), model=route.get("model"),
                              stream=bool(stream), failover_index=metrics["failovers"],
                              decision=next((d["reason"] for d in self.last_route_decisions if d["route_id"] == rid), "policy_selected"))
                emit({"phase": "connecting" if not failures and metrics["failovers"] == 0 else "failover",
                      "failovers": metrics["failovers"], **info})
                attempt_started = time.monotonic()
                parts, first_at, connect_at = [], None, None
                provider = None
                try:
                    provider = self._make_provider(route)
                    if cancel_event is not None and cancel_event.is_set():
                        break
                    provider.cancel_event = cancel_event
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
                            request_trace("response_headers_received", route_id=rid, provider=route.get("provider"), model=route.get("model"), elapsed_ms=int((time.monotonic()-attempt_started)*1000))
                            emit({"phase": "waiting", "failovers": metrics["failovers"], **info})
                        gen = provider.stream(messages, system_prompt, temperature, on_connect=on_connect)
                        if cancel_event is not None and cancel_event.is_set():
                            gen.close()
                            return self._finish(route, info, parts, metrics, started, attempt_started, connect_at, first_at, provider,
                                                stopped=True, failures=failures)
                        try:
                            for chunk in gen:
                                if not chunk:
                                    continue
                                if first_at is None:
                                    first_at = time.monotonic()
                                    request_trace("first_content_chunk", route_id=rid, provider=route.get("provider"), model=route.get("model"), elapsed_ms=int((first_at-attempt_started)*1000))
                                    emit({"phase": "streaming", "failovers": metrics["failovers"], **info})
                                chunk = guard.feed(chunk)
                                if chunk:
                                    parts.append(chunk)
                                    if on_chunk:
                                        on_chunk(chunk)
                                if self._cancel.is_set() or (cancel_event is not None and cancel_event.is_set()):
                                    break
                            if not self._cancel.is_set() and not (cancel_event is not None and cancel_event.is_set()):
                                tail = guard.finish()
                                if tail:
                                    parts.append(tail)
                                    if on_chunk:
                                        on_chunk(tail)
                        finally:
                            gen.close()                                   # closes the HTTP stream even after Stop
                        if not parts and not self._cancel.is_set() and not (cancel_event is not None and cancel_event.is_set()):
                            raise ProviderError(route["provider"], ("مدل فقط متن تحلیل داخلی برگرداند و چیزی برای نمایش نبود؛ Route بعدی امتحان می‌شود."
                                                                    if guard.leaked else "مدل پاسخ خالی برگرداند."), True, kind="empty")
                except Exception as exc:                                  # noqa: BLE001 - every provider failure is contained here
                    if self._cancel.is_set() or (cancel_event is not None and cancel_event.is_set()):  # Stop: not a failure of the route
                        return self._finish(route, info, parts, metrics, started, attempt_started, connect_at, first_at, provider,
                                            stopped=True, failures=failures)
                    safe = RuntimeError(redact(exc, *secrets)) if not isinstance(exc, (ProviderError, OllamaError)) else exc
                    kind, status, cooldown = self._mark_failure(route, exc, secrets)
                    request_trace("route_failed", route_id=rid, provider=route.get("provider"), model=route.get("model"), error_kind=kind, status_code=status, elapsed_ms=int((time.monotonic()-attempt_started)*1000))
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
                                    stopped=self._cancel.is_set() or (cancel_event is not None and cancel_event.is_set()), failures=failures)
            # nothing worked
            self.last_provider = self.last_model = self.last_route_id = self.last_kind = None
            role = _ROLE.get()
            allowlist = self.settings.get("role_provider_allowlist")
            if not failures:
                if role == "deep" and isinstance(allowlist, dict) and role in allowlist:
                    failures.append("برای استدلال سنگین، Route فعال Google Gemini لازم است؛ هیچ مسیر محلی یا Provider دیگری جایگزین نمی‌شود.")
                elif role == "surface":
                    providers = self.settings.get("providers") or {}
                    ollama_cfg = providers.get("ollama") or {}
                    local_routes = [route for route in self.routes() if route.get("provider") == "ollama"]
                    enabled_local = [route for route in local_routes if route.get("enabled", True)]
                    surface_allowed = allowlist.get("surface") if isinstance(allowlist, dict) else None
                    provider_allowed = (
                        not isinstance(surface_allowed, (list, tuple))
                        or "ollama" in {str(value).strip().lower() for value in surface_allowed}
                    )
                    if not bool(ollama_cfg.get("enabled", True)):
                        failures.append("Provider محلی Ollama خاموش است؛ آن را از تنظیمات Provider فعال کن.")
                    elif not local_routes:
                        failures.append("هیچ مدل Ollama در Routeها ثبت نشده است؛ مدل‌های نصب‌شده را اسکن کن.")
                    elif not enabled_local:
                        cloud_ready = any(
                            route_model.provider_kind(route.get("provider"), (providers.get(route.get("provider")) or {})) == "cloud"
                            and self.eligibility(route)[0]
                            for route in self.routes()
                        )
                        failures.append(
                            "مدل محلی خاموش است و هیچ Route ابریِ فعال و معتبری برای جایگزینی وجود ندارد؛ یک Provider ابری را همراه با حداقل یک Route و کلید معتبر فعال کن."
                            if not cloud_ready else
                            "هیچ Route ابریِ آماده‌ای برای مکالمه پیدا نشد؛ تنظیمات Provider را بررسی کن."
                        )
                    elif not provider_allowed:
                        failures.append("سیاست نقش مکالمهٔ عادی Provider محلی Ollama را مجاز نکرده است؛ role_provider_allowlist را بررسی کن.")
                    else:
                        failures.append("هیچ Route محلیِ مجاز و آماده‌ای برای مکالمه پیدا نشد؛ وضعیت اتصال Ollama و سلامت مدل را بررسی کن.")
            self.last_error = "; ".join(failures) or "هیچ Route فعالی تنظیم نشده است."
            self.last_duration_ms = int((time.monotonic() - started) * 1000)
            if self._cancel.is_set() or (cancel_event is not None and cancel_event.is_set()):
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
            request_trace("request_end", duration_ms=int((time.monotonic()-started)*1000) if "started" in locals() else None)
            if trace_token is not None:
                reset_trace_request_id(trace_token)
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
            ping_ms = ((connect_at - attempt_started) * 1000 if connect_at else
                       (first_at - attempt_started) * 1000 if first_at else (now - attempt_started) * 1000)
            self._mark_success(route, int((now - attempt_started) * 1000), max(0, int(ping_ms)))
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
        request_trace("request_completed", provider=route["provider"], model=model, route_id=route["id"], result=metrics["result"], total_ms=self.last_duration_ms, connect_ms=metrics.get("connect_ms"), first_token_ms=metrics.get("first_token_ms"), response_chars=len(text))
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

    def chat_stream(self, messages, system_prompt, temperature=0.7, on_chunk=None, on_event=None, retry_index=0, cancel_event=None):
        """Streamed answer. on_chunk(text) gets each piece; on_event(dict) gets phase changes
        (connecting / waiting / streaming / failover) with the REAL route taken from the router.
        An optional external Event lets background workers cancel before or during provider startup.

        Failover happens only before the first token. Once text has arrived it is never repeated: a connection that dies
        later ends the answer as 'interrupted' (result["interrupted"] holds the reason). Returns the result dict."""
        return self._execute(messages, system_prompt, temperature, True, on_chunk, on_event, retry_index, cancel_event)

    # ---------- native function calling ----------
    def chat_with_tools(self, messages, system_prompt, temperature=0.4, tools=None, on_event=None):
        """Try one eligible OpenAI-compatible route with native JSON-schema tools; return None if no route supports it."""
        if not tools:
            return None
        if not self._lock.acquire(blocking=False):
            raise RuntimeError("درخواست قبلی هنوز در حال انجام است؛ درخواست تکراری ارسال نشد.")
        self._cancel.clear()
        self.last_attempts = []
        started = time.monotonic()
        started_at = datetime.now(timezone.utc).isoformat()
        request_id = uuid.uuid4().hex[:8]
        failures = []
        last_provider = None
        last_route_info = None
        emit = on_event or (lambda event: None)
        try:
            for route in self._candidates():
                provider = None
                if self._cancel.is_set():
                    return {"text": "", "tool_calls": [], "stopped": True, "interrupted": None}
                ok, reason = self.eligibility(route)
                if not ok:
                    continue
                info = self.route_info(route)
                try:
                    provider = self._make_provider(route)
                    native = getattr(provider, "chat_with_tools", None)
                    if not callable(native):
                        continue
                    emit({"phase": "connecting", **info})
                    self._active = provider
                    result = native(messages, system_prompt, temperature, tools)
                    if result is None:                         # this model/provider explicitly lacks native tool support
                        self._active = None
                        continue
                    elapsed = int((time.monotonic() - started) * 1000)
                    self._mark_success(route, elapsed)
                    active_model = getattr(provider, "active_model", None)
                    model = active_model if isinstance(active_model, str) and active_model else route["model"]
                    self.last_provider, self.last_model, self.last_route_id = route["provider"], model, route["id"]
                    self.last_kind, self.last_error, self.last_duration_ms = info["kind"], None, elapsed
                    metrics = {"request_id": request_id, "started_at": started_at,
                               "stream": False, "retries": 0, "failovers": len(failures), "provider": route["provider"],
                               "model": model, "route_id": route["id"], "kind": info["kind"],
                               "total_ms": elapsed, "result": "tool_call" if result.get("tool_calls") else "success",
                               "chars": len(result.get("text") or ""), "role": _ROLE.get() or None}
                    self.last_metrics = metrics
                    self.metrics.append(metrics)
                    self.last_attempts.append({
                        "provider": route["provider"],
                        "route_id": route["id"],
                        "model": model,
                        "result": metrics["result"],
                        "duration_ms": elapsed,
                    })
                    stats = getattr(provider, "last_stats", None)
                    stats = stats if isinstance(stats, dict) else None
                    if stats:
                        metrics.update(
                            load_ms=stats.get("load_ms"),
                            eval_tokens=stats.get("eval_tokens"),
                            eval_ms=stats.get("eval_ms"),
                        )
                    # Native function-calling requests are real provider requests too.
                    # Record reported token usage and metadata just like the streaming path.
                    self._ledger(metrics, metrics["result"], provider, stats)
                    self._write_telemetry({
                        "provider": route["provider"],
                        "model": model,
                        "result": metrics["result"],
                        "duration_ms": elapsed,
                        "attempts": self.last_attempts,
                        **{key: metrics.get(key) for key in (
                            "request_id", "route_id", "kind", "stream", "connect_ms",
                            "first_token_ms", "total_ms", "retries", "failovers", "role",
                            "load_ms", "eval_tokens", "eval_ms",
                        )},
                    })
                    return {**result, "provider": route["provider"], "model": model, "route_id": route["id"],
                            "kind": info["kind"], "label": info["label"], "metrics": metrics,
                            "stopped": False, "interrupted": None}
                except Exception as exc:                              # noqa: BLE001
                    if self._cancel.is_set():
                        return {"text": "", "tool_calls": [], "stopped": True, "interrupted": None}
                    last_provider = provider
                    last_route_info = {**self.route_info(route), "route": route}
                    secrets = (self._provider_cfg(route).get("api_key"),)
                    kind, status, _cooldown = self._mark_failure(route, exc, secrets)
                    failures.append(f"{route['id']}: {redact(exc, *secrets)}")
                    self.last_attempts.append({"provider": route["provider"], "route_id": route["id"],
                                               "result": "error", "error_kind": kind, "status_code": status})
            if failures:
                elapsed = int((time.monotonic() - started) * 1000)
                route_info = last_route_info or {}
                route = route_info.get("route") or {}
                metrics = {
                    "request_id": request_id,
                    "started_at": started_at,
                    "stream": False,
                    "retries": 0,
                    "failovers": max(0, len(failures) - 1),
                    "provider": route.get("provider"),
                    "model": route.get("model"),
                    "route_id": route.get("id"),
                    "kind": route_info.get("kind"),
                    "total_ms": elapsed,
                    "result": "failed",
                    "chars": 0,
                    "role": _ROLE.get() or None,
                }
                self.last_provider = metrics["provider"]
                self.last_model = metrics["model"]
                self.last_route_id = metrics["route_id"]
                self.last_kind = metrics["kind"]
                self.last_error = "\n".join(failures)
                self.last_duration_ms = elapsed
                self.last_metrics = metrics
                self.metrics.append(metrics)
                stats = getattr(last_provider, "last_stats", None)
                stats = stats if isinstance(stats, dict) else None
                if stats:
                    metrics.update(
                        load_ms=stats.get("load_ms"),
                        eval_tokens=stats.get("eval_tokens"),
                        eval_ms=stats.get("eval_ms"),
                    )
                self._ledger(metrics, "failed", last_provider, stats)
                self._write_telemetry({
                    "provider": metrics["provider"],
                    "model": metrics["model"],
                    "result": "failed",
                    "duration_ms": elapsed,
                    "attempts": self.last_attempts,
                    "request_id": request_id,
                    "route_id": metrics["route_id"],
                    "kind": metrics["kind"],
                    "stream": False,
                    "failovers": metrics["failovers"],
                    "retries": 0,
                    "role": metrics["role"],
                    "load_ms": metrics.get("load_ms"),
                    "eval_tokens": metrics.get("eval_tokens"),
                    "eval_ms": metrics.get("eval_ms"),
                })
                raise RuntimeError("همه‌ی Routeهای سازگار با Native Function Calling ناموفق بودند:\n" + "\n".join(failures))
            return None
        finally:
            self._active = None
            self._lock.release()

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
                # Route tests must get the same total response budget as real chat.
                # This matters for Gemini thinking models such as Hydrogen.
                test_timeout = max(1, int(route_model.effective_timeout(route, cfg) or 15))
                merged = {
                    **cfg,
                    "model": route["model"],
                    "timeout": test_timeout,
                }
                ok, msg = probe_provider(
                    route["provider"], merged, timeout=test_timeout
                )
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
                    ping = row.get("connect_ms")
                    if ping is None:
                        ping = row.get("first_token_ms")
                    self._mark_success(route, row["total_ms"], ping)
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
