"""Headless Playwright transport for the DeepSeek web chat."""
from __future__ import annotations

import json
import threading
import time
from collections.abc import Iterable
from typing import Any

from ..core.interfaces.reverse_transport import (
    ReverseRequest, ReverseTransportError, TransportState, TransportStatus,
)
from .deepseek_session import DeepSeekSessionError, DeepSeekSessionStore

_COMPOSER_SELECTORS = (
    "textarea",
    '[contenteditable="true"]',
    '[role="textbox"]',
)
_RESPONSE_SCRIPT = """() => {
  const selectors = [".ds-markdown", "[class*='markdown']", "[data-testid*='message']"];
  const values = [];
  for (const selector of selectors) {
    for (const node of document.querySelectorAll(selector)) {
      const style = getComputedStyle(node);
      if (style.display === "none" || style.visibility === "hidden") continue;
      const value = (node.innerText || node.textContent || "").trim();
      if (value && !values.includes(value)) values.push(value);
    }
    if (values.length) break;
  }
  return values;
}"""
_GENERATING_SCRIPT = """() => {
  const selectors = [
    'button[aria-label*= "Stop"]', 'button[aria-label*= "stop"]',
    'button[title*= "Stop"]', 'button[title*= "stop"]',
    '[data-testid*= "stop"]', 'button[class*= "stop"]'
  ];
  return selectors.some(selector => [...document.querySelectorAll(selector)].some(node => {
    const style = getComputedStyle(node);
    return style.display !== "none" && style.visibility !== "hidden" && !node.disabled;
  }));
}"""


