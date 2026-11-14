"""Client adapter for the shared Kira Core API.

This module is Qt-free. Windows keeps only its short-lived Core session locally;
shared conversation/settings/memory remain account-owned on Kira Core.
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests


class KiraCoreError(RuntimeError):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = int(status_code)


class KiraCoreClient:
    """Synchronous HTTP client. Call it from a worker thread, never the GUI thread."""

    SESSION_FILE = "kira_core_session.json"

    def __init__(self, base_url: str | None = None, data_dir: str | Path | None = None,
                 timeout: tuple[float, float] = (15, 120), session: requests.Session | None = None):
        self.base_url = str(base_url or os.environ.get("KIRA_CORE_URL") or "").strip().rstrip("/")
        if not self.base_url:
            raise ValueError("KIRA Core URL is not configured.")
        if not (self.base_url.startswith("https://") or self.base_url.startswith("http://127.0.0.1")):
            raise ValueError("KIRA Core must use HTTPS (HTTP is allowed only for local development).")
        if data_dir is None:
            from .config import DATA_DIR
            data_dir = DATA_DIR
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.session_path = self.data_dir / self.SESSION_FILE
        self.timeout = timeout
        self.http = session or requests.Session()
        self._lock = threading.RLock()
        self._access_token = ""
        self._refresh_token = ""
        self.account_id = ""
        self._load_session()

    @property
    def authenticated(self) -> bool:
        return bool(self._access_token and self._refresh_token and self.account_id)

    def _load_session(self) -> None:
        if not self.session_path.is_file():
            return
        try:
            from .secret_store import unprotect
            saved = json.loads(self.session_path.read_text(encoding="utf-8"))
            self._access_token = unprotect(str(saved.get("access_token") or ""))
            self._refresh_token = unprotect(str(saved.get("refresh_token") or ""))
            self.account_id = str(saved.get("account_id") or "")
        except Exception:
            # Preserve an unreadable session file for diagnosis; start signed out.
            self._access_token = self._refresh_token = self.account_id = ""

    def _save_session(self) -> None:
        from .secret_store import protect
        # On Windows, protect() uses the current user's DPAPI profile. On other
        # operating systems secret_store intentionally does not persist plaintext.
        if os.name != "nt":
            return
        payload = {
            "account_id": self.account_id,
            "access_token": protect(self._access_token),
            "refresh_token": protect(self._refresh_token),
        }
        tmp = self.session_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.session_path)

    def clear_session(self) -> None:
        with self._lock:
            self._access_token = self._refresh_token = self.account_id = ""
            if self.session_path.exists():
                try:
                    self.session_path.unlink()
                except OSError:
                    pass

    def _set_session(self, payload: dict) -> dict:
        access = str(payload.get("access_token") or "")
        refresh = str(payload.get("refresh_token") or "")
        account_id = str(payload.get("account_id") or "")
        if not access or not refresh or not account_id:
            raise KiraCoreError(502, "Kira Core returned an incomplete session.")
        with self._lock:
            self._access_token, self._refresh_token, self.account_id = access, refresh, account_id
            self._save_session()
        return payload

    def register(self, email: str, password: str, display_name: str = "") -> dict:
        return self._set_session(self._request("POST", "/v1/auth/register", {
            "email": email, "password": password, "display_name": display_name,
        }, authenticated=False))

    def login(self, email: str, password: str) -> dict:
        return self._set_session(self._request("POST", "/v1/auth/login", {
            "email": email, "password": password,
        }, authenticated=False))

    def refresh(self) -> dict:
        with self._lock:
            refresh_token = self._refresh_token
        if not refresh_token:
            raise KiraCoreError(401, "Sign in to Kira Core first.")
        payload = self._request("POST", "/v1/auth/refresh", {
            "refresh_token": refresh_token,
        }, authenticated=False)
        return self._set_session(payload)

    def logout(self) -> None:
        with self._lock:
            refresh_token = self._refresh_token
        try:
            if refresh_token:
                self._request("POST", "/v1/auth/logout", {"refresh_token": refresh_token})
        finally:
            self.clear_session()

    def account(self) -> dict:
        return self._request("GET", "/v1/account")

    def get_settings(self) -> dict:
        return self._request("GET", "/v1/settings")

    def save_settings(self, revision: int, settings: dict) -> dict:
        return self._request("PUT", "/v1/settings", {"revision": int(revision), "settings": settings})

    def save_provider_credential(self, provider_id: str, api_key: str, account_id: str | None = None) -> None:
        payload: dict[str, Any] = {"api_key": api_key}
        if account_id:
            payload["account_id"] = account_id
        self._request("PUT", f"/v1/settings/providers/{quote(provider_id, safe='')}/credential", payload)

    def delete_provider_credential(self, provider_id: str) -> None:
        self._request("DELETE", f"/v1/settings/providers/{quote(provider_id, safe='')}/credential")

    def conversations(self, character_id: str | None = None) -> dict:
        params = {"character_id": character_id} if character_id else None
        return self._request("GET", "/v1/conversations", params=params)

    def create_conversation(self, character_id: str, title: str = "") -> dict:
        return self._request("POST", "/v1/conversations", {
            "character_id": character_id, "title": title,
        })

    def messages(self, conversation_id: str) -> dict:
        return self._request("GET", f"/v1/conversations/{quote(conversation_id, safe='')}/messages")

    def send_message(self, conversation_id: str, character_id: str, content: str,
                     attachment_ids: list[str] | None = None,
                     approved_screen_context: bool = False,
                     device_id: str | None = None) -> dict:
        payload = {
            "conversation_id": conversation_id,
            "character_id": character_id,
            "content": content,
            "attachment_ids": list(attachment_ids or []),
            "approved_screen_context": bool(approved_screen_context),
        }
        if device_id:
            payload["device_id"] = device_id
        return self._request("POST", "/v1/chat/messages", payload)

    def get_memory(self, character_id: str) -> dict:
        return self._request("GET", f"/v1/memory/{quote(character_id, safe='')}")

    def save_memory(self, character_id: str, revision: int, items: list[dict]) -> dict:
        return self._request("PUT", f"/v1/memory/{quote(character_id, safe='')}", {
            "revision": int(revision), "items": items,
        })

    def register_device(self, device_id: str, device_name: str, app_version: str,
                        local_capabilities: list[str] | None = None) -> dict:
        return self._request("POST", "/v1/devices", {
            "device_id": device_id,
            "platform": "windows",
            "device_name": device_name,
            "app_version": app_version,
            "local_capabilities": list(local_capabilities or []),
        })

    def devices(self) -> dict:
        return self._request("GET", "/v1/devices")

    def restore_snapshot(self) -> dict:
        return self._request("GET", "/v1/sync/snapshot")

    def import_desktop_data(self, import_id: str, shared_data: dict,
                            provider_credentials: dict | None = None) -> dict:
        """Call only after showing the user a preview and obtaining explicit import consent."""
        payload = {"import_id": import_id, "shared_data": shared_data}
        if provider_credentials:
            payload["provider_credentials"] = provider_credentials
        return self._request("POST", "/v1/sync/import", payload)

    def _request(self, method: str, path: str, payload: dict | None = None,
                 params: dict | None = None, authenticated: bool = True,
                 retry_auth: bool = True) -> dict:
        headers = {"Accept": "application/json"}
        if authenticated:
            with self._lock:
                token = self._access_token
            if not token:
                raise KiraCoreError(401, "Sign in to Kira Core first.")
            headers["Authorization"] = f"Bearer {token}"
        try:
            response = self.http.request(
                method=method,
                url=self.base_url + path,
                json=payload,
                params=params,
                headers=headers,
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise KiraCoreError(0, f"Cannot reach Kira Core: {exc}") from exc

        if response.status_code == 401 and authenticated and retry_auth:
            try:
                self.refresh()
            except Exception:
                self.clear_session()
                raise KiraCoreError(401, "Kira Core session expired. Sign in again.")
            return self._request(method, path, payload, params, authenticated, retry_auth=False)

        if not 200 <= response.status_code < 300:
            try:
                detail = response.json().get("detail")
                if isinstance(detail, dict):
                    message = str(detail.get("message") or detail)
                else:
                    message = str(detail or response.text)
            except (ValueError, AttributeError):
                message = response.text
            raise KiraCoreError(response.status_code, message[:800])

        if response.status_code == 204 or not response.content:
            return {}
        try:
            data = response.json()
        except ValueError as exc:
            raise KiraCoreError(502, "Kira Core returned a non-JSON response.") from exc
        if not isinstance(data, dict):
            raise KiraCoreError(502, "Kira Core returned an unexpected response.")
        return data
