"""Headless Playwright transport for the DeepSeek web chat."""
from __future__ import annotations

import json
import subprocess
import sys
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
_GENERATION_STATE_SCRIPT = """() => {
  const selectors = [
    'button[aria-label*="stop" i]', 'button[title*="stop" i]',
    '[data-testid*="stop" i]', 'button[class*="stop" i]',
    '[aria-label*="停止"]', '[title*="停止"]',
    '[aria-label*="توقف"]', '[title*="توقف"]'
  ];
  const stopVisible = selectors.some(selector =>
    [...document.querySelectorAll(selector)].some(node => {
      const style = getComputedStyle(node);
      return style.display !== "none" && style.visibility !== "hidden" &&
        node.getAttribute("aria-hidden") !== "true" && !node.disabled;
    })
  );
  const composer = [...document.querySelectorAll('textarea, [contenteditable="true"], [role="textbox"]')]
    .find(node => {
      const style = getComputedStyle(node);
      return style.display !== "none" && style.visibility !== "hidden";
    });
  return { stopVisible, composerDisabled: !composer || composer.disabled ||
    composer.getAttribute("aria-disabled") === "true" };
}"""

# Keep a rolling tail uncommitted so transient markdown/code-block re-renders
# do not resend the entire cumulative response.
_STREAM_HOLDBACK_CHARS = 512
_NO_STOP_IDLE_SECONDS = 5.0
_STOP_IDLE_SECONDS = 2.5


