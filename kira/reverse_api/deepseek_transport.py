"""Headless Playwright transport for the DeepSeek web chat."""
from __future__ import annotations

import atexit
import json
import queue
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
# Keep a rolling tail uncommitted so transient markdown/code-block re-renders
# do not resend the entire cumulative response.
_STREAM_HOLDBACK_CHARS = 96
_NO_STOP_IDLE_SECONDS = 1.5
_COMPLETION_GRACE_SECONDS = 0.35

_POLL_SCRIPT = """() => {
  const textSelectors = [".ds-markdown", "[class*='markdown']", "[data-testid*='message']"];
  const values = [];
  for (const selector of textSelectors) {
    for (const node of document.querySelectorAll(selector)) {
      const style = getComputedStyle(node);
      if (style.display === "none" || style.visibility === "hidden") continue;
      const value = (node.innerText || node.textContent || "").trim();
      if (value && !values.includes(value)) values.push(value);
    }
    if (values.length) break;
  }
  const stopSelectors = [
    'button[aria-label*="stop" i]', 'button[title*="stop" i]',
    '[data-testid*="stop" i]', 'button[class*="stop" i]',
    '[aria-label*="停止"]', '[title*="停止"]',
    '[aria-label*="توقف"]', '[title*="توقف"]'
  ];
  const stopVisible = stopSelectors.some(selector =>
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
  return {
    values,
    stopVisible,
    composerPresent: !!composer,
    composerDisabled: !!composer && (composer.disabled ||
      composer.getAttribute("aria-disabled") === "true")
  };
}"""


class _DeepSeekBrowserJob:
    def __init__(self, request: ReverseRequest) -> None:
        self.request = request
        self.cancel = threading.Event()
        self.events = queue.Queue()


class _DeepSeekBrowserWorker:
    """Own Playwright and one warm browser on a dedicated thread.

    Playwright's synchronous objects are thread-affine. A dedicated owner thread
    lets successive Kira request threads reuse Chromium without cross-thread access.
    """

    def __init__(self, transport) -> None:
        self.transport = transport
        self.jobs = queue.Queue()
        self.ready = threading.Event()
        self.startup_error = None
        self._thread = threading.Thread(
            target=self._run,
            name="Kira-DeepSeek-Browser",
            daemon=True,
        )
        self._thread.start()
        if not self.ready.wait(35):
            self.shutdown()
            raise ReverseTransportError(
                "راه‌اندازی مرورگر DeepSeek بیش از حد طول کشید.",
                kind="timeout",
                retryable=True,
            )
        if self.startup_error is not None:
            error = self.startup_error
            self.shutdown()
            raise ReverseTransportError(
                "مرورگر DeepSeek اجرا نشد: " + str(error)[:220],
                kind="missing",
                retryable=False,
            ) from error

    def is_alive(self) -> bool:
        return self._thread.is_alive()

    def submit(self, job) -> None:
        if not self.is_alive():
            raise ReverseTransportError(
                "مرورگر دائمی DeepSeek در دسترس نیست.",
                kind="network",
                retryable=True,
            )
        self.jobs.put(job)

    @staticmethod
    def _launch(playwright):
        errors = []
        for options in (
            {"channel": "chrome", "headless": True},
            {"headless": True},
        ):
            try:
                return playwright.chromium.launch(**options)
            except Exception as exc:  # noqa: BLE001 - try bundled Chromium after installed Chrome
                errors.append(str(exc)[:180])
        raise RuntimeError("؛ ".join(errors))

    def _run(self) -> None:
        try:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as playwright:
                browser = None
                try:
                    browser = self._launch(playwright)
                    self.ready.set()
                    while True:
                        job = self.jobs.get()
                        if job is None:
                            break
                        try:
                            if not job.cancel.is_set():
                                if browser is None or not browser.is_connected():
                                    browser = self._launch(playwright)
                                self.transport._execute_job(browser, job)
                        except Exception as exc:  # noqa: BLE001 - deliver failures to this request only
                            job.events.put(("error", exc))
                        finally:
                            job.events.put(("done", None))
                finally:
                    if browser is not None:
                        try:
                            browser.close()
                        except Exception:
                            pass
        except Exception as exc:  # noqa: BLE001 - unblock waiters if startup or loop fails
            self.startup_error = exc
            self.ready.set()
            while True:
                try:
                    job = self.jobs.get_nowait()
                except queue.Empty:
                    break
                if job is not None:
                    job.events.put(("error", exc))
                    job.events.put(("done", None))

    def shutdown(self) -> None:
        if self._thread.is_alive():
            self.jobs.put(None)
            self._thread.join(timeout=6)


