"""DeepSeek browser login and encrypted local session storage.

Task 2 owns the interactive first-login flow. Task 3 will consume the saved state
with a headless browser transport; no web-chat selectors or message sending live
in this module.
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Callable
from urllib.request import urlopen

from ..secret_store import protect, unprotect

DEEPSEEK_LOGIN_URL = "https://chat.deepseek.com/sign_in"
_AUTHENTICATED_SELECTORS = (
    'textarea',
    '[contenteditable="true"]',
    '[data-testid*="chat-input"]',
)


def _chrome_candidate_paths(environ=None) -> tuple[Path, ...]:
    """Return standard Windows Chrome locations in preference order."""
    env = os.environ if environ is None else environ
    candidates = []
    for variable in ("LOCALAPPDATA", "PROGRAMFILES", "PROGRAMFILES(X86)", "PROGRAMW6432"):
        root = str(env.get(variable) or "").strip()
        if root:
            candidates.append(Path(root) / "Google" / "Chrome" / "Application" / "chrome.exe")
    return tuple(dict.fromkeys(candidates))


def _registered_chrome_paths() -> tuple[Path, ...]:
    """Read Chrome's own Windows App Paths registration, when available."""
    if os.name != "nt":
        return ()
    try:
        import winreg
    except ImportError:
        return ()
    locations = []
    keys = (
        r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe",
        r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe",
    )
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for key_name in keys:
            try:
                with winreg.OpenKey(hive, key_name) as key:
                    value, _ = winreg.QueryValueEx(key, None)
                if value:
                    locations.append(Path(os.path.expandvars(str(value).strip().strip('"'))))
            except OSError:
                continue
    return tuple(dict.fromkeys(locations))


def _find_chrome_executable() -> Path | None:
    """Find installed Google Chrome; never fall back to an automated browser."""
    candidates = list(_registered_chrome_paths())
    candidates.extend(_chrome_candidate_paths())
    for command in ("chrome.exe", "chrome"):
        found = shutil.which(command)
        if found:
            candidates.append(Path(found))
    for candidate in candidates:
        try:
            if candidate.is_file():
                return candidate
        except OSError:
            continue
    return None


class DeepSeekSessionError(RuntimeError):
    """Login, browser runtime, or encrypted-session failure."""