class DeepSeekBrowserTransport:
    """One-request-at-a-time headless browser transport backed by the encrypted login session."""

    def __init__(self, config: dict[str, Any] | None = None, store: DeepSeekSessionStore | None = None):
        self.config = dict(config or {})
        self.store = store or DeepSeekSessionStore()
        self._lock = threading.Lock()
        self._cancel = threading.Event()
        self._active_page = None
        self._last_error = ""

    def status(self) -> TransportStatus:
        try:
            state = self.store.load()
        except DeepSeekSessionError as exc:
            return TransportStatus(TransportState.ERROR, str(exc)[:180])
        if state is None:
            return TransportStatus(TransportState.DISCONNECTED, "ابتدا از تنظیمات Providerها وارد DeepSeek شو.")
        try:
            import playwright.sync_api  # noqa: F401
        except ImportError:
            return TransportStatus(TransportState.UNAVAILABLE, "Playwright نصب نیست؛ وابستگی‌های Kira را نصب کن.")
        return TransportStatus(TransportState.CONNECTED, "نشست رمزگذاری‌شده آماده است.", False)

    def abort(self) -> None:
        self._cancel.set()

    @staticmethod
    def _composer(page):
        for selector in _COMPOSER_SELECTORS:
            locator = page.locator(selector)
            for index in range(locator.count() - 1, -1, -1):
                candidate = locator.nth(index)
                try:
                    if candidate.is_visible() and candidate.is_enabled():
                        return candidate
                except Exception:
                    continue
        return None

    @staticmethod
    def _session_init_script(state: dict[str, Any]) -> str:
        entries = state.get("sessionStorageByOrigin") or {}
        payload = json.dumps(entries, ensure_ascii=False)
        return (
            "(() => { const all = " + payload + "; const entries = all[location.origin];"
            " if (entries) for (const item of entries) { try { sessionStorage.setItem(item.name, item.value); } catch (_) {} }"
            " })();"
        )

    def stream(self, request: ReverseRequest, cancel: threading.Event) -> Iterable[str]:
        if not self._lock.acquire(blocking=False):
            raise ReverseTransportError("درخواست دیگری از طریق نشست DeepSeek در حال اجراست.", kind="rate", retryable=True)
        self._cancel.clear()
        browser = context = page = None
        try:
            try:
                from playwright.sync_api import sync_playwright
            except ImportError as exc:
                raise ReverseTransportError("Playwright نصب نیست.", kind="missing", retryable=False) from exc
            try:
                state = self.store.load()
            except DeepSeekSessionError as exc:
                raise ReverseTransportError(str(exc), kind="auth", retryable=False) from exc
            if not state:
                raise ReverseTransportError("نشست DeepSeek ذخیره نشده است؛ ابتدا وارد حساب شو.", kind="auth", retryable=False)
            timeout_ms = max(15_000, int(float(self.config.get("timeout", 90)) * 1000))
            with sync_playwright() as playwright:
                try:
                    try:
                        browser = playwright.chromium.launch(channel="chrome", headless=True)
                    except Exception:
                        browser = playwright.chromium.launch(headless=True)
                except Exception as exc:
                    raise ReverseTransportError("مرورگر Headless قابل اجرا نیست؛ Chromium مربوط به Playwright را نصب کن.", kind="missing", retryable=False) from exc
                context = browser.new_context(storage_state={"cookies": state.get("cookies", []), "origins": state.get("origins", [])})
                context.add_init_script(self._session_init_script(state))
                page = context.new_page()
                self._active_page = page
                page.set_default_timeout(min(timeout_ms, 20_000))
                try:
                    page.goto("https://chat.deepseek.com/", wait_until="domcontentloaded", timeout=timeout_ms)
                    composer = page.wait_for_function(
                        """selectors => selectors.some(selector => [...document.querySelectorAll(selector)].some(node => {
                            const s = getComputedStyle(node); return s.display !== "none" && s.visibility !== "hidden";
                        }))""",
                        arg=list(_COMPOSER_SELECTORS), timeout=timeout_ms,
                    )
                except Exception as exc:
                    raise ReverseTransportError("نشست DeepSeek معتبر نیست یا صفحه چت بارگذاری نشد؛ دوباره وارد حساب شو.", kind="auth", retryable=False) from exc
                if cancel.is_set() or self._cancel.is_set():
                    return
                before = page.evaluate(_RESPONSE_SCRIPT)
                composer = self._composer(page)
                if composer is None:
                    raise ReverseTransportError("کادر پیام DeepSeek پیدا نشد؛ ساختار صفحه تغییر کرده است.", kind="response", retryable=False)
                composer.fill(request.prompt)
                composer.press("Enter")
                deadline = time.monotonic() + timeout_ms / 1000
                previous = ""
                stable = 0
                started = False
                while time.monotonic() < deadline:
                    if cancel.is_set() or self._cancel.is_set():
                        return
                    texts = page.evaluate(_RESPONSE_SCRIPT)
                    current = texts[-1] if texts else ""
                    if texts and (len(texts) > len(before) or current not in before):
                        started = True
                    if started and current:
                        if current.startswith(previous):
                            delta = current[len(previous):]
                        else:
                            delta = current
                        if delta:
                            yield delta
                        if current == previous:
                            stable += 1
                        else:
                            stable = 0
                        previous = current
                    generating = page.evaluate(_GENERATING_SCRIPT)
                    if started and not generating and stable >= 3:
                        break
                    page.wait_for_timeout(250)
                if not started or not previous.strip():
                    raise ReverseTransportError("DeepSeek در مهلت تعیین‌شده پاسخی برنگرداند.", kind="timeout", retryable=True)
                if time.monotonic() >= deadline:
                    raise ReverseTransportError("مهلت دریافت پاسخ DeepSeek تمام شد.", kind="timeout", retryable=True)
        except ReverseTransportError:
            raise
        except Exception as exc:
            if cancel.is_set() or self._cancel.is_set():
                return
            raise ReverseTransportError("خطای مرورگر DeepSeek: " + str(exc)[:240], kind="network", retryable=True) from exc
        finally:
            self._active_page = None
            try:
                if context is not None:
                    context.close()
            except Exception:
                pass
            try:
                if browser is not None:
                    browser.close()
            except Exception:
                pass
            self._lock.release()


__all__ = ["DeepSeekBrowserTransport"]