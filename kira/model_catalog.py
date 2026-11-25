"""Qt-free view model for the "مدل‌ها" box: which model belongs to which tab, archiving, saved test results.

A model's *enabled* state is its Route (see api_manager.set_model_enabled); the registry only knows what the service
reported (status, free). What this module adds:

* ``settings["model_archive"]``  {provider id: [model ids]} - models the user moved to the "منسوخ / غیرفعال" tab.
* ``settings["model_tests"]``    {"provider::model": {ok, ms, at, message}} - the last quick test of each model.

Tabs (a model is in exactly one of free / paid / archived, and also in "active" when its Route is on):

* active    - Route enabled (shown in Route priority order)
* free      - the service says it is free
* paid      - the service says it is NOT free, or does not say (price unknown is never shown as free)
* archived  - moved there by the user, gone from the service, or switched off automatically
"""
from __future__ import annotations

import time

from . import api_manager
from . import routes as route_model

TAB_ACTIVE, TAB_FREE, TAB_PAID, TAB_ARCHIVED = "active", "free", "paid", "archived"
TABS = (TAB_ACTIVE, TAB_FREE, TAB_PAID, TAB_ARCHIVED)
TAB_TITLES = {
    TAB_ACTIVE: "فعال",
    TAB_FREE: "رایگان",
    TAB_PAID: "غیررایگان / نامشخص",
    TAB_ARCHIVED: "منسوخ / غیرفعال",
}

_NON_CHAT_TOKENS = ("tts", "text-to-speech", "embedding", "whisper", "speech-to-text", "speech", "transcription", "audio", "asr")


def is_chat_model(model_id, meta=None):
    """Chat models only: audio / embedding models never belong in the Route list."""
    if (meta or {}).get("text") == "No":
        return False
    low = str(model_id).lower()
    return not any(token in low for token in _NON_CHAT_TOKENS)


def _key(provider, model):
    return f"{provider}::{model}"


# ---------------------------------------------------------------- archive
def is_archived(settings, provider, model):
    return model in ((settings.get("model_archive") or {}).get(provider) or ())


def archive_model(settings, provider, model):
    """Move a model to the archived tab: remembered, and its Route (if any) is switched off, never deleted."""
    bucket = settings.setdefault("model_archive", {}).setdefault(provider, [])
    if model not in bucket:
        bucket.append(model)
        bucket.sort()
    for route in route_model.get_routes(settings):
        if route["provider"] == provider and route["model"] == model:
            route_model.update_route(settings, route["id"], enabled=False)
            if settings.get("manual_route_id") == route["id"]:
                settings["manual_route_id"] = ""          # a pinned model that is archived must not stay pinned


def restore_model(settings, provider, model):
    """Take a model out of the archived tab. It comes back switched OFF; the user turns it on again if wanted."""
    bucket = (settings.get("model_archive") or {}).get(provider)
    if bucket and model in bucket:
        bucket.remove(model)
        if not bucket:
            settings["model_archive"].pop(provider, None)
    (settings.get("route_notes") or {}).pop(_route_id(settings, provider, model), None)    # an auto-disable note no longer applies


def _route_id(settings, provider, model):
    for route in route_model.get_routes(settings):
        if route["provider"] == provider and route["model"] == model:
            return route["id"]
    return ""


def forget_provider(settings, provider):
    """Drop the archive and test records of a deleted API."""
    (settings.get("model_archive") or {}).pop(provider, None)
    tests = settings.get("model_tests") or {}
    for key in [k for k in tests if k.startswith(provider + "::")]:
        tests.pop(key, None)


# ---------------------------------------------------------------- test results
def record_test(settings, provider, model, ok, ms=None, message="", now=None):
    settings.setdefault("model_tests", {})[_key(provider, model)] = {
        "ok": bool(ok), "ms": None if ms is None else int(ms),
        "at": int(now if now is not None else time.time()), "message": str(message or "")[:300]}