class DeepSeekChromeUnavailable(DeepSeekSessionError):
    """A normal installed Chrome browser is unavailable for interactive login."""


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
        if not isinstance(state, dict) or not (state.get("cookies") or state.get("origins") or state.get("sessionStorageByOrigin")):
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
                if not isinstance(state, dict) or not (state.get("cookies") or state.get("origins") or state.get("sessionStorageByOrigin")):
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
    """Open a real, visible Chrome window and attach only to save the signed-in session."""

    def __init__(self, store: DeepSeekSessionStore | None = None) -> None:
        self.store = store or DeepSeekSessionStore()
        self._lock = threading.Lock()

    @staticmethod
    def _reserve_debug_port() -> int:
        """Choose a specific free loopback port; Chrome treats port=0 as an automation signal."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", 0))
            return int(listener.getsockname()[1])

    @staticmethod
    def _wait_for_debug_endpoint(port: int, process, timeout_seconds: float = 25.0) -> None:
        """Wait until the local DevTools HTTP endpoint is responsive."""
        endpoint = f"http://127.0.0.1:{int(port)}/json/version"
        deadline = time.monotonic() + max(1.0, float(timeout_seconds))
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise DeepSeekChromeUnavailable(
                    "Chrome هنگام شروع ورود بسته شد؛ مرورگر را به‌روز کن و دوباره امتحان کن."
                )
            try:
                with urlopen(endpoint, timeout=0.8) as response:
                    if response.status == 200:
                        return
            except Exception:
                pass
            time.sleep(0.15)
        raise DeepSeekChromeUnavailable(
            "Chrome اجرا شد اما رابط اتصال محلی آن آماده نشد. همه پنجره‌های موقت Chrome را ببند و دوباره تلاش کن."
        )

    def login(self, timeout_ms: int = 300_000) -> dict[str, Any]:
        """Let the user sign in manually in regular Chrome and encrypt the resulting browser state.

        Chrome is started as an ordinary desktop process with a dedicated Kira profile.
        Playwright attaches over loopback CDP; it does not launch a webdriver-controlled
        browser or interact with the CAPTCHA. Run this method in a worker thread.
        """
        if not self._lock.acquire(blocking=False):
            raise DeepSeekSessionError("فرایند ورود DeepSeek از قبل در حال اجراست.")
        process = None
        browser = None
        profile_temp = None
        try:
            chrome = _find_chrome_executable()
            if chrome is None:
                raise DeepSeekChromeUnavailable(
                    "CHROME_UNAVAILABLE: مرورگر Google Chrome روی این سیستم پیدا نشد. برای ورود امن، Chrome معمولی لازم است."
                )
            try:
                from playwright.sync_api import sync_playwright
            except ImportError as exc:
                raise DeepSeekChromeUnavailable(
                    "CHROME_UNAVAILABLE: Playwright نصب نیست؛ وابستگی‌های Kira را نصب کن."
                ) from exc

            profile_temp = tempfile.TemporaryDirectory(prefix="kira-deepseek-login-")
            profile_dir = Path(profile_temp.name)
            try:
                port = self._reserve_debug_port()
            except OSError as exc:
                raise DeepSeekChromeUnavailable(f"پورت محلی ورود DeepSeek رزرو نشد: {exc}") from exc

            command = [
                str(chrome),
                f"--user-data-dir={profile_dir}",
                "--remote-debugging-address=127.0.0.1",
                f"--remote-debugging-port={port}",
                "--no-first-run",
                "--no-default-browser-check",
                "--new-window",
                DEEPSEEK_LOGIN_URL,
            ]
            popen_options = {
                "stdin": subprocess.DEVNULL,
                "stdout": subprocess.DEVNULL,
                "stderr": subprocess.DEVNULL,
                "close_fds": True,
            }
            if os.name == "nt":
                popen_options["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            try:
                process = subprocess.Popen(command, **popen_options)
            except OSError as exc:
                raise DeepSeekChromeUnavailable(f"اجرای Chrome معمولی ناموفق بود: {exc}") from exc

            with sync_playwright() as playwright:
                self._wait_for_debug_endpoint(port, process)
                endpoint = f"http://127.0.0.1:{port}"
                try:
                    browser = playwright.chromium.connect_over_cdp(endpoint, timeout=20_000)
                    if not browser.contexts:
                        raise DeepSeekSessionError("Chrome نشست مرورگر قابل‌استفاده‌ای ایجاد نکرد.")
                    context = browser.contexts[0]
                    page = next(
                        (item for item in context.pages if "chat.deepseek.com" in (item.url or "")),
                        None,
                    )
                    if page is None:
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
                    session_storage = page.evaluate(
                        """() => ({origin: location.origin, entries: Object.entries(sessionStorage)
                            .map(([name, value]) => ({name, value}))})"""
                    )
                    if session_storage.get("entries"):
                        state["sessionStorageByOrigin"] = {
                            session_storage["origin"]: session_storage["entries"]
                        }
                    self.store.save(state)
                    return {"saved": True, "session_file": str(self.store.path)}
                except Exception as exc:
                    if isinstance(exc, DeepSeekSessionError):
                        raise
                    raise DeepSeekSessionError(
                        "ورود DeepSeek کامل نشد. اگر کپچا نمایش داده شد، آن را در پنجره Chrome حل کن "
                        "و تا بازشدن صفحه چت صبر کن. جزئیات: " + str(exc)[:240]
                    ) from exc
        finally:
            if browser is not None:
                try:
                    browser.close()
                except Exception:
                    pass
            if process is not None and process.poll() is None:
                try:
                    process.wait(timeout=6)
                except subprocess.TimeoutExpired:
                    try:
                        process.terminate()
                        process.wait(timeout=8)
                    except Exception:
                        try:
                            process.kill()
                            process.wait(timeout=4)
                        except Exception:
                            pass
            if profile_temp is not None:
                try:
                    profile_temp.cleanup()
                except OSError:
                    pass
            self._lock.release()
