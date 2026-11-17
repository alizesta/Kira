"""Usage ledger: one row per model request (and per embedding request), kept in DATA_DIR/kira_usage.sqlite3.

Nothing is guessed:
  * tokens are stored only when the provider reported them (NULL = Unknown, never an estimate from text length);
  * cost_reported is a price the provider itself returned (e.g. OpenRouter); cost_estimated needs reported tokens AND a price the user wrote in
    settings["model_prices"]; otherwise the cost is Unknown;
  * prompts, replies and keys are never stored - only numbers, ids and error kinds.

Limits (settings["usage_limits"]): keys "role:<role>" or "provider:<id>", values {"requests_per_day": N, "tokens_per_day": N, "action": "warn"|"block"}.
  * "block" on a provider removes its routes from failover, but only while another usable route exists - the conversation is never cut off;
  * "block" on an expensive role (deep / reflection / memory) sends it back to the normal (surface) path; the surface role is only ever warned about.

Show it: type /usage in the chat, or run `python -m kira.usage [days]`.
"""
from __future__ import annotations

import contextlib
import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path

DB_NAME = "kira_usage.sqlite3"
LIMIT_CACHE_SECONDS = 20
KEEP_DAYS = 400
ROLES_BLOCKABLE = ("deep", "reflection", "memory")

_lock = threading.RLock()
_settings: dict = {}
_cache: dict = {}
_db_path: Path | None = None
_ready = False

COLUMNS = ("ts", "request_id", "role", "provider", "model", "route_id", "status", "failovers", "failover_causes", "connect_ms", "first_token_ms",
           "total_ms", "tokens_in", "tokens_out", "tokens_cache", "tokens_reasoning", "tokens_source", "cost_reported", "cost_estimated", "cost_kind",
           "error_kind")


