"""Reverse API provider: a standard ChatProvider that delegates the wire work to a registered transport.

It reuses everything the router already gives every provider (persona/system prompt, memory, history,
routing, failover, cooldowns, streaming, cancellation, metrics). Tool use goes through Kira's shared tool
path: the provider deliberately has no ``chat_with_tools``, so the router skips it for native function calling.
"""
from __future__ import annotations

import threading
from collections.abc import Callable, Iterable
from typing import Any

from ..core.interfaces.reverse_transport import (
    ReverseRequest,
    ReverseTransportError,
    TransportState,
    TransportStatus,
)
from ..hybrid_providers import BaseProvider, ProviderError, normalize_messages, redact
from ..think_filter import ThinkFilter
from .prompt import build_prompt
from .registry import TRANSPORTS, TransportRegistry

_SENSITIVE_KEY_PARTS = ("key", "token", "cookie", "session", "secret", "password", "authorization")


class ReverseApiProvider(BaseProvider):
    name = "reverse_api"
    needs_key = False                       # authentication is a session owned by the transport, not an API key
    supports_probe = True                   # probe_provider() asks status() instead of calling /models
    auth_hint = "نشست Reverse API برقرار نیست یا منقضی شده است"

    def __init__(self, config: dict[str, Any], name: str | None = None, registry: TransportRegistry | None = None):
        super().__init__(config, name)
        self.needs_key = False
        self._registry = registry or TRANSPORTS
        self._transport = None
        self._abort_event = threading.Event()

    # ---- configuration / secrets ----
    def _transport_id(self) -> str:
        return str(self.config.get("transport") or "").strip().lower()

    def _sensitive_values(self) -> list[str]:
        values = []
        for key, value in self.config.items():
            if isinstance(value, str) and len(value) >= 6 and any(part in str(key).lower() for part in _SENSITIVE_KEY_PARTS):
                values.append(value)
        return values

    def _fail(self, message, retryable, status=None, kind="error", retry_after=None):
        return ProviderError(self.name, redact(message, self.secret, *self._sensitive_values()), retryable, status, kind, retry_after)

    def enabled(self) -> bool:
        return bool(self.config.get("enabled", False)) and self._registry.resolve(self._transport_id()) is not None

    # ---- transport access ----
    def _resolve_transport(self):
        if self._transport is not None:
            return self._transport
        transport_id = self._transport_id()
        if not transport_id:
            raise self._fail("نوع انتقال (transport) برای Reverse API تنظیم نشده است.", False, kind="request")
        factory = self._registry.resolve(transport_id)
        if factory is None:
            raise self._fail(f"انتقال Reverse API با شناسه‌ی «{transport_id}» ثبت نشده است.", False, kind="missing")
        try:
            self._transport = factory(dict(self.config))
        except ProviderError:
            raise
        except Exception as exc:                                       # noqa: BLE001 - classified and redacted
            raise self._fail(f"ساخت انتقال Reverse API ناموفق بود: {exc}", False, kind="request") from exc
        return self._transport

    def _status(self, transport) -> TransportStatus:
        try:
            status = transport.status()
        except Exception as exc:                                       # noqa: BLE001
            raise self._fail(f"خواندن وضعیت اتصال Reverse API ناموفق بود: {exc}", True, kind="network") from exc
        if not isinstance(status, TransportStatus):
            raise self._fail("وضعیت اتصال Reverse API معتبر نیست.", False, kind="response")
        return status

    def _require_connected(self, status: TransportStatus) -> None:
        detail = f" ({status.detail})" if status.detail else ""
        if status.state is TransportState.CONNECTED:
            return
        if status.state is TransportState.CONNECTING:
            raise self._fail("اتصال Reverse API هنوز در حال برقراری است" + detail + ".", True, kind="network")
        if status.state is TransportState.DISCONNECTED:
            raise self._fail("Reverse API متصل نیست؛ ابتدا نشست را برقرار کن" + detail + ".", False, kind="auth")
        if status.state is TransportState.UNAVAILABLE:
            raise self._fail("انتقال Reverse API روی این سیستم در دسترس نیست" + detail + ".", False, kind="missing")
        raise self._fail("اتصال Reverse API دچار خطا شده است" + detail + ".", True, kind="network")

    # ---- request assembly ----
    def _request(self, messages, system_prompt, temperature, max_tokens=None):
        clean = normalize_messages(messages, preserve_tool_messages=True)
        if not clean:
            raise self._fail("هیچ پیام کاربری برای ارسال وجود ندارد.", False, kind="request")
        transport = self._resolve_transport()
        status = self._status(transport)
        self._require_connected(status)
        if any(item.get("images") for item in clean) and not status.supports_images:
            raise self._fail("این انتقال Reverse API تصویر را پشتیبانی نمی‌کند.", False, kind="request")
        self._abort_event.clear()
        request = ReverseRequest(
            prompt=build_prompt(clean, system_prompt),
            system_prompt=str(system_prompt or ""),
            messages=tuple(dict(item) for item in clean),
            model=self.model,
            temperature=float(temperature),
            max_tokens=int(max_tokens) if max_tokens else None,
        )
        return transport, request

    # ---- cancellation ----
    def _cancelled(self) -> bool:
        external = getattr(self, "cancel_event", None)
        return self._abort_event.is_set() or (external is not None and external.is_set())

    def abort(self) -> None:
        """Stop the running request from another thread (Stop button)."""
        self._abort_event.set()
        transport = self._transport
        if transport is not None:
            try:
                transport.abort()
            except Exception:                                          # noqa: BLE001 - Stop must never raise
                pass
        super().abort()

    # ---- ChatProvider contract ----
    def stream(self, messages, system_prompt, temperature=0.7, on_connect: Callable[[], None] | None = None,
               max_tokens=None) -> Iterable[str]:
        transport, request = self._request(messages, system_prompt, temperature, max_tokens)
        return self._iterate(transport, request, on_connect)

    def _iterate(self, transport, request, on_connect):
        source = None
        connected = False
        think = ThinkFilter()
        try:
            source = transport.stream(request, self._abort_event)
            for piece in source:
                if self._cancelled():
                    self.abort()
                    break
                if not connected:
                    connected = True
                    if on_connect:
                        on_connect()
                text = think.feed(str(piece or ""))
                if text:
                    yield text
            if not self._cancelled():
                tail = think.flush()
                if tail:
                    yield tail
        except ProviderError:
            raise
        except ReverseTransportError as exc:
            if self._cancelled():
                return
            raise self._fail(str(exc), exc.retryable, kind=exc.kind) from exc
        except Exception as exc:                                       # noqa: BLE001 - classified and redacted
            if self._cancelled():
                return
            raise self._fail(f"خطای Reverse API ({type(exc).__name__}): {exc}", True, kind="server") from exc
        finally:
            close = getattr(source, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:                                      # noqa: BLE001
                    pass

    def chat(self, messages, system_prompt, temperature=0.7) -> str:
        text = "".join(self.stream(messages, system_prompt, temperature)).strip()
        if not text:
            raise self._fail("مدل پاسخ خالی برگرداند.", True, kind="empty")
        return text

    # ---- connection test (no generation request is sent) ----
    def probe(self) -> tuple[bool, str]:
        try:
            status = self._status(self._resolve_transport())
        except ProviderError as exc:
            return False, str(exc)[:400]
        detail = f" ({status.detail})" if status.detail else ""
        if status.state is TransportState.CONNECTED:
            return True, "نشست Reverse API متصل است" + detail + "."
        return False, redact(f"Reverse API آماده نیست: {status.state.value}{detail}", *self._sensitive_values())[:400]
