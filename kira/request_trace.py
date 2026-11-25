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
_SENSITIVE_FIELDS = frozenset({
    "key", "api_key", "secret", "token", "authorization", "headers",
    "prompt", "messages", "message", "content", "completion", "response",
    "response_body", "body", "payload", "input", "output", "tool_calls",
    "tool_arguments", "arguments", "credential", "credentials",
})


def current_request_id() -> str:
    return _request_id.get()


def set_request_id(value: str):
    return _request_id.set(str(value or ""))


def reset_request_id(token):
    _request_id.reset(token)


def _log_path(filename: str = "request_trace.jsonl") -> Path:
    # Lazy import avoids config/provider import cycles.
    from . import config
    folder = Path(config.DATA_DIR) / "logs"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / filename


def trace(phase: str, **fields):
    """Write one bounded, secret-safe JSONL event. Logging must never break chat."""
    _write(phase, fields, "request_trace.jsonl")


def gemini_trace(phase: str, **fields):
    """Same as trace(), but into DATA_DIR/logs/gemini_trace.jsonl: only requests sent to Google's Gemini endpoint."""
    _write(phase, fields, "gemini_trace.jsonl")


def vision_trace(phase: str, **fields):
    """Game Mode vision diagnostics into DATA_DIR/logs/vision_trace.jsonl.

    Records what the capture/attachment path did (window found, frame size, whether the frame
    reached the model request). It never records pixels or prompts.
    """
    _write(phase, fields, "vision_trace.jsonl")


def _write(phase: str, fields: dict, filename: str):
    record = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "mono": round(time.monotonic(), 6),
        "request_id": current_request_id() or None,
        "phase": str(phase)[:64],
    }
    # Explicitly accept only scalar diagnostic fields; callers must never pass payloads.
    for key, value in fields.items():
        field_name = str(key)[:48]
        normalized_key = field_name.strip().casefold().replace("-", "_")
        if normalized_key in _SENSITIVE_FIELDS:
            continue
        if any(normalized_key.endswith(suffix) for suffix in (
            "_api_key", "_secret", "_authorization", "_prompt", "_messages",
            "_message", "_content", "_completion", "_response_body",
            "_body", "_payload", "_tool_calls", "_tool_arguments",
        )):
            continue
        if value is None or isinstance(value, (str, int, float, bool)):
            record[field_name] = value[:240] if isinstance(value, str) else value
    try:
        path = _log_path(filename)
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
        prefix = "[gemini] " if filename.startswith("gemini") else "[vision] " if filename.startswith("vision") else ""
        _logger.info("%s%s", prefix, json.dumps(record, ensure_ascii=False, separators=(",", ":")))
    except Exception:
        # Diagnostics are best-effort and must never interrupt provider traffic.
        pass
