"""Embedded DeepSeek login fallback used when desktop Chrome is unavailable."""
from __future__ import annotations

import json
from typing import Any

from .deepseek_session import DEEPSEEK_LOGIN_URL, DeepSeekSessionError, DeepSeekSessionStore

_AUTHENTICATED_JS = """(() => {
  const selectors = ['textarea', '[contenteditable="true"]', '[data-testid*="chat-input"]'];
  return selectors.some(selector => {
    const node = document.querySelector(selector);
    if (!node) return false;
    const style = getComputedStyle(node);
    return style.display !== 'none' && style.visibility !== 'hidden';
  });
})()"""


def run_embedded_login(parent=None, store: DeepSeekSessionStore | None = None) -> bool:
    """Show DeepSeek inside Kira and save its cookies/localStorage after login."""
    try:
        from PySide6.QtCore import QTimer, QUrl
        from PySide6.QtNetwork import QNetworkCookie
        from PySide6.QtWidgets import QDialog, QLabel, QVBoxLayout
        from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
        from PySide6.QtWebEngineWidgets import QWebEngineView
    except ImportError as exc:
        raise DeepSeekSessionError(
            "مرورگر داخلی Kira در این نصب Qt در دسترس نیست."
        ) from exc

    session_store = store or DeepSeekSessionStore()

    class LoginDialog(QDialog):
        def __init__(self):
            super().__init__(parent)
            self.setWindowTitle("ورود به DeepSeek")
            self.resize(1040, 760)
            self._cookies: dict[tuple[str, str, str], dict[str, Any]] = {}
            self._finishing = False
            self.status = QLabel("وارد حساب DeepSeek شو؛ بعد از ورود نشست به‌صورت امن ذخیره می‌شود.")
            self.status.setWordWrap(True)
            self.view = QWebEngineView(self)
            self.profile = QWebEngineProfile(self)
            self.page = QWebEnginePage(self.profile, self.view)
            self.view.setPage(self.page)
            layout = QVBoxLayout(self)
            layout.addWidget(self.status)
            layout.addWidget(self.view, 1)
            self.profile.cookieStore().cookieAdded.connect(self._cookie_added)
            self.profile.cookieStore().loadAllCookies()
            self.view.loadFinished.connect(self._page_loaded)
            self.timer = QTimer(self)
            self.timer.setInterval(900)
            self.timer.timeout.connect(self._check_login)
            self.view.setUrl(QUrl(DEEPSEEK_LOGIN_URL))

        def _cookie_added(self, cookie):
            try:
                name = bytes(cookie.name()).decode("utf-8", "replace")
                value = bytes(cookie.value()).decode("utf-8", "replace")
                domain = str(cookie.domain())
                path = str(cookie.path() or "/")
                if not name or not domain:
                    return
                expires = -1 if cookie.isSessionCookie() else int(cookie.expirationDate().toSecsSinceEpoch())
                same_site = "Lax"
                policy = str(cookie.sameSitePolicy()).lower()
                if "strict" in policy:
                    same_site = "Strict"
                elif "none" in policy:
                    same_site = "None"
                self._cookies[(domain, path, name)] = {
                    "name": name, "value": value, "domain": domain, "path": path,
                    "expires": expires, "httpOnly": bool(cookie.isHttpOnly()),
                    "secure": bool(cookie.isSecure()), "sameSite": same_site,
                }
            except Exception:
                return

        def _page_loaded(self, ok):
            if ok:
                self.timer.start()
            else:
                self.status.setText("صفحه ورود بارگذاری نشد؛ اتصال اینترنت را بررسی کن.")

        def _check_login(self):
            if self._finishing:
                return
            self.page.runJavaScript(_AUTHENTICATED_JS, self._on_authenticated)

        def _on_authenticated(self, ready):
            if not ready or self._finishing:
                return
            self._finishing = True
            self.timer.stop()
            script = "JSON.stringify(Object.entries(localStorage).map(([name,value]) => ({name,value})))"
            self.page.runJavaScript(script, self._save_state)

        def _save_state(self, raw_storage):
            try:
                entries = json.loads(raw_storage or "[]")
                origins = []
                if entries:
                    origins.append({
                        "origin": "https://chat.deepseek.com",
                        "localStorage": entries,
                    })
                state = {"cookies": list(self._cookies.values()), "origins": origins}
                session_store.save(state)
                self.status.setText("نشست DeepSeek به‌صورت رمزگذاری‌شده ذخیره شد.")
                self.accept()
            except Exception as exc:
                self._finishing = False
                self.timer.start()
                self.status.setText("ذخیره نشست انجام نشد: " + str(exc)[:220])

    dialog = LoginDialog()
    return dialog.exec() == QDialog.DialogCode.Accepted
