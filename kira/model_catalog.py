"""Qt-free view model for the "مدل‌ها" box: which model belongs to which tab, archiving, saved test results.

A model's *enabled* state is its Route (see api_manager.set_model_enabled); the registry only knows what the service
reported (status, free). What this module adds:

* ``settings["model_archive"]``  {provider id: [model ids]} - models the user moved to the "منسوخ / غیرفعال" tab.
* DetectedCapabilities ``model_tests`` stores the last quick test observation for each model.

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
from .app.detected_capabilities import DetectedCapabilities

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


def restore_model(settings, provider, model, *, capabilities: DetectedCapabilities):
    """Take a model out of the archived tab. It comes back switched OFF; the user turns it on again if wanted."""
    bucket = (settings.get("model_archive") or {}).get(provider)
    if bucket and model in bucket:
        bucket.remove(model)
        if not bucket:
            settings["model_archive"].pop(provider, None)
    capabilities.mapping_pop("route_notes", _route_id(settings, provider, model), None)


def _route_id(settings, provider, model):
    for route in route_model.get_routes(settings):
        if route["provider"] == provider and route["model"] == model:
            return route["id"]
    return ""


def forget_provider(settings, provider, *, capabilities: DetectedCapabilities):
    """Drop user archive choices and process-local test observations for a deleted API."""
    (settings.get("model_archive") or {}).pop(provider, None)
    store = capabilities
    tests = store.get("model_tests") or {}
    for key in [k for k in tests if k.startswith(provider + "::")]:
        tests.pop(key, None)


# ---------------------------------------------------------------- test results
def record_test(settings, provider, model, ok, ms=None, message="", now=None, *, capabilities: DetectedCapabilities):
    store = capabilities
    store.setdefault("model_tests", {})[_key(provider, model)] = {
        "ok": bool(ok), "ms": None if ms is None else int(ms),
        "at": int(now if now is not None else time.time()), "message": str(message or "")[:300]}


def test_result(settings, provider, model, *, capabilities: DetectedCapabilities):
    store = capabilities
    return (store.get("model_tests") or {}).get(_key(provider, model))


# ---------------------------------------------------------------- rows
def _price(free):
    return "free" if free is True else "paid" if free is False else "unknown"


def _archive_reason(settings, provider, model, meta, route, *, capabilities: DetectedCapabilities):
    if is_archived(settings, provider, model):
        return "به منسوخ منتقل شده"
    if meta.get("status") == "unavailable":
        return "دیگر در سرویس نیست"
    if route is not None and not route.get("enabled", True):
        note = route_model.route_note(settings, route["id"], capabilities=capabilities)
        if note:
            return "خاموش‌شده خودکار: " + note
    return ""


def model_rows(settings, *, capabilities: DetectedCapabilities):
    """Every chat model of every registered API, grouped by shared cloud model identity for display."""
    api_manager.ensure_registry(settings, capabilities)
    routes = route_model.get_routes(settings)
    order = {(r["provider"], r["model"]): i for i, r in enumerate(routes)}
    by_key = {(r["provider"], r["model"]): r for r in routes}
    rows = []
    for pid, entry in api_manager.registry(capabilities).items():
        cfg = (settings.get("providers") or {}).get(pid, {})
        label = route_model.provider_label(pid, cfg)
        for mid, meta in (entry.get("models") or {}).items():
            if not is_chat_model(mid, meta):
                continue
            route = by_key.get((pid, mid))
            reason = _archive_reason(settings, pid, mid, meta, route, capabilities=capabilities)
            enabled = bool(route and route.get("enabled", True)) and not reason
            tabs = [TAB_ARCHIVED] if reason else [TAB_FREE if meta.get("free") is True else TAB_PAID]
            if enabled:
                tabs.insert(0, TAB_ACTIVE)
            rows.append({
                "provider": pid, "provider_label": label, "model": mid, "price": _price(meta.get("free")),
                "free": meta.get("free"), "status": meta.get("status") or "unknown", "enabled": enabled,
                "route_id": route["id"] if route else "", "reason": reason, "tabs": tabs,
                "restorable": meta.get("status") != "unavailable",        # a model the service dropped cannot come back by hand
                "test": test_result(settings, pid, mid, capabilities=capabilities),
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
        reason = _archive_reason(settings, pid, mid, meta, route, capabilities=capabilities)
        enabled = bool(route.get("enabled", True)) and not reason
        tabs = [TAB_ARCHIVED] if reason else [TAB_FREE]
        if enabled:
            tabs.insert(0, TAB_ACTIVE)
        cfg = (settings.get("providers") or {}).get(pid, {})
        rows.append({
            "provider": pid, "provider_label": route_model.provider_label(pid, cfg),
            "model": mid, "price": "free", "free": True, "status": "available",
            "enabled": enabled, "route_id": route["id"], "reason": reason, "tabs": tabs,
            "restorable": True, "test": test_result(settings, pid, mid, capabilities=capabilities),
            "order": order.get((pid, mid), 10 ** 6),
        })
        known.add((pid, mid))

    rows = group_model_rows(rows, settings)
    rows.sort(key=lambda r: (r["model"].casefold(), r["provider_label"].casefold()))
    return rows


def group_model_rows(rows, settings):
    """Collapse identical cloud models across APIs for display, retaining provider-specific members.

    Each member continues to own its original provider/model ID, Route, quota and test/archive state.
    Only the row identity and display name are normalized; local models remain isolated.
    """
    grouped = {}
    for row in rows:
        provider = str(row.get("provider") or "")
        cfg = (settings.get("providers") or {}).get(provider, {})
        is_cloud = route_model.provider_kind(provider, cfg) == "cloud"
        display_model = (
            route_model.normalize_display_model_id(row.get("model"), provider, cfg)
            if is_cloud else str(row.get("model") or "")
        )
        if is_cloud and display_model:
            key = ("cloud", display_model.casefold())
        else:
            key = ("provider", provider, str(row.get("model") or "").casefold())
        grouped.setdefault(key, []).append((row, display_model))

    result = []
    for members_with_names in grouped.values():
        members = [dict(item[0]) for item in members_with_names]
        display_model = members_with_names[0][1]
        provider_ids = list(dict.fromkeys(member["provider"] for member in members))
        provider_labels = list(dict.fromkeys(member["provider_label"] for member in members))
        member_keys = tuple((member["provider"], member["model"]) for member in members)

        available_members = [
            member for member in members if TAB_ARCHIVED not in member.get("tabs", [])
        ]
        archived_members = [
            member for member in members if TAB_ARCHIVED in member.get("tabs", [])
        ]
        # A grouped model belongs to exactly one price/archive category. Mixed
        # provider prices are conservatively classified as paid/unknown rather
        # than duplicating the same model in both Free and Paid tabs.
        if not available_members:
            category_tab = TAB_ARCHIVED
        elif all(member.get("price") == "free" for member in available_members):
            category_tab = TAB_FREE
        else:
            category_tab = TAB_PAID
        tabs = [category_tab]
        if any(bool(member.get("enabled")) for member in available_members):
            tabs.insert(0, TAB_ACTIVE)

        prices = {member["price"] for member in available_members} or {
            member["price"] for member in members
        }
        price = next(iter(prices)) if len(prices) == 1 else "unknown"
        price_details = "؛ ".join(
            f'{member["provider_label"]}: {member["price"]}'
            for member in members
        )
        reasons = [
            f'{member["provider_label"]}: {member["reason"]}'
            for member in members if member.get("reason")
        ]

        tested = [member["test"] for member in members if member.get("test")]
        if len(members) == 1:
            combined_test = members[0].get("test")
        elif not tested:
            combined_test = None
        else:
            times = [int(item["ms"]) for item in tested if item.get("ms") is not None]
            complete = len(tested) == len(members)
            combined_test = {
                "ok": all(bool(item.get("ok")) for item in tested) if complete else None,
                "ms": round(sum(times) / len(times)) if times else None,
                "at": max(int(item.get("at") or 0) for item in tested),
                "message": (
                    f'{len(tested)}/{len(members)} API تست شده؛ '
                    f'{sum(1 for item in tested if item.get("ok"))} موفق، '
                    f'{sum(1 for item in tested if not item.get("ok"))} ناموفق'
                ),
            }

        first = dict(members[0])
        first.update({
            "model": display_model,
            "provider_label": (
                (" + ".join(provider_labels) + f" · {len(members)} API")
                if len(members) > 1 else provider_labels[0]
            ),
            "provider_ids": provider_ids,
            "provider_labels": provider_labels,
            "member_keys": member_keys,
            "members": members,
            "member_count": len(members),
            "enabled": any(bool(member.get("enabled")) for member in available_members),
            "tabs": tabs,
            "category_tab": category_tab,
            "price": price,
            "free": (
                available_members[0].get("free")
                if available_members and len({member.get("free") for member in available_members}) == 1
                else None
            ),
            "toggle_member_keys": tuple(
                (member["provider"], member["model"]) for member in available_members
            ),
            "archived_member_keys": tuple(
                (member["provider"], member["model"]) for member in archived_members
            ),
            "archived_member_count": len(archived_members),
            "price_tooltip": (
                "وضعیت هزینه در APIها: " + price_details
                if len(prices) > 1 else price_details
            ),
            "status": "available" if any(
                member.get("status") == "available" for member in available_members
            ) else members[0].get("status", "unknown"),
            "route_id": first.get("route_id", ""),
            "reason": "؛ ".join(reasons),
            "restorable": any(member.get("restorable") for member in archived_members),
            "test": combined_test,
            "order": min(int(member.get("order", 10 ** 6)) for member in members),
        })
        result.append(first)
    return result


def rows_for_tab(rows, tab):
    selected = [r for r in rows if tab in r["tabs"]]
    if tab == TAB_ACTIVE:
        selected.sort(key=lambda r: r["order"])          # same order the router tries them
    return selected


def tab_counts(rows):
    return {tab: sum(1 for r in rows if tab in r["tabs"]) for tab in TABS}
