"""Reads kira_mcp.json (DATA_DIR). The file is written and edited ONLY by the user: no tool lets a model register a server or an agent.

Shape (all keys optional):
{
  "servers": {
    "notes": {"command": "npx", "args": ["-y", "some-mcp-server"], "env": {"NAME": "value"}, "cwd": "",
              "enabled": true, "allow": [], "deny": [], "levels": {"search": "read"}, "default_level": "sensitive",
              "timeout": 30, "max_tools": 20, "keywords": ["notes"]},
    "remote": {"url": "https://example.com/mcp", "headers_env": {"Authorization": "NAME_OF_ENV_VAR"}}
  },
  "agents": {
    "helper": {"url": "http://127.0.0.1:8765", "token_env": "NAME_OF_ENV_VAR", "timeout": 15, "enabled": true, "keywords": ["helper"]}
  }
}
Secrets are never stored here: header / token values are read from the named environment variables at call time.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

FILE_NAME = "kira_mcp.json"
LEVELS = {"read": 1, "action": 2, "sensitive": 3}
MAX_SERVERS = 12
MAX_AGENTS = 8
_NAME_RX = re.compile(r"[^a-z0-9_-]+")


def safe_name(name) -> str:
    return _NAME_RX.sub("-", str(name or "").strip().lower()).strip("-")[:32]


def _int(value, lo, hi, default):
    try:
        return max(lo, min(int(value), hi))
    except (TypeError, ValueError):
        return default


def _words(value) -> list:
    return [str(w).strip()[:40] for w in value if str(w).strip()][:12] if isinstance(value, list) else []


def _server(name, raw) -> dict | None:
    if not isinstance(raw, dict) or raw.get("enabled", True) is False:
        return None
    command, url = str(raw.get("command") or "").strip(), str(raw.get("url") or "").strip()
    if bool(command) == bool(url):
        return None                                                       # exactly one transport
    if url and not re.match(r"^https?://", url, re.I):
        return None
    env = raw.get("env") if isinstance(raw.get("env"), dict) else {}
    levels = raw.get("levels") if isinstance(raw.get("levels"), dict) else {}
    default_level = str(raw.get("default_level", "sensitive")).lower()
    return {
        "name": name, "command": command, "url": url,
        "args": [str(a) for a in raw.get("args", [])][:40] if isinstance(raw.get("args"), list) else [],
        "env": {str(k): str(v) for k, v in env.items()},
        "cwd": str(raw.get("cwd") or ""),
        "headers_env": {str(k): str(v) for k, v in (raw.get("headers_env") or {}).items()} if isinstance(raw.get("headers_env"), dict) else {},
        "allow": [str(x) for x in raw.get("allow", [])] if isinstance(raw.get("allow"), list) else [],
        "deny": [str(x) for x in raw.get("deny", [])] if isinstance(raw.get("deny"), list) else [],
        "levels": {str(k): LEVELS[str(v).lower()] for k, v in levels.items() if str(v).lower() in LEVELS},
        "default_level": LEVELS.get(default_level, 3),                    # unknown / missing = SENSITIVE
        "timeout": _int(raw.get("timeout"), 3, 120, 30),
        "max_tools": _int(raw.get("max_tools"), 1, 40, 20),
        "keywords": _words(raw.get("keywords")),
    }


def _agent(name, raw) -> dict | None:
    if not isinstance(raw, dict) or raw.get("enabled", True) is False:
        return None
    url = str(raw.get("url") or "").strip().rstrip("/")
    if not re.match(r"^https?://", url, re.I):
        return None
    return {"name": name, "url": url, "token_env": str(raw.get("token_env") or ""), "timeout": _int(raw.get("timeout"), 3, 60, 15),
            "keywords": _words(raw.get("keywords"))}


def load(data_dir) -> dict:
    """{'servers': {name: cfg}, 'agents': {name: cfg}, 'error': str}. A missing file is normal (feature unused); a broken file never raises."""
    out = {"servers": {}, "agents": {}, "error": ""}
    path = Path(data_dir) / FILE_NAME
    if not path.is_file():
        return out
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(data, dict):
            raise ValueError("top level must be an object")
        for name, raw in list((data.get("servers") or {}).items())[:MAX_SERVERS]:
            key = safe_name(name)
            cfg = _server(key, raw) if key else None
            if cfg:
                if key in out["servers"]:
                    out["error"] = (out["error"] + "; " if out["error"] else "") + f"duplicate server name after normalization: {key}"
                    continue
                out["servers"][key] = cfg
        for name, raw in list((data.get("agents") or {}).items())[:MAX_AGENTS]:
            key = safe_name(name)
            cfg = _agent(key, raw) if key else None
            if cfg:
                if key in out["agents"]:
                    out["error"] = (out["error"] + "; " if out["error"] else "") + f"duplicate agent name after normalization: {key}"
                    continue
                out["agents"][key] = cfg
    except (OSError, ValueError, AttributeError) as exc:
        out["error"] = f"{FILE_NAME}: {exc}"
    return out