class DeepSeekBrowserTransport:
    """One-request-at-a-time headless browser transport backed by the encrypted login session."""

    def __init__(self, config: dict[str, Any] | None = None, store: DeepSeekSessionStore | None = None):
        self.config = dict(config or {})
        self.store = store or DeepSeekSessionStore()
        self._lock = threading.Lock()
        self._cancel = threading.Event()
        self._active_page = None
        self._active_job = None
        self._last_error = ""
        self._worker = None
        self._worker_lock = threading.RLock()
        atexit.register(self.shutdown)

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
        job = self._active_job
        if job is not None:
            job.cancel.set()

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

    def _execute_job(self, browser, job) -> None:
        """Run one isolated chat in the warm browser owned by the worker thread."""
        context = None
        cancelled = lambda: job.cancel.is_set() or self._cancel.is_set()
        try:
            if cancelled():
                return
            try:
                state = self.store.load()
            except DeepSeekSessionError as exc:
                raise ReverseTransportError(str(exc), kind="auth", retryable=False) from exc
            if not state:
                raise ReverseTransportError(
                    "نشست DeepSeek ذخیره نشده است؛ ابتدا وارد حساب شو.",
                    kind="auth",
                    retryable=False,
                )

            timeout_ms = self._timeout_ms()
            context = browser.new_context(
                storage_state={
                    "cookies": state.get("cookies", []),
                    "origins": state.get("origins", []),
                }
            )
            context.add_init_script(self._session_init_script(state))
            page = context.new_page()
            self._active_page = page
            page.set_default_timeout(min(timeout_ms, 10_000))
            page.set_default_navigation_timeout(min(timeout_ms, 20_000))

            try:
                if cancelled():
                    return
                page.goto(
                    "https://chat.deepseek.com/",
                    wait_until="domcontentloaded",
                    timeout=min(timeout_ms, 20_000),
                )
                composer_deadline = time.monotonic() + min(timeout_ms / 1000, 20.0)
                composer = None
                while time.monotonic() < composer_deadline and not cancelled():
                    composer = self._composer(page)
                    if composer is not None:
                        break
                    page.wait_for_timeout(120)
                if cancelled():
                    return
                if composer is None:
                    raise ReverseTransportError(
                        "نشست DeepSeek معتبر نیست یا کادر پیام بارگذاری نشد؛ دوباره وارد حساب شو.",
                        kind="auth",
                        retryable=False,
                    )
            except ReverseTransportError:
                raise
            except Exception as exc:
                raise ReverseTransportError(
                    "نشست DeepSeek معتبر نیست یا صفحه چت بارگذاری نشد؛ دوباره وارد حساب شو.",
                    kind="auth",
                    retryable=False,
                ) from exc

            if cancelled():
                return
            before = page.evaluate(_RESPONSE_SCRIPT)
            composer = self._composer(page)
            if composer is None:
                raise ReverseTransportError(
                    "کادر پیام DeepSeek پیدا نشد؛ ساختار صفحه تغییر کرده است.",
                    kind="response",
                    retryable=False,
                )
            composer.fill(job.request.prompt)
            composer.press("Enter")

            deadline = time.monotonic() + timeout_ms / 1000
            previous_snapshot = ""
            emitted_prefix = ""
            latest_text = ""
            last_change = time.monotonic()
            completion_since = None
            started = False
            saw_stop = False
            saw_composer_disabled = False

            while time.monotonic() < deadline:
                if cancelled():
                    return
                snapshot = page.evaluate(_POLL_SCRIPT)
                if not isinstance(snapshot, dict):
                    snapshot = {}
                texts = snapshot.get("values") or []
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
                        job.events.put(("chunk", delta))
                    emitted_prefix = next_prefix
                    previous_snapshot = current

                stop_visible = bool(snapshot.get("stopVisible"))
                composer_disabled = bool(snapshot.get("composerDisabled"))
                if stop_visible:
                    saw_stop = True
                if composer_disabled:
                    saw_composer_disabled = True

                composer_present = bool(snapshot.get("composerPresent"))
                completed = (
                    started
                    and composer_present
                    and not stop_visible
                    and not composer_disabled
                    and (saw_stop or saw_composer_disabled)
                )
                if completed:
                    if completion_since is None:
                        completion_since = now
                    elif now - completion_since >= _COMPLETION_GRACE_SECONDS:
                        break
                else:
                    completion_since = None

                if (
                    started
                    and not saw_stop
                    and not saw_composer_disabled
                    and composer_present
                    and now - last_change >= _NO_STOP_IDLE_SECONDS
                ):
                    break
                page.wait_for_timeout(150)

            if cancelled():
                return
            if not started or not latest_text.strip():
                raise ReverseTransportError(
                    "DeepSeek در مهلت تعیین‌شده پاسخی برنگرداند.",
                    kind="timeout",
                    retryable=True,
                )

            try:
                self._persist_refreshed_session(context, page)
            except Exception as exc:
                self._last_error = "ذخیره نشست تازه‌شده ناموفق بود: " + str(exc)[:180]

            if latest_text.startswith(emitted_prefix):
                tail = latest_text[len(emitted_prefix):]
                if tail:
                    job.events.put(("chunk", tail))
            elif not emitted_prefix:
                job.events.put(("chunk", latest_text))
        finally:
            self._active_page = None
            if context is not None:
                try:
                    context.close()
                except Exception:
                    pass

    def _ensure_browser_worker(self):
        with self._worker_lock:
            worker = self._worker
            if worker is None or not worker.is_alive():
                worker = _DeepSeekBrowserWorker(self)
                self._worker = worker
            return worker

    def stream(self, request: ReverseRequest, cancel: threading.Event) -> Iterable[str]:
        if not self._lock.acquire(blocking=False):
            raise ReverseTransportError(
                "درخواست دیگری از طریق نشست DeepSeek در حال اجراست.",
                kind="rate",
                retryable=True,
            )
        job = None
        try:
            if cancel.is_set() or self._cancel.is_set():
                return
            worker = self._ensure_browser_worker()
            job = _DeepSeekBrowserJob(request)
            self._active_job = job
            worker.submit(job)

            while True:
                if cancel.is_set() or self._cancel.is_set():
                    job.cancel.set()
                try:
                    kind, payload = job.events.get(timeout=0.1)
                except queue.Empty:
                    if not worker.is_alive():
                        raise ReverseTransportError(
                            "مرورگر دائمی DeepSeek متوقف شد؛ برنامه را دوباره باز کن.",
                            kind="network",
                            retryable=True,
                        )
                    continue
                if kind == "chunk":
                    if payload:
                        yield str(payload)
                elif kind == "error":
                    raise payload
                elif kind == "done":
                    return
        except ReverseTransportError:
            raise
        except Exception as exc:
            if cancel.is_set() or self._cancel.is_set():
                return
            raise ReverseTransportError(
                "خطای مرورگر DeepSeek: " + str(exc)[:240],
                kind="network",
                retryable=True,
            ) from exc
        finally:
            if job is not None:
                job.cancel.set()
            self._active_job = None
            self._cancel.clear()
            self._lock.release()

    def shutdown(self) -> None:
        """Stop the warm browser worker during interpreter shutdown."""
        with self._worker_lock:
            worker, self._worker = self._worker, None
        if worker is not None:
            worker.shutdown()


__all__ = ["DeepSeekBrowserTransport"]