def test_result(settings, provider, model):
    return (settings.get("model_tests") or {}).get(_key(provider, model))


# ---------------------------------------------------------------- rows
def _price(free):
    return "free" if free is True else "paid" if free is False else "unknown"


def _archive_reason(settings, provider, model, meta, route):
    if is_archived(settings, provider, model):
        return "به منسوخ منتقل شده"
    if meta.get("status") == "unavailable":
        return "دیگر در سرویس نیست"
    if route is not None and not route.get("enabled", True):
        note = route_model.route_note(settings, route["id"])
        if note:
            return "خاموش‌شده خودکار: " + note
    return ""


def model_rows(settings, *, capabilities=None):
    """Every chat model of every registered API as a flat list of dicts (see module doc for the tab rules)."""
    api_manager.ensure_registry(settings, capabilities)
    routes = route_model.get_routes(settings)
    order = {(r["provider"], r["model"]): i for i, r in enumerate(routes)}
    by_key = {(r["provider"], r["model"]): r for r in routes}
    rows = []
    for pid, entry in api_manager.registry(settings, capabilities).items():
        cfg = (settings.get("providers") or {}).get(pid, {})
        label = route_model.provider_label(pid, cfg)
        for mid, meta in (entry.get("models") or {}).items():
            if not is_chat_model(mid, meta):
                continue
            route = by_key.get((pid, mid))
            reason = _archive_reason(settings, pid, mid, meta, route)
            enabled = bool(route and route.get("enabled", True)) and not reason
            tabs = [TAB_ARCHIVED] if reason else [TAB_FREE if meta.get("free") is True else TAB_PAID]
            if enabled:
                tabs.insert(0, TAB_ACTIVE)
            rows.append({
                "provider": pid, "provider_label": label, "model": mid, "price": _price(meta.get("free")),
                "free": meta.get("free"), "status": meta.get("status") or "unknown", "enabled": enabled,
                "route_id": route["id"] if route else "", "reason": reason, "tabs": tabs,
                "restorable": meta.get("status") != "unavailable",        # a model the service dropped cannot come back by hand
                "test": test_result(settings, pid, mid),
                "order": order.get((pid, mid), 10 ** 6),
            })
    # Ollama models are discovered from the local daemon, not the cloud API registry.
    # Their Route records are the local catalogue; expose them in the same table so the
    # existing per-model switch can enable/disable them through the normal Route service.
    known = {(row["provider"], row["model"]) for row in rows}
    for route in routes:
        pid, mid = route.get("provider"), route.get("model")
        if pid != "ollama" or not mid or not is_chat_model(mid) or (pid, mid) in known:
            continue
        meta = {"free": True, "status": "available"}
        reason = _archive_reason(settings, pid, mid, meta, route)
        enabled = bool(route.get("enabled", True)) and not reason
        tabs = [TAB_ARCHIVED] if reason else [TAB_FREE]
        if enabled:
            tabs.insert(0, TAB_ACTIVE)
        cfg = (settings.get("providers") or {}).get(pid, {})
        rows.append({
            "provider": pid, "provider_label": route_model.provider_label(pid, cfg),
            "model": mid, "price": "free", "free": True, "status": "available",
            "enabled": enabled, "route_id": route["id"], "reason": reason, "tabs": tabs,
            "restorable": True, "test": test_result(settings, pid, mid),
            "order": order.get((pid, mid), 10 ** 6),
        })
        known.add((pid, mid))

    rows.sort(key=lambda r: (r["provider_label"].casefold(), r["model"].casefold()))
    return rows


def rows_for_tab(rows, tab):
    selected = [r for r in rows if tab in r["tabs"]]
    if tab == TAB_ACTIVE:
        selected.sort(key=lambda r: r["order"])          # same order the router tries them
    return selected


def tab_counts(rows):
    return {tab: sum(1 for r in rows if tab in r["tabs"]) for tab in TABS}
