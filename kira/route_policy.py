"""Deterministic route policy, independent from provider health and execution state."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


LOCAL_ONLY = "local_only"
CLOUD_PERMITTED = "cloud_permitted"
_PROTECTED_ROLES = frozenset({"surface", "deep", "reflection", "memory"})


def normalize_network_policy(value):
    """Normalize network permission using a fail-closed default.

    Only the explicit cloud_permitted value can authorize Cloud routes. Missing,
    empty, malformed, or future/unknown values are treated as local_only.
    """
    if isinstance(value, str) and value.strip().lower() == CLOUD_PERMITTED:
        return CLOUD_PERMITTED
    return LOCAL_ONLY


@dataclass(frozen=True)
class RouteDecision:
    route_id: str
    allowed: bool
    reason: str


class RoutePolicyEngine:
    """Resolve network, role, vision and manual-priority policy into an ordered route plan.

    Provider health, cooldown, quota backoff and retry execution are deliberately
    not owned here. They are runtime gates applied by the router after policy selection.
    """

    def select(
        self,
        routes,
        settings,
        *,
        role="",
        preferred_route_id="",
        vision_only=False,
        provider_cfg: Callable,
        provider_kind: Callable,
        is_google: Callable,
        supports_vision: Callable,
    ):
        settings = settings if isinstance(settings, dict) else {}
        original_routes = list(routes)
        decisions = {}

        def filter_routes(items, predicate, reason):
            kept = []
            for item in items:
                rid = str(item.get("id") or "")
                if predicate(item):
                    kept.append(item)
                else:
                    decisions[rid] = reason
            return kept

        network_policy = normalize_network_policy(settings.get("network_policy"))
        if network_policy == LOCAL_ONLY:
            routes = filter_routes(
                routes,
                lambda route: provider_kind(
                    route.get("provider"), provider_cfg(route)
                ) == "local",
                "blocked_by_local_only",
            )

        # Known roles are security boundaries. A missing or malformed allowlist
        # for one of them grants no providers. Unknown/general roles retain their
        # existing unrestricted-by-role behavior unless explicitly configured.
        role_allowlists = settings.get("role_provider_allowlist")
        has_role_allowlist = (
            isinstance(role_allowlists, dict) and role in role_allowlists
        )
        role_is_restricted = has_role_allowlist or role in _PROTECTED_ROLES
        raw_allowed = (
            role_allowlists.get(role)
            if has_role_allowlist
            else None
        )
        allow = (
            {
                str(value).strip().lower()
                for value in raw_allowed
                if str(value).strip()
            }
            if isinstance(raw_allowed, (list, tuple, set, frozenset))
            else set()
        )

        def provider_allowed(route):
            provider = str(route.get("provider") or "").strip().lower()
            return (
                provider in allow
                or (
                    "google" in allow
                    and is_google(route.get("provider"), provider_cfg(route))
                )
            )

        if role_is_restricted:
            routes = filter_routes(
                routes,
                provider_allowed,
                "blocked_by_role_provider_allowlist",
            )

        # Vision's Google-only role rule is an additional restriction, never an
        # override of the role allowlist or the network privacy boundary.
        if vision_only and role in ("surface", "deep"):
            routes = filter_routes(
                routes,
                lambda route: is_google(
                    route.get("provider"), provider_cfg(route)
                ),
                "vision_provider_not_google",
            )

        model_allowlists = settings.get("role_route_models")
        if not vision_only and isinstance(model_allowlists, dict) and role in model_allowlists:
            raw_models = model_allowlists.get(role)
            allowed_models = (
                {
                    str(value).strip().lower()
                    for value in raw_models
                    if str(value).strip()
                }
                if isinstance(raw_models, (list, tuple, set, frozenset))
                else set()
            )
            # Surface may use any configured Ollama route when Ollama itself is
            # explicitly allowlisted; all non-Ollama routes remain model-limited.
            local_surface_routes = role == "surface" and "ollama" in allow
            routes = filter_routes(
                routes,
                lambda route: (
                    local_surface_routes
                    and str(route.get("provider") or "").strip().lower() == "ollama"
                ) or str(route.get("model") or "").strip().lower() in allowed_models,
                "blocked_by_role_model_allowlist",
            )

        surface_cloud_fallback = (
            role == "surface"
            and not vision_only
            and network_policy == CLOUD_PERMITTED
        )
        if surface_cloud_fallback:
            # Local-first ordering is only an ordering rule. Every route has
            # already passed the same network and role-policy filters above.
            local_routes = [
                route for route in routes
                if provider_kind(
                    route.get("provider"), provider_cfg(route)
                ) == "local"
            ]
            cloud_routes = [
                route for route in routes
                if provider_kind(
                    route.get("provider"), provider_cfg(route)
                ) == "cloud"
            ]
            routes = local_routes + cloud_routes

        manual_id = str(settings.get("manual_route_id") or "")
        manual = next(
            (r for r in routes if str(r.get("id") or "") == manual_id),
            None,
        ) if manual_id else None
        if manual is not None and not settings.get("failover_enabled", True):
            for route in routes:
                if route is not manual:
                    decisions[str(route.get("id") or "")] = "manual_failover_disabled"
            ordered = [manual]
        elif manual is not None:
            ordered = [manual] + [r for r in routes if r is not manual]
        else:
            ordered = list(routes)

        preferred = next(
            (r for r in ordered if str(r.get("id") or "") == str(preferred_route_id)),
            None,
        )
        pinned = preferred or manual
        if pinned is not None:
            ordered = [pinned] + [r for r in ordered if r is not pinned]

        selected_ids = {str(r.get("id") or "") for r in ordered}
        result = []
        for route in ordered:
            rid = str(route.get("id") or "")
            reason = (
                "preferred_route"
                if preferred is route
                else ("manual_route" if manual is route else "priority_order")
            )
            result.append(RouteDecision(rid, True, reason))
        for route in original_routes:
            rid = str(route.get("id") or "")
            if rid not in selected_ids and rid not in decisions:
                decisions[rid] = "not_selected"
        result.extend(
            RouteDecision(rid, False, reason)
            for rid, reason in decisions.items()
        )
        return ordered, result
