"""Structured, secret-safe lifecycle tracing for outbound model requests.

Writes JSONL records to DATA_DIR/logs/request_trace.jsonl and mirrors concise
records to the normal Python logger (therefore the in-app Runtime Log).
No prompts, response bodies, API keys, or authorization headers are recorded.
"""
from __future__ import annotations

import contextvars
import json
import logging
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

_request_id = contextvars.ContextVar("kira_request_trace_id", default="")
_lock = threading.Lock()
_logger = logging.getLogger("kira.request_trace")
_MAX_BYTES = 5 * 1024 * 1024


def current_request_id() -> str:
    return _request_id.get()


def set_request_id(value: str):
    return _request_id.set(str(value or ""))


def reset_request_id(token):
    _request_id.reset(token)


def _log_path() -> Path:
    # Lazy import avoids config/provider import cycles.
    from . import config
    folder = Path(config.DATA_DIR) / "logs"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "request_trace.jsonl"


def trace(phase: str, **fields):
    """Write one bounded, secret-safe JSONL event. Logging must never break chat."""
    record = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "mono": round(time.monotonic(), 6),
        "request_id": current_request_id() or None,
        "phase": str(phase)[:64],
    }
    # Explicitly accept only scalar diagnostic fields; callers must never pass payloads.
    for key, value in fields.items():
        if value is None or isinstance(value, (str, int, float, bool)):
            record[str(key)[:48]] = value[:240] if isinstance(value, str) else value
    try:
        path = _log_path()
        line = json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
        with _lock:
            if path.exists() and path.stat().st_size + len(line.encode("utf-8")) > _MAX_BYTES:
                backup = path.with_suffix(".jsonl.1")
                try:
                    backup.unlink(missing_ok=True)
                except OSError:
                    pass
                try:
                    path.replace(backup)
                except OSError:
                    pass
            with path.open("a", encoding="utf-8") as stream:
                stream.write(line)
        _logger.info("%s", json.dumps(record, ensure_ascii=False, separators=(",", ":")))
    except Exception:
        # Diagnostics are best-effort and must never interrupt provider traffic.
        pass
