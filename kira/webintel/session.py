"""Temporary research memory (one research session) kept OUTSIDE any model, so a Route / Provider change or a Failover cannot lose it.

  * stores the searches made, the pages read (title, publisher, date, relevant excerpts only), the findings per sub-topic and the budget used;
  * answers a repeated search / page from memory instead of going to the web again (time-sensitive entries expire quickly and are re-checked);
  * is saved to <data>/web_research/session.json so a stopped research can be continued; it expires after 24 hours;
  * is TEMPORARY: it is never written to Kira's long-term memory and it is deleted with the chat (clear) or on request.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import threading
import time
import uuid
from pathlib import Path

CANCEL = threading.Event()                 # set by the Stop button (ToolAgent.request_cancel); every research loop checks it
SESSION_TTL = 24 * 3600
TTL_SEARCH_FRESH = 10 * 60                 # time-sensitive searches are repeated after 10 minutes ...
TTL_SEARCH_STABLE = 6 * 3600               # ... other searches after 6 hours
TTL_PAGE_FRESH = 30 * 60
TTL_PAGE_STABLE = 12 * 3600

RUNNING, PAUSED, DONE, CANCELLED, FAILED = "running", "paused", "done", "cancelled", "failed"
STATUS_FA = {RUNNING: "در حال انجام", PAUSED: "متوقف‌شده (قابل ادامه)", DONE: "کامل", CANCELLED: "لغو شده", FAILED: "ناموفق"}

DEFAULT_BUDGET = {"max_searches": 8, "max_pages": 10, "max_seconds": 90, "max_chars": 9000}
HARD_LIMITS = {"max_searches": (1, 20), "max_pages": (1, 25), "max_seconds": (15, 300), "max_chars": (2500, 14000)}


def _clamp(value, lo, hi, default):
    try:
        return max(lo, min(int(float(value)), hi))
    except (TypeError, ValueError):
        return default


def budget_from(settings: dict | None, **overrides) -> dict:
    """Defaults < settings.json (web_research_*) < the call's own arguments; always inside the hard limits."""
    settings = settings or {}
    out = {}
    for key, default in DEFAULT_BUDGET.items():
        lo, hi = HARD_LIMITS[key]
        value = overrides.get(key)
        if value is None:
            value = settings.get("web_research_" + key, default)
        out[key] = _clamp(value, lo, hi, default)
        if key in overrides and overrides[key] is not None:                  # a call may only go lower than the user's own setting
            cap = _clamp(settings.get("web_research_" + key, default), lo, hi, default)
            out[key] = min(out[key], cap)
    return out


