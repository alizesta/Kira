"""Application policy for provider, model and route configuration.

The UI owns form widgets and confirmation dialogs. This service owns the
settings mutations and keeps the provider registry and route model coherent.
"""
from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

from .. import api_manager, routes as route_model


class ProviderApplicationService:
    """Coordinate provider and route policy without depending on Qt."""

    def __init__(self, router_factory=None, ollama_client_factory=None):
        self._router_factory = router_factory
        self._ollama_client_factory = ollama_client_factory

    def create_router(self, settings):
        if self._router_factory is not None:
            return self._router_factory(settings)
        from ..hybrid_ai import HybridRouter
        return HybridRouter(settings)

    def create_ollama_client(self, settings):
        if self._ollama_client_factory is not None:
            return self._ollama_client_factory(settings)
        from ..ollama_client import OllamaClient
        return OllamaClient.from_settings(settings)

    def rebuild_session_routers(self, settings, sessions, previous_router=None):
        """Recreate per-character routers while preserving shared health and cooldown state."""
        sessions = tuple(sessions)
        if not sessions:
            return ()
        old_states = getattr(previous_router, "states", None)
        shared_cooldowns = {}
        routers = []
        for session in sessions:
            router = self.create_router(settings)
            if old_states is not None:
                router.states = old_states
            router.cooldowns = shared_cooldowns
            session.client = router
            routers.append(router)
        return tuple(routers)

    BUILTIN = route_model.BUILTIN
    LOCAL_TIMEOUT = route_model.LOCAL_TIMEOUT
    CLOUD_TIMEOUT = route_model.CLOUD_TIMEOUT

    @staticmethod
    def get_routes(settings: dict[str, Any]):
        return route_model.get_routes(settings)

    @staticmethod
    def find_route(settings: dict[str, Any], route_id: str | None):
        return route_model.find_route(settings, route_id)

    @staticmethod
    def provider_label(provider_id: str, config=None) -> str:
        return route_model.provider_label(provider_id, config)

    @staticmethod
    def provider_kind(provider_id: str, config=None) -> str:
        return route_model.provider_kind(provider_id, config)

    @staticmethod
    def ensure_routes(settings: dict[str, Any]) -> dict[str, Any]:
        return route_model.ensure_routes(settings)

    @staticmethod
    def add_route(settings: dict[str, Any], provider: str, model: str, enabled: bool = True):
        return route_model.add_route(settings, provider, model, enabled=enabled)

    @staticmethod
    def update_route(settings: dict[str, Any], route_id: str, **changes):
        return route_model.update_route(settings, route_id, **changes)

    @staticmethod
    def remove_route(settings: dict[str, Any], route_id: str) -> None:
        route_model.remove_route(settings, route_id)

    @staticmethod
    def reorder_routes(settings: dict[str, Any], ordered_ids):
        return route_model.reorder(settings, ordered_ids)

    @staticmethod
    def move_route(settings: dict[str, Any], route_id: str, new_index: int):
        return route_model.move_route(settings, route_id, new_index)

    @staticmethod
    def set_default_route(settings: dict[str, Any], route_id: str):
        return route_model.set_default(settings, route_id)

    @staticmethod
    def set_manual_route(settings: dict[str, Any], route_id: str | None) -> None:
        route_model.set_manual(settings, route_id)

    @staticmethod
    def set_failover(settings: dict[str, Any], enabled: bool) -> None:
        settings["failover_enabled"] = bool(enabled)

    @staticmethod
    def add_ollama_models(settings: dict[str, Any], names):
        return route_model.add_ollama_models(settings, names)

    @staticmethod
    def update_provider(settings: dict[str, Any], provider_id: str, **changes):
        return route_model.update_provider(settings, provider_id, **changes)

    @staticmethod
    def add_provider(
        settings: dict[str, Any],
        label: str,
        base_url: str,
        api_key: str = "",
        local: bool = False,
        first_model: str = "",
    ) -> str:
        """Add provider and optional initial route atomically in the in-memory settings document."""
        before = deepcopy(settings)
        try:
            provider_id = route_model.add_provider(settings, label, base_url, api_key, local)
            if str(first_model or "").strip():
                route_model.add_route(settings, provider_id, first_model)
            route_model.ensure_routes(settings)
            return provider_id
        except Exception:
            settings.clear()
            settings.update(before)
            raise

    @staticmethod
    def remove_provider(settings: dict[str, Any], provider_id: str):
        """Remove a custom provider and its API registry entry as one settings operation."""
        before = deepcopy(settings)
        try:
            removed_routes = route_model.remove_provider(settings, provider_id)
            api_manager.registry(settings).pop(provider_id, None)
            return removed_routes
        except Exception:
            settings.clear()
            settings.update(before)
            raise

    @staticmethod
    def set_api_enabled(settings: dict[str, Any], provider_id: str, enabled: bool) -> None:
        api_manager.set_api_enabled(settings, provider_id, enabled)

    @staticmethod
    def set_model_enabled(settings: dict[str, Any], provider_id: str, model_id: str, enabled: bool) -> None:
        api_manager.set_model_enabled(settings, provider_id, model_id, enabled)

    @staticmethod
    def delete_api(settings: dict[str, Any], provider_id: str) -> None:
        api_manager.delete_api(settings, provider_id)

    @staticmethod
    def move_api(settings: dict[str, Any], provider_id: str, delta: int) -> None:
        api_manager.move_api(settings, provider_id, delta)

    @staticmethod
    def apply_models(settings: dict[str, Any], provider_id: str, models, rate_limit=None):
        return api_manager.apply_models(settings, provider_id, models, rate_limit)

    @staticmethod
    def apply_failure(settings: dict[str, Any], provider_id: str, detection) -> None:
        api_manager.apply_failure(settings, provider_id, detection)

    @staticmethod
    def update_ollama_url(settings: dict[str, Any], value: str) -> str:
        url = str(value or "").strip().rstrip("/")
        if not re.fullmatch(r"https?://\S+", url, re.IGNORECASE):
            raise ValueError("آدرس Ollama باید با http:// یا https:// شروع شود و فاصله نداشته باشد.")
        settings["ollama_url"] = url
        settings.setdefault("providers", {}).setdefault("ollama", {})["base_url"] = url
        return url
