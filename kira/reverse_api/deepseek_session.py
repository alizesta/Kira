"""DeepSeek browser login and encrypted local session storage.

Task 2 owns the interactive first-login flow. Task 3 will consume the saved state
with a headless browser transport; no web-chat selectors or message sending live
in this module.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from typing import Any, Callable

from ..secret_store import protect, unprotect

DEEPSEEK_LOGIN_URL = "https://chat.deepseek.com/"
_AUTHENTICATED_SELECTORS = (
    'textarea',
    '[contenteditable="true"]',
    '[data-testid*="chat-input"]',
)


class DeepSeekSessionError(RuntimeError):
    """Login, browser runtime, or encrypted-session failure."""


class DeepSeekSessionStore:
    """Persist Playwright storage state encrypted with the current Windows user DPAPI key."""

    def __init__(
        self,
        data_dir: str | os.PathLike[str] | None = None,
        *,
        encrypt: Callable[[str], str] = protect,
        decrypt: Callable[[str], str] = unprotect,
    ) -> None:
        if data_dir is None:
            from ..config import DATA_DIR
            data_dir = DATA_DIR
        self.path = Path(data_dir) / "reverse_api" / "deepseek.session"
        self._encrypt = encrypt
        self._decrypt = decrypt
        self._lock = threading.RLock()

    def save(self, state: dict[str, Any]) -> None:
        if os.name != "nt" and self._encrypt is protect:
            raise DeepSeekSessionError("ذخیره امن نشست DeepSeek فقط روی Windows پشتیبانی می‌شود.")
        if not isinstance(state, dict) or not (state.get("cookies") or state.get("origins")):
            raise DeepSeekSessionError("مرورگر نشست معتبری برای ذخیره برنگرداند.")
        raw = json.dumps(state, ensure_ascii=False, separators=(",", ":"))
        try:
            encrypted = self._encrypt(raw)
            if not encrypted or encrypted == raw:
                raise DeepSeekSessionError("نشست به‌صورت رمزگذاری‌شده ذخیره نشد.")
            with self._lock:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                temp_path = None
                try:
                    with tempfile.NamedTemporaryFile(
                        mode="w", encoding="utf-8", dir=self.path.parent,
                        prefix=".deepseek-session-", suffix=".tmp", delete=False,
                    ) as handle:
                        temp_path = Path(handle.name)
                        handle.write(encrypted)
                        handle.flush()
                        os.fsync(handle.fileno())
                    os.replace(temp_path, self.path)
                finally:
                    if temp_path is not None:
                        temp_path.unlink(missing_ok=True)
        except DeepSeekSessionError:
            raise
        except Exception as exc:
            raise DeepSeekSessionError(f"ذخیره نشست DeepSeek ناموفق بود: {exc}") from exc

    def load(self) -> dict[str, Any] | None:
        with self._lock:
            if not self.path.is_file():
                return None
            try:
                encrypted = self.path.read_text(encoding="utf-8")
                raw = self._decrypt(encrypted)
                if not raw:
                    raise DeepSeekSessionError("نشست ذخیره‌شده روی این حساب Windows قابل رمزگشایی نیست.")
                state = json.loads(raw)
                if not isinstance(state, dict) or not (state.get("cookies") or state.get("origins")):
                    raise DeepSeekSessionError("ساختار نشست DeepSeek معتبر نیست.")
                return state
            except DeepSeekSessionError:
                raise
            except Exception as exc:
                raise DeepSeekSessionError(f"خواندن نشست DeepSeek ناموفق بود: {exc}") from exc

    def clear(self) -> bool:
        with self._lock:
            try:
                self.path.unlink(missing_ok=True)
                return True
            except OSError as exc:
                raise DeepSeekSessionError(f"حذف نشست DeepSeek ناموفق بود: {exc}") from exc

    def has_session(self) -> bool:
        return self.load() is not None


class DeepSeekBrowserLogin:
    """Open the first-login page in Chrome, falling back to Playwright's Chromium."""

    def __init__(self, store: DeepSeekSessionStore | None = None) -> None:
        self.store = store or DeepSeekSessionStore()
        self._lock = threading.Lock()

    def login(self, timeout_ms: int = 300_000) -> dict[str, Any]:
        """Wait for the user to finish login, then encrypt and persist browser storage state.

        This is intentionally synchronous and should be called from a worker thread,
        never from the Qt UI thread.
        """
        if not self._lock.acquire(blocking=False):
            raise DeepSeekSessionError("فرایند ورود DeepSeek از قبل در حال اجراست.")
        try:
            try:
                from playwright.sync_api import sync_playwright
            except ImportError as exc:
                raise DeepSeekSessionError(
                    "Playwright نصب نیست؛ وابستگی‌های Kira را به‌روزرسانی کن."
                ) from exc

            errors: list[str] = []
            with sync_playwright() as playwright:
                browser = None
                context = None
                for channel in ("chrome", None):
                    try:
                        launch = {"headless": False}
                        if channel:
                            launch["channel"] = channel
                        browser = playwright.chromium.launch(**launch)
                        context = browser.new_context()
                        break
                    except Exception as exc:
                        errors.append(f"{channel or 'chromium'}: {exc}")
                        if browser is not None:
                            try:
                                browser.close()
                            except Exception:
                                pass
                        browser, context = None, None
                if browser is None or context is None:
                    # Playwright's Python package does not bundle browser binaries.
                    # Install its pinned Chromium runtime once, then retry the managed browser.
                    try:
                        install = subprocess.run(
                            [sys.executable, "-m", "playwright", "install", "chromium"],
                            capture_output=True, text=True, timeout=240, check=False,
                        )
                        if install.returncode == 0:
                            browser = playwright.chromium.launch(headless=False)
                            context = browser.new_context()
                    except Exception as exc:
                        errors.append(f"chromium install: {exc}")
                if browser is None or context is None:
                    raise DeepSeekSessionError(
                        "Chrome و مرورگر داخلی Kira قابل اجرا نیستند: " + " | ".join(errors)[:500]
                    )

                try:
                    page = context.new_page()
                    page.goto(DEEPSEEK_LOGIN_URL, wait_until="domcontentloaded", timeout=60_000)
                    page.wait_for_function(
                        """selectors => selectors.some(selector => {
                            const node = document.querySelector(selector);
                            if (!node) return false;
                            const style = window.getComputedStyle(node);
                            return style.display !== 'none' && style.visibility !== 'hidden';
                        })""",
                        arg=list(_AUTHENTICATED_SELECTORS),
                        timeout=max(1_000, int(timeout_ms)),
                    )
                    state = context.storage_state()
                    self.store.save(state)
                    # Never return cookie/token material to the UI or log layer.
                    return {"saved": True, "session_file": str(self.store.path)}
                except Exception as exc:
                    raise DeepSeekSessionError(
                        "ورود DeepSeek کامل نشد یا صفحه چت شناسایی نشد: " + str(exc)[:400]
                    ) from exc
                finally:
                    try:
                        context.close()
                    finally:
                        browser.close()
        finally:
            self._lock.release()
