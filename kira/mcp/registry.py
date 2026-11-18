"""Official MCP Registry discovery and safe local server configuration.

Search uses the public registry. A server is never launched from registry metadata
until the user explicitly selects Add in Kira's UI. Only known package runners
(npx / uvx) and HTTPS remote endpoints are accepted; no shell command is executed.
"""
from __future__ import annotations

import re
import urllib.parse
import urllib.request
import json

from PySide6.QtCore import QThread, Signal

REGISTRY_URL = "https://registry.modelcontextprotocol.io/v0.1/servers"
MAX_RESULTS = 30
_NAME = re.compile(r"[^a-z0-9_-]+")
_PACKAGE = re.compile(r"^(?:@[A-Za-z0-9_.-]+/)?[A-Za-z0-9_.-]+$")
_VERSION = re.compile(r"^[A-Za-z0-9.+_-]{1,80}$")


def search_servers(query: str = "", limit: int = MAX_RESULTS) -> list[dict]:
    query = str(query or "").strip()
    if query and len(query) < 3:
        raise ValueError("برای جستجو حداقل سه نویسه وارد کن.")
    params = {"version": "latest", "limit": str(max(1, min(int(limit), MAX_RESULTS)))}
    if query:
        params["search"] = query
    url = REGISTRY_URL + "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "Kira-MCP-Registry/1.0"})
    with urllib.request.urlopen(request, timeout=15) as response:
        payload = json.loads(response.read(2_000_000).decode("utf-8"))
    records = payload.get("servers", []) if isinstance(payload, dict) else []
    active = []
    for record in records:
        if not isinstance(record, dict):
            continue
        meta = record.get("_meta", {}).get("io.modelcontextprotocol.registry/official", {})
        if isinstance(meta, dict) and meta.get("status") not in (None, "active"):
            continue
        active.append(record)
    return active[:MAX_RESULTS]


def _safe_args(value) -> list[str]:
    if not isinstance(value, list):
        return []
    out = []
    for item in value[:24]:
        if isinstance(item, str) and len(item) <= 300 and not any(ch in item for ch in ("\x00", "\r", "\n")):
            out.append(item)
        elif isinstance(item, dict):
            raw = item.get("value")
            kind = str(item.get("type") or "positional").lower()
            flag = str(item.get("name") or "").strip()
            if not isinstance(raw, str) or len(raw) > 300 or any(ch in raw for ch in ("\x00", "\r", "\n")):
                continue
            if kind == "named":
                if not re.fullmatch(r"--?[A-Za-z0-9_-]{1,64}", flag):
                    continue
                out.extend([flag, raw])
            elif kind == "positional":
                out.append(raw)
    return out


def server_config(record: dict) -> tuple[str, dict]:
    """Convert one official registry record into a Kira MCP config entry."""
    server = record.get("server", record)
    if not isinstance(server, dict):
        raise ValueError("اطلاعات سرور رجیستری معتبر نیست.")
    raw_name = str(server.get("name") or "").strip()
    name = _NAME.sub("-", raw_name.lower()).strip("-")[:32]
    if not name:
        raise ValueError("نام سرور MCP معتبر نیست.")
    cfg = {
        "enabled": True, "allow": [], "deny": [], "levels": {},
        "default_level": "sensitive", "timeout": 30, "max_tools": 20,
        "keywords": [name.replace("-", " ")],
    }
    remotes = server.get("remotes") if isinstance(server.get("remotes"), list) else []
    for remote in remotes:
        if not isinstance(remote, dict):
            continue
        endpoint = str(remote.get("url") or "").strip()
        if endpoint.startswith("https://"):
            cfg["url"] = endpoint
            return name, cfg
    packages = server.get("packages") if isinstance(server.get("packages"), list) else []
    for package in packages:
        if not isinstance(package, dict):
            continue
        transport = package.get("transport") or {}
        if isinstance(transport, dict) and transport.get("type") not in (None, "stdio"):
            continue
        kind = str(package.get("registryType") or "").lower()
        identifier = str(package.get("identifier") or "").strip()
        version = str(package.get("version") or "").strip()
        if not _PACKAGE.fullmatch(identifier):
            continue
        if version and not _VERSION.fullmatch(version):
            continue
        env = {}
        for item in package.get("environmentVariables") or []:
            if isinstance(item, dict) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", str(item.get("name") or "")):
                env[str(item["name"])] = str(item.get("default") or "")
        if kind == "npm":
            spec = identifier + ("@" + version if version else "")
            cfg.update(command="npx", args=["-y", spec, *_safe_args(package.get("packageArguments"))], env=env)
            return name, cfg
        if kind in ("pypi", "python"):
            spec = identifier + ("==" + version if version else "")
            cfg.update(command="uvx", args=["--from", spec, *_safe_args(package.get("packageArguments"))], env=env)
            return name, cfg
    raise ValueError("این سرور بسته‌ی قابل‌اجرای خودکار (npm/uvx) یا آدرس HTTPS ندارد؛ برای امنیت به‌صورت خودکار نصب نشد.")


class RegistrySearchWorker(QThread):
    completed = Signal(object, str)

    def __init__(self, query="", parent=None):
        super().__init__(parent)
        self.query = str(query or "")

    def run(self):
        try:
            self.completed.emit(search_servers(self.query), "")
        except Exception as exc:
            self.completed.emit([], f"{type(exc).__name__}: {exc}")