def norm_key(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").lower().replace("ي", "ی").replace("ك", "ک").replace("‌", " ")).strip()


class Session:
    def __init__(self, topic: str = "", budget: dict | None = None):
        now = time.time()
        self.id = uuid.uuid4().hex[:8]
        self.topic = topic
        self.subtopics: list[str] = []
        self.sub_queries: dict[str, str] = {}
        self.status = RUNNING
        self.created = self.updated = now
        self.budget = dict(budget or DEFAULT_BUDGET)
        self.used = {"searches": 0, "pages": 0, "chars": 0, "seconds": 0.0}
        self.queries: dict[str, dict] = {}           # normalised query -> {query, kind, engine, ts, urls}
        self.pages: dict[str, dict] = {}             # canonical url -> page record
        self.order: list[str] = []                   # canonical urls in citation order: [1] = order[0]
        self.findings: dict[str, list] = {}          # sub-topic -> [{text, sources}]
        self.done_subtopics: list[str] = []
        self.errors: list[str] = []
        self.engine_note = ""
        self.stop_reason = ""
        self.rounds = 0

    # ---- citation numbers: stable for the whole session ----
    def sid(self, key: str) -> int:
        if key not in self.order:
            self.order.append(key)
        return self.order.index(key) + 1

    def known_urls(self) -> set[str]:
        urls = set(self.pages)
        for q in self.queries.values():
            urls.update(q.get("urls", []))
        for p in self.pages.values():
            urls.update(p.get("links", []))
        return urls

    # ---- cache ----
    def cached_search(self, query: str, kind: str, time_sensitive: bool):
        rec = self.queries.get(norm_key(query) + "|" + kind)
        if not rec:
            return None
        ttl = TTL_SEARCH_FRESH if time_sensitive else TTL_SEARCH_STABLE
        return rec if time.time() - rec["ts"] <= ttl and rec.get("results") else None

    def remember_search(self, query: str, kind: str, engine: str, results: list[dict]):
        slim = [{k: r.get(k, "") for k in ("title", "url", "snippet", "date", "kind", "credibility", "domain", "stale", "freshness", "also", "key", "score", "relevance", "age_days")}
                for r in results[:12]]
        self.queries[norm_key(query) + "|" + kind] = {"query": query, "kind": kind, "engine": engine, "ts": time.time(),
                                                      "urls": [r.get("key") or r.get("url") for r in slim], "results": slim}

    def cached_page(self, key: str, time_sensitive: bool):
        rec = self.pages.get(key)
        if not rec or rec.get("status") != "ok":
            return None
        ttl = TTL_PAGE_FRESH if time_sensitive else TTL_PAGE_STABLE
        return rec if time.time() - rec.get("fetched", 0) <= ttl else None

    # ---- budget ----
    def left(self) -> dict:
        b = self.budget
        return {"searches": b["max_searches"] - self.used["searches"], "pages": b["max_pages"] - self.used["pages"],
                "seconds": b["max_seconds"] - self.used["seconds"], "chars": b["max_chars"]}

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in ("id", "topic", "subtopics", "sub_queries", "status", "created", "updated", "budget", "used", "queries", "pages", "order",
                                              "findings", "done_subtopics", "errors", "engine_note", "stop_reason", "rounds")}

    @classmethod
    def from_dict(cls, data: dict) -> "Session":
        s = cls(str(data.get("topic", "")), data.get("budget") or DEFAULT_BUDGET)
        for key in ("id", "subtopics", "sub_queries", "status", "created", "updated", "used", "queries", "pages", "order", "findings", "done_subtopics",
                    "errors", "engine_note", "stop_reason", "rounds"):
            if key in data:
                setattr(s, key, data[key])
        s.used.setdefault("seconds", 0.0)
        return s


class ResearchStore:
    """One current session on disk (JSON). All access is guarded by a lock: tools run in the agent thread, the UI may clear from another."""

    def __init__(self, data_dir=None):
        self._lock = threading.RLock()
        self._dir = Path(data_dir) / "web_research" if data_dir else None
        self._current: Session | None = None
        self._loaded = False

    @property
    def _file(self) -> Path | None:
        return self._dir / "session.json" if self._dir else None

    def _load(self):
        if self._loaded:
            return
        self._loaded = True
        f = self._file
        if not f or not f.exists():
            return
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            s = Session.from_dict(data)
            if time.time() - float(s.updated or 0) <= SESSION_TTL:
                if s.status == RUNNING:
                    s.status = PAUSED                              # the program was closed in the middle: it is only paused, and can be continued
                self._current = s
            else:
                f.unlink(missing_ok=True)
        except (OSError, ValueError, TypeError, KeyError):
            self._current = None

    def current(self) -> Session | None:
        with self._lock:
            self._load()
            return self._current

    def start(self, topic: str, budget: dict) -> Session:
        with self._lock:
            self._load()
            self._current = Session(topic, budget)
            self.save()
            return self._current

    def save(self):
        with self._lock:
            s, f = self._current, self._file
            if s is None or f is None:
                return
            s.updated = time.time()
            try:
                f.parent.mkdir(parents=True, exist_ok=True)
                fd, tmp = tempfile.mkstemp(dir=str(f.parent), suffix=".tmp")
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    json.dump(s.to_dict(), fh, ensure_ascii=False)
                os.replace(tmp, f)
            except OSError:
                pass                                              # the research still works from memory; it just cannot be resumed after a restart

    def clear(self):
        with self._lock:
            self._current, self._loaded = None, True
            f = self._file
            if f:
                try:
                    f.unlink(missing_ok=True)
                except OSError:
                    pass
