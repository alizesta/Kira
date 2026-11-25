"""Deterministic route policy, independent from provider health and execution state."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


LOCAL_ONLY = "local_only"
CLOUD_PERMITTED = "cloud_permitted"


@dataclass(frozen=True)
class RouteDecision:
    route_id: str
    allowed: bool
    reason: str


class RoutePolicyEngine:
    """Resolve role, network, vision, manual-priority and usage policy into an ordered route plan.

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
        is_eligible: Callable,
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

        network_policy = str(settings.get("network_policy") or CLOUD_PERMITTED).strip().lower()
        if network_policy not in (LOCAL_ONLY, CLOUD_PERMITTED):
            network_policy = CLOUD_PERMITTED

        role_allowlist = settings.get("role_provider_allowlist")
        allowed = role_allowlist.get(role) if isinstance(role_allowlist, dict) else None
        surface_cloud_fallback = role == "surface" and not vision_only and network_policy == CLOUD_PERMITTED

        if network_policy == LOCAL_ONLY:
            routes = filter_routes(
                routes,
                lambda route: provider_kind(route.get("provider"), provider_cfg(route)) == "local",
                "blocked_by_local_only",
            )

        if vision_only and role in ("surface", "deep") and network_policy != LOCAL_ONLY:
            allowed = ["google"]

        if surface_cloud_fallback:
            # The surface role is local-first, not local-exclusive: preserve all
            # configured Cloud fallbacks behind its role-approved local routes.
            local_routes = [
                route for route in routes
                if provider_kind(route.get("provider"), provider_cfg(route)) == "local"
            ]
            cloud_routes = [
                route for route in routes
                if provider_kind(route.get("provider"), provider_cfg(route)) == "cloud"
            ]
            if isinstance(allowed, (list, tuple)):
                allow = {str(value).strip().lower() for value in allowed if str(value).strip()}
                local_routes = [
                    route for route in local_routes
                    if str(route.get("provider") or "").lower() in allow
                    or ("google" in allow and is_google(route.get("provider"), provider_cfg(route)))
                ]
            model_allowlist = settings.get("role_route_models")
            allowed_models = model_allowlist.get(role) if isinstance(model_allowlist, dict) else None
            if isinstance(allowed_models, (list, tuple)) and "ollama" not in allow:
                model_ids = {str(value).strip().lower() for value in allowed_models if str(value).strip()}
                local_routes = [
                    route for route in local_routes
                    if str(route.get("model") or "").strip().lower() in model_ids
                ]
            routes = local_routes + cloud_routes
        else:
            allow = {str(value).strip().lower() for value in allowed if str(value).strip()} if isinstance(allowed, (list, tuple)) else set()
            if isinstance(allowed, (list, tuple)):
                routes = filter_routes(
                    routes,
                    lambda route: (
                        ("google" in allow and is_google(route.get("provider"), provider_cfg(route)))
                        or str(route.get("provider") or "").lower() in allow
                    ),
                    "blocked_by_role_provider_allowlist",
                )

            model_allowlist = settings.get("role_route_models")
            allowed_models = model_allowlist.get(role) if isinstance(model_allowlist, dict) else None
            if vision_only:
                allowed_models = None
            if isinstance(allowed_models, (list, tuple)):
                model_ids = {str(value).strip().lower() for value in allowed_models if str(value).strip()}
                local_surface_routes = role == "surface" and "ollama" in allow
                routes = filter_routes(
                    routes,
                    lambda route: (
                        local_surface_routes
                        and str(route.get("provider") or "").strip().lower() == "ollama"
                    ) or str(route.get("model") or "").strip().lower() in model_ids,
                    "blocked_by_role_model_allowlist",
                )

        # Provider usage limits are a policy constraint, not a health signal.
        # Their implementation owns its own storage/error handling.
        from . import usage
        if preferred_route_id and not usage.role_allowed(role):
            preferred_route_id = ""
        before_limits = list(routes)
        routes = usage.apply_limits(routes, is_eligible)
        retained = {str(r.get("id") or "") for r in routes}
        for route in before_limits:
            rid = str(route.get("id") or "")
            if rid not in retained:
                decisions[rid] = "blocked_by_usage_limit"

        if vision_only:
            routes = filter_routes(
                routes,
                lambda route: supports_vision(route, provider_cfg(route)),
                "vision_not_supported",
            )

        manual_id = str(settings.get("manual_route_id") or "")
        manual = next((r for r in routes if str(r.get("id") or "") == manual_id), None) if manual_id else None
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
            reason = "preferred_route" if preferred is route else ("manual_route" if manual is route else "priority_order")
            result.append(RouteDecision(rid, True, reason))
        for route in original_routes:
            rid = str(route.get("id") or "")
            if rid not in selected_ids and rid not in decisions:
                decisions[rid] = "not_selected"
        result.extend(RouteDecision(rid, False, reason) for rid, reason in decisions.items())
        return ordered, result