# ---------------------------------------------------------------------------------------------- parsing what a provider reported
def _num(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value if value >= 0 else None


def parse_usage(obj):
    """Token / cost numbers found in ONE decoded provider JSON object (any known shape), or None. Only reported values are returned."""
    if not isinstance(obj, dict):
        return None
    raw = None
    for holder in (obj, obj.get("result"), obj.get("x_groq")):
        if isinstance(holder, dict) and isinstance(holder.get("usage"), dict):
            raw = holder["usage"]
            break
    out = {}
    if raw is not None:
        details_in = raw.get("prompt_tokens_details") if isinstance(raw.get("prompt_tokens_details"), dict) else {}
        details_out = raw.get("completion_tokens_details") if isinstance(raw.get("completion_tokens_details"), dict) else {}
        out = {"tokens_in": _num(raw.get("prompt_tokens", raw.get("input_tokens"))),
               "tokens_out": _num(raw.get("completion_tokens", raw.get("output_tokens"))),
               "tokens_cache": _num(details_in.get("cached_tokens")),
               "tokens_reasoning": _num(details_out.get("reasoning_tokens")),
               "cost_reported": _num(raw.get("cost"))}
    meta = obj.get("usageMetadata")                                                  # Gemini native shape
    if isinstance(meta, dict):
        out = {"tokens_in": _num(meta.get("promptTokenCount")), "tokens_out": _num(meta.get("candidatesTokenCount")),
               "tokens_cache": _num(meta.get("cachedContentTokenCount")), "tokens_reasoning": _num(meta.get("thoughtsTokenCount")), "cost_reported": None}
    out = {k: v for k, v in out.items() if v is not None}
    return out or None


def merge_usage(current, new):
    """Later chunks of a stream carry the totals: keep the newest value of every key."""
    if not new:
        return current
    merged = dict(current or {})
    merged.update(new)
    return merged


# ---------------------------------------------------------------------------------------------- storage
def configure(settings) -> None:
    global _settings
    _settings = settings if isinstance(settings, dict) else {}
    _cache.clear()


def _path() -> Path:
    global _db_path
    if _db_path is None:
        from .config import DATA_DIR
        _db_path = Path(DATA_DIR) / DB_NAME
    return _db_path


def _connect() -> sqlite3.Connection:
    global _ready
    con = sqlite3.connect(str(_path()), timeout=5)
    con.row_factory = sqlite3.Row
    if not _ready:
        con.execute("""CREATE TABLE IF NOT EXISTS requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, request_id TEXT, role TEXT, provider TEXT, model TEXT, route_id TEXT,
            status TEXT, failovers INTEGER, failover_causes TEXT, connect_ms INTEGER, first_token_ms INTEGER, total_ms INTEGER,
            tokens_in INTEGER, tokens_out INTEGER, tokens_cache INTEGER, tokens_reasoning INTEGER, tokens_source TEXT,
            cost_reported REAL, cost_estimated REAL, cost_kind TEXT, error_kind TEXT)""")
        con.execute("CREATE INDEX IF NOT EXISTS idx_req_ts ON requests(ts)")
        con.execute("DELETE FROM requests WHERE ts < ?", (time.time() - KEEP_DAYS * 86400,))
        con.commit()
        _ready = True
    return con


def _price(provider, model):
    prices = _settings.get("model_prices")
    if not isinstance(prices, dict):
        return None
    for key in (f"{provider}:{model}", str(model), str(provider)):
        entry = prices.get(key)
        if isinstance(entry, dict) and _num(entry.get("input_per_million")) is not None and _num(entry.get("output_per_million")) is not None:
            return entry
    return None


def _cost(rec: dict):
    """(cost_reported, cost_estimated, cost_kind). kind: reported | estimated | local | unknown."""
    reported = _num(rec.get("cost_reported"))
    if reported is not None:
        return reported, None, "reported"
    if rec.get("kind") == "local":
        return None, None, "local"
    tin, tout = _num(rec.get("tokens_in")), _num(rec.get("tokens_out"))
    price = _price(rec.get("provider"), rec.get("model"))
    if price is not None and tin is not None and tout is not None:
        cached = _num(rec.get("tokens_cache")) or 0
        cache_price = _num(price.get("cache_per_million"))
        billable_in = (tin - cached) if cache_price is not None and cached <= tin else tin
        est = billable_in * price["input_per_million"] / 1e6 + tout * price["output_per_million"] / 1e6
        if cache_price is not None and cached <= tin:
            est += cached * cache_price / 1e6
        return None, est, "estimated"
    return None, None, "unknown"


def record(rec: dict) -> None:
    """Write one request. Never raises: the ledger must not be able to break a chat."""
    try:
        reported, estimated, kind = _cost(rec)
        causes = rec.get("failover_causes")
        row = (time.time(), rec.get("request_id"), rec.get("role") or "surface", rec.get("provider"), rec.get("model"), rec.get("route_id"),
               rec.get("status"), int(rec.get("failovers") or 0), ",".join(causes) if isinstance(causes, (list, tuple)) else causes,
               rec.get("connect_ms"), rec.get("first_token_ms"), rec.get("total_ms"),
               _num(rec.get("tokens_in")), _num(rec.get("tokens_out")), _num(rec.get("tokens_cache")), _num(rec.get("tokens_reasoning")),
               rec.get("tokens_source") if _num(rec.get("tokens_in")) is not None or _num(rec.get("tokens_out")) is not None else None,
               reported, estimated, kind, rec.get("error_kind"))
        with _lock, contextlib.closing(_connect()) as con:
            con.execute(f"INSERT INTO requests ({','.join(COLUMNS)}) VALUES ({','.join('?' * len(COLUMNS))})", row)
            con.commit()
        _cache.clear()
    except Exception:                                                                # noqa: BLE001
        pass


# ---------------------------------------------------------------------------------------------- limits
def _day_start() -> float:
    now = datetime.now()
    return now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()


def _today(kind: str, name: str):
    """(requests, known_tokens) today for role / provider; cached for a few seconds because routes are listed often."""
    key = (kind, name)
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < LIMIT_CACHE_SECONDS:
        return hit[1]
    column = "role" if kind == "role" else "provider"
    try:
        with _lock, contextlib.closing(_connect()) as con:
            row = con.execute(f"SELECT COUNT(*), COALESCE(SUM(COALESCE(tokens_in,0)+COALESCE(tokens_out,0)),0) FROM requests "
                              f"WHERE ts >= ? AND {column} = ?", (_day_start(), name)).fetchone()
        value = (int(row[0]), int(row[1]))
    except Exception:                                                                # noqa: BLE001
        value = (0, 0)
    _cache[key] = (time.monotonic(), value)
    return value


def limit_state(kind: str, name: str) -> str:
    """'' (no limit / under it) | 'warn' | 'block'."""
    limits = _settings.get("usage_limits")
    cfg = limits.get(f"{kind}:{name}") if isinstance(limits, dict) else None
    if not isinstance(cfg, dict):
        return ""
    reqs, toks = _today(kind, name)
    over = ((_num(cfg.get("requests_per_day")) is not None and reqs >= cfg["requests_per_day"])
            or (_num(cfg.get("tokens_per_day")) is not None and toks >= cfg["tokens_per_day"]))
    if not over:
        return ""
    return "block" if str(cfg.get("action", "warn")).lower() == "block" else "warn"


def role_allowed(role) -> bool:
    """False when an expensive role reached a blocking limit. The surface role (the conversation itself) is always allowed."""
    try:
        return not (role in ROLES_BLOCKABLE and limit_state("role", role) == "block")
    except Exception:                                                                # noqa: BLE001
        return True


def apply_limits(routes, eligible_fn):
    """Routes minus those of a provider over a blocking limit - unless that would leave no usable route (then nothing is removed)."""
    try:
        blocked = {p for p in {r["provider"] for r in routes} if limit_state("provider", p) == "block"}
        if not blocked:
            return routes
        kept = [r for r in routes if r["provider"] not in blocked]
        return kept if any(eligible_fn(r) for r in kept) else routes
    except Exception:                                                                # noqa: BLE001
        return routes


# ---------------------------------------------------------------------------------------------- report
def _fmt(value, unit=""):
    return "Unknown" if value is None else f"{value:,}{unit}"


def report(days: int = 1) -> str:
    days = max(1, min(int(days), 365))
    since = time.time() - days * 86400 if days > 1 else _day_start()
    try:
        with _lock, contextlib.closing(_connect()) as con:
            rows = con.execute("""SELECT role, provider, model, COUNT(*) n, SUM(status='success') ok, SUM(status NOT IN ('success','stopped')) bad,
                SUM(failovers) fo, SUM(tokens_in) tin, SUM(tokens_out) tout,
                SUM(tokens_in IS NULL AND tokens_out IS NULL) unk, SUM(cost_reported) cr, SUM(cost_estimated) ce,
                SUM(cost_kind='unknown') cu, AVG(first_token_ms) ft FROM requests WHERE ts >= ?
                GROUP BY role, provider, model ORDER BY n DESC LIMIT 25""", (since,)).fetchall()
    except Exception as exc:                                                         # noqa: BLE001
        return f"خواندن آمار مصرف ممکن نشد: {exc}"
    title = "مصرف امروز" if days == 1 else f"مصرف {days} روز اخیر"
    if not rows:
        return f"{title}: هنوز درخواستی ثبت نشده است."
    lines = [title + " (عددهای Unknown یعنی سرویس گزارش نکرده؛ هیچ عددی حدس زده نمی‌شود):"]
    for r in rows:
        cost = []
        if r["cr"] is not None:
            cost.append(f"هزینه‌ی گزارش‌شده {r['cr']:.4f}")
        if r["ce"] is not None:
            cost.append(f"برآورد {r['ce']:.4f} (از قیمت تنظیم‌شده)")
        if not cost:
            cost.append("هزینه Unknown" if r["cu"] else "هزینه: محلی")
        lines.append(f"- [{r['role']}] {r['provider']}/{r['model']}: {r['n']} درخواست ({r['ok'] or 0} موفق، {r['bad'] or 0} ناموفق، {r['fo'] or 0} failover) | "
                     f"توکن ورودی {_fmt(r['tin'])} / خروجی {_fmt(r['tout'])}" + (f" ({r['unk']} درخواست بدون گزارش توکن)" if r["unk"] else "")
                     + " | " + "، ".join(cost) + (f" | اولین توکن {int(r['ft'])}ms" if r["ft"] else ""))
    limits = _settings.get("usage_limits")
    if isinstance(limits, dict):
        for key in limits:
            kind, _, name = key.partition(":")
            if kind in ("role", "provider") and (state := limit_state(kind, name)):
                lines.append(f"⚠ محدودیت «{key}» پر شده ({'مسدود' if state == 'block' else 'هشدار'}).")
    return "\n".join(lines)


def parse_command(text: str) -> int | None:
    """Return the requested usage period for an existing /usage command, or None when unmatched."""
    parts = str(text or "").strip().split()
    if not parts or parts[0].lower() not in ("/usage", "/مصرف"):
        return None
    return int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 1


def handle_command(text: str):
    """Compatibility entry point for '/usage' and '/مصرف'."""
    days = parse_command(text)
    return report(days) if days is not None else None


def install(settings) -> None:
    """Hook the ledger into the embedding path and the brain's background roles. Safe to call more than once."""
    configure(settings)
    with contextlib.suppress(Exception):
        from . import evidence_memory
        evidence_memory.usage_hook = lambda rec: record({**rec, "tokens_source": "provider"})
    with contextlib.suppress(Exception):
        from . import brain
        brain.budget_check = role_allowed


if __name__ == "__main__":
    import sys
    try:
        from .config import load_settings
        configure(load_settings())
    except Exception:                                                                # noqa: BLE001
        pass
    print(report(int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 1))
