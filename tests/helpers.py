"""Shared test helpers. Importing this module redirects Kira's data folder to a temp dir (never the real one)."""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if "KIRA_DATA_DIR" not in os.environ:
    os.environ["KIRA_DATA_DIR"] = tempfile.mkdtemp(prefix="kira_test_")
if "KIRA_LOG_DIR" not in os.environ:                       # tests never write telemetry into the program folder
    os.environ["KIRA_LOG_DIR"] = tempfile.mkdtemp(prefix="kira_logs_")
sys.path.insert(0, str(ROOT))

import base64
from copy import deepcopy

from kira import config  # noqa: E402

CANARY = "TESTKEY-CANARY-1234567890abcdef"


def fresh_settings():
    return deepcopy(config.DEFAULTS)


def enable(settings, *names, canary=True):
    for n in names:
        cfg = settings["providers"][n]
        cfg["enabled"] = True
        cfg["api_key"] = f"{CANARY}-{n}" if canary else "k"
        if n == "cloudflare":
            cfg["account_id"] = "acc123"
        if n == "openrouter":
            cfg["model"] = "some/model"
    return settings


class Resp:
    def __init__(self, status=200, body=None, text=None, headers=None):
        self.status_code = status
        self._body = body
        self.text = text if text is not None else (str(body) if body is not None else "")
        self.headers = headers or {}

    def json(self):
        if self._body is None:
            raise ValueError("no json")
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(str(self.status_code))


def ok_openai(text="سلام"):
    return Resp(200, {"choices": [{"message": {"content": text}}]})


def ok_cloudflare(text="سلام"):
    return Resp(200, {"result": {"response": text}})


def ok_ollama(text="سلام"):
    return Resp(200, {"message": {"content": text}})


def fake_dpapi():
    """Reversible stand-in for DPAPI so the config logic can be tested on any OS."""
    def protect(value):
        if not value or value.startswith("dpapi:"):
            return value
        return "dpapi:" + base64.b64encode(value[::-1].encode()).decode()

    def unprotect(value):
        if not value or not value.startswith("dpapi:"):
            return value
        return base64.b64decode(value[6:]).decode()[::-1]
    return protect, unprotect


class StreamResp:
    """requests.Response stand-in for stream=True. `lines` may contain bytes/str, an Exception (raised at that point), or
    a callable (called when that position is reached, e.g. to press Stop)."""
    def __init__(self, lines, status=200, body=None, headers=None):
        self.status_code = status
        self._lines = list(lines)
        self._body = body
        self.text = "" if body is None else str(body)
        self.headers = headers or {}
        self.closed = False
        self.consumed = 0

    def json(self):
        if self._body is None:
            raise ValueError("no json")
        return self._body

    def iter_lines(self, *a, **kw):
        for item in self._lines:
            if self.closed:
                return
            self.consumed += 1
            if isinstance(item, Exception):
                raise item
            if callable(item):
                item()
                continue
            yield item

    def close(self):
        self.closed = True


def sse(*objs, done=True):
    """OpenAI-style SSE byte lines for the given delta texts."""
    import json as _json
    out = []
    for o in objs:
        payload = o if isinstance(o, dict) else {"choices": [{"delta": {"content": o}}]}
        out.append(("data: " + _json.dumps(payload, ensure_ascii=False)).encode("utf-8"))
        out.append(b"")
    if done:
        out.append(b"data: [DONE]")
    return out


def ndjson(*texts, stats=True):
    import json as _json
    out = [_json.dumps({"message": {"role": "assistant", "content": t}, "done": False}, ensure_ascii=False).encode("utf-8") for t in texts]
    if stats:
        out.append(_json.dumps({"message": {"content": ""}, "done": True, "load_duration": 2_000_000_000, "eval_count": 10,
                                "eval_duration": 1_000_000_000, "prompt_eval_count": 5, "total_duration": 3_500_000_000}).encode())
    return out
