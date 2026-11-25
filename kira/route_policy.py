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
        network_policy = str(settings.get("network_policy") or CLOUD_PERMITTED).strip().lower()
        if network_policy not in (LOCAL_ONLY, CLOUD_PERMITTED):
            network_policy = CLOUD_PERMITTED

        role_allowlist = settings.get("role_provider_allowlist")
        allowed = role_allowlist.get(role) if isinstance(role_allowlist, dict) else None
        local_ready = False
        if role == "surface" and not vision_only:
            local_ready = any(
                str(route.get("provider") or "").lower() == "ollama" and is_eligible(route)
                for route in routes
            )
            # Preserve the existing local-first conversation behavior, but only
            # cross the network boundary when the explicit policy permits Cloud.
            if not local_ready:
                if network_policy == LOCAL_ONLY:
                    return [], [RouteDecision(str(r.get("id") or ""), False, "local_unavailable_local_only") for r in routes]
                routes = [
                    route for route in routes
                    if provider_kind(route.get("provider"), provider_cfg(route)) == "cloud"
                ]
                allowed = None

        if network_policy == LOCAL_ONLY:
            routes = [
                route for route in routes
                if provider_kind(route.get("provider"), provider_cfg(route)) == "local"
            ]

        if vision_only and role in ("surface", "deep"):
            allowed = ["google"]

        if isinstance(allowed, (list, tuple)):
            allow = {str(value).strip().lower() for value in allowed if str(value).strip()}
            routes = [
                route for route in routes
                if (
                    ("google" in allow and is_google(route.get("provider"), provider_cfg(route)))
                    or str(route.get("provider") or "").lower() in allow
                )
            ]

        model_allowlist = settings.get("role_route_models")
        allowed_models = model_allowlist.get(role) if isinstance(model_allowlist, dict) else None
        if vision_only:
            allowed_models = None
        if isinstance(allowed_models, (list, tuple)) and not (role == "surface" and not local_ready):
            model_ids = {str(value).strip().lower() for value in allowed_models if str(value).strip()}
            local_surface_routes = (
                role == "surface" and isinstance(allowed, set) and "ollama" in allowed
            )
            routes = [
                route for route in routes
                if (
                    local_surface_routes
                    and str(route.get("provider") or "").strip().lower() == "ollama"
                ) or str(route.get("model") or "").strip().lower() in model_ids
            ]

        # Provider usage limits are a policy constraint, not a health signal.
        # Their implementation owns its own storage/error handling.
        from . import usage
        if preferred_route_id and not usage.role_allowed(role):
            preferred_route_id = ""
        routes = usage.apply_limits(routes, is_eligible)

        if vision_only:
            routes = [r for r in routes if supports_vision(r, provider_cfg(r))]

        manual_id = str(settings.get("manual_route_id") or "")
        manual = next((r for r in routes if str(r.get("id") or "") == manual_id), None) if manual_id else None
        if manual is not None and not settings.get("failover_enabled", True):
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

        decisions = []
        selected_ids = {str(r.get("id") or "") for r in ordered}
        for route in ordered:
            decisions.append(RouteDecision(str(route.get("id") or ""), True, "selected_by_policy"))
        for route in routes:
            rid = str(route.get("id") or "")
            if rid not in selected_ids:
                decisions.append(RouteDecision(rid, False, "filtered_by_policy"))
        return ordered, decisions