class DeepSeekBrowserTransport:
    """One-request-at-a-time headless browser transport backed by the encrypted login session."""

    def __init__(self, config: dict[str, Any] | None = None, store: DeepSeekSessionStore | None = None):
        self.config = dict(config or {})
        self.store = store or DeepSeekSessionStore()
        self._lock = threading.Lock()
        self._cancel = threading.Event()
        self._active_page = None
        self._last_error = ""

    def configure(self, config: dict[str, Any] | None = None):
        """Refresh per-route options while retaining the shared session and request lock."""
        self.config = dict(config or {})
        return self

    def _timeout_ms(self) -> int:
        """Convert the active Route timeout to milliseconds without overriding short user values."""
        try:
            seconds = float(self.config.get("timeout", 90))
        except (TypeError, ValueError):
            seconds = 90.0
        return max(1_000, int(seconds * 1000))

    @staticmethod
    def _common_prefix_length(left: str, right: str) -> int:
        limit = min(len(left), len(right))
        index = 0
        while index < limit and left[index] == right[index]:
            index += 1
        return index

    @staticmethod
    def _stable_stream_delta(previous: str, current: str, emitted_prefix: str) -> tuple[str, str]:
        """Return only newly stable text, keeping a mutable tail out of the append-only stream."""
        if not previous:
            return "", emitted_prefix
        stable_prefix = DeepSeekBrowserTransport._common_prefix_length(previous, current)
        safe_length = max(0, min(stable_prefix, len(current) - _STREAM_HOLDBACK_CHARS))
        if current.startswith(emitted_prefix) and safe_length > len(emitted_prefix):
            next_prefix = current[:safe_length]
            return current[len(emitted_prefix):safe_length], next_prefix
        return "", emitted_prefix

    @staticmethod
    def _merge_session_storage(state: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, Any]:
        """Merge the current origin's sessionStorage into Playwright's refreshed storage state."""
        updated = dict(state)
        by_origin = dict(state.get("sessionStorageByOrigin") or {})
        origin = snapshot.get("origin")
        entries = snapshot.get("entries") or []
        if origin:
            if entries:
                by_origin[origin] = entries
            else:
                by_origin.pop(origin, None)
        if by_origin:
            updated["sessionStorageByOrigin"] = by_origin
        else:
            updated.pop("sessionStorageByOrigin", None)
        return updated

    def _persist_refreshed_session(self, context, page) -> None:
        """Persist rotated cookies/local storage and current-origin sessionStorage after a reply."""
        refreshed = context.storage_state()
        snapshot = page.evaluate(
            """() => ({origin: location.origin, entries: Object.entries(sessionStorage)
                .map(([name, value]) => ({name, value}))})"""
        )
        self.store.save(self._merge_session_storage(refreshed, snapshot))

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
        # Do not clear a cancellation requested immediately before stream() starts.
        browser = context = page = None
        try:
            if cancel.is_set() or self._cancel.is_set():
                return
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
            timeout_ms = self._timeout_ms()
            with sync_playwright() as playwright:
                try:
                    try:
                        browser = playwright.chromium.launch(channel="chrome", headless=True)
                    except Exception:
                        try:
                            browser = playwright.chromium.launch(headless=True)
                        except Exception:
                            install = subprocess.run(
                                [sys.executable, "-m", "playwright", "install", "chromium"],
                                capture_output=True, text=True, timeout=240, check=False,
                            )
                            if install.returncode != 0:
                                raise RuntimeError((install.stderr or install.stdout or "Chromium install failed")[-500:])
                            browser = playwright.chromium.launch(headless=True)
                except Exception as exc:
                    raise ReverseTransportError("مرورگر Headless DeepSeek اجرا نشد: " + str(exc)[:300], kind="missing", retryable=False) from exc
                context = browser.new_context(storage_state={"cookies": state.get("cookies", []), "origins": state.get("origins", [])})
                context.add_init_script(self._session_init_script(state))
                page = context.new_page()
                self._active_page = page
                page.set_default_timeout(min(timeout_ms, 20_000))
                page.set_default_navigation_timeout(min(timeout_ms, 30_000))
                try:
                    if cancel.is_set() or self._cancel.is_set():
                        return
                    page.goto("https://chat.deepseek.com/", wait_until="domcontentloaded", timeout=min(timeout_ms, 30_000))
                    if cancel.is_set() or self._cancel.is_set():
                        return
                    page.wait_for_function(
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
                previous_snapshot = ""
                emitted_prefix = ""
                latest_text = ""
                last_change = time.monotonic()
                started = False
                saw_stop = False
                while time.monotonic() < deadline:
                    if cancel.is_set() or self._cancel.is_set():
                        return
                    texts = page.evaluate(_RESPONSE_SCRIPT)
                    current = texts[-1] if texts else ""
                    if texts and (len(texts) > len(before) or current not in before):
                        started = True
                    now = time.monotonic()
                    if started and current:
                        latest_text = current
                        if current != previous_snapshot:
                            last_change = now
                        delta, next_prefix = self._stable_stream_delta(
                            previous_snapshot, current, emitted_prefix
                        )
                        if delta:
                            yield delta
                        emitted_prefix = next_prefix
                        previous_snapshot = current

                    try:
                        generation = page.evaluate(_GENERATION_STATE_SCRIPT)
                    except Exception:
                        if started and latest_text.strip():
                            break
                        raise
                    stop_visible = bool(generation.get("stopVisible")) if isinstance(generation, dict) else bool(generation)
                    composer_disabled = bool(generation.get("composerDisabled")) if isinstance(generation, dict) else False
                    idle_for = now - last_change
                    if stop_visible:
                        saw_stop = True
                    elif started and not composer_disabled:
                        idle_limit = _STOP_IDLE_SECONDS if saw_stop else _NO_STOP_IDLE_SECONDS
                        if idle_for >= idle_limit:
                            break
                    page.wait_for_timeout(250)

                if not started or not latest_text.strip():
                    raise ReverseTransportError("DeepSeek در مهلت تعیین‌شده پاسخی برنگرداند.", kind="timeout", retryable=True)

                # A timed-out partial response is still a usable partial result. Do not
                # raise after yielding it: the router would otherwise trigger failover
                # and append a second answer to the already streamed text.
                try:
                    self._persist_refreshed_session(context, page)
                except Exception as exc:
                    self._last_error = "ذخیره نشست تازه‌شده ناموفق بود: " + str(exc)[:180]

                if latest_text.startswith(emitted_prefix):
                    tail = latest_text[len(emitted_prefix):]
                    if tail:
                        yield tail
                elif not emitted_prefix:
                    yield latest_text
                # If the deadline elapsed after content arrived, return the partial
                # answer as a completed transport result rather than raising timeout.
                return
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
            # Clear only after this request has completely unwound. A stop arriving
            # before stream() starts is therefore observed instead of erased.
            self._cancel.clear()
            self._lock.release()


__all__ = ["DeepSeekBrowserTransport"]