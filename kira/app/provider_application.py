"""Application policy for provider, model and route configuration.

The UI owns form widgets and confirmation dialogs. This service owns the
settings mutations; provider/model observations live in its separate
DetectedCapabilities store.
"""
from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

from .. import api_manager, routes as route_model
from .detected_capabilities import DetectedCapabilities


class ProviderApplicationService:
    """Coordinate provider and route policy without depending on Qt."""

    def __init__(self, router_factory=None, ollama_client_factory=None):
        self._router_factory = router_factory
        self._ollama_client_factory = ollama_client_factory
        self.detected_capabilities = DetectedCapabilities()

    @property
    def ollama_models(self):
        return tuple(self.detected_capabilities.get("ollama_models", ()))

    def set_ollama_models(self, models):
        self.detected_capabilities.set("ollama_models", tuple(str(item) for item in (models or ())))

    @property
    def model_catalog_refreshed_at(self):
        return int(self.detected_capabilities.get("model_catalog_refreshed_at", 0) or 0)

    def set_model_catalog_refreshed_at(self, timestamp):
        self.detected_capabilities.set("model_catalog_refreshed_at", int(timestamp or 0))

    def create_router(self, settings):
        if self._router_factory is not None:
            return self._router_factory(settings)
        from ..hybrid_ai import HybridRouter
        return HybridRouter(settings, detected_capabilities=self.detected_capabilities)

    def create_isolated_router(self, settings, previous_router=None):
        """Create an independent request/cancellation channel for background work."""
        router = self.create_router(settings)
        if previous_router is not None:
            if router is previous_router:
                raise RuntimeError("isolated router factory returned the previous router")
            previous_states = getattr(previous_router, "states", None)
            if isinstance(previous_states, dict):
                router.states = deepcopy(previous_states)
            previous_cooldowns = getattr(previous_router, "cooldowns", None)
            if isinstance(previous_cooldowns, dict):
                router.cooldowns = dict(previous_cooldowns)
        return router

    def create_ollama_client(self, settings):
        if self._ollama_client_factory is not None:
            return self._ollama_client_factory(settings)
        from ..ollama_client import OllamaClient
        return OllamaClient.from_settings(settings)

    def create_ollama_client_from_values(
        self, base_url, model, *, num_ctx, keep_alive, num_predict
    ):
        """Create the settings-dialog probe client without exposing the SDK to UI code."""
        from ..ollama_client import OllamaClient
        return OllamaClient(
            base_url,
            model,
            num_ctx=num_ctx,
            keep_alive=keep_alive,
            num_predict=num_predict,
        )

    def rebuild_session_routers(self, settings, sessions, previous_router=None):
        """Share route health across replacements while resetting their cooldown map."""
        sessions = tuple(sessions)
        if not sessions:
            return ()
        old_states = getattr(previous_router, "states", None)
        shared_cooldowns = {}
        # Build every replacement before mutating any Session; a failed factory
        # must not leave the character set with a mixture of old and new routers.
        routers = [self.create_router(settings) for _session in sessions]
        for router in routers:
            if old_states is not None:
                router.states = old_states
            router.cooldowns = shared_cooldowns
        for session, router in zip(sessions, routers):
            session.client = router
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

    def ensure_routes(self, settings: dict[str, Any]) -> dict[str, Any]:
        return route_model.ensure_routes(settings, capabilities=self.detected_capabilities)

    @staticmethod
    def add_route(settings: dict[str, Any], provider: str, model: str, enabled: bool = True):
        return route_model.add_route(settings, provider, model, enabled=enabled)

    @staticmethod
    def update_route(settings: dict[str, Any], route_id: str, **changes):
        return route_model.update_route(settings, route_id, **changes)

    def remove_route(self, settings: dict[str, Any], route_id: str) -> None:
        route_model.remove_route(settings, route_id, capabilities=self.detected_capabilities)

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

    def update_provider(self, settings: dict[str, Any], provider_id: str, **changes):
        return route_model.update_provider(
            settings, provider_id, capabilities=self.detected_capabilities, **changes
        )

    def add_provider(
        self,
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
            route_model.ensure_routes(settings, capabilities=self.detected_capabilities)
            return provider_id
        except Exception:
            settings.clear()
            settings.update(before)
            raise

    def remove_provider(self, settings: dict[str, Any], provider_id: str):
        """Remove a custom provider and its API registry entry as one settings operation."""
        before = deepcopy(settings)
        try:
            removed_routes = route_model.remove_provider(
                settings, provider_id, capabilities=self.detected_capabilities
            )
            api_manager.registry(self.detected_capabilities).pop(provider_id, None)
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

    def delete_api(self, settings: dict[str, Any], provider_id: str) -> None:
        api_manager.delete_api(settings, provider_id, capabilities=self.detected_capabilities)

    @staticmethod
    def move_api(settings: dict[str, Any], provider_id: str, delta: int) -> None:
        api_manager.move_api(settings, provider_id, delta)

    def apply_models(self, settings: dict[str, Any], provider_id: str, models, rate_limit=None):
        return api_manager.apply_models(settings, provider_id, models, rate_limit, capabilities=self.detected_capabilities)

    def apply_failure(self, settings: dict[str, Any], provider_id: str, detection) -> None:
        api_manager.apply_failure(settings, provider_id, detection, capabilities=self.detected_capabilities)

    Detection = api_manager.Detection

    @staticmethod
    def api_ids(settings):
        return api_manager.api_ids(settings)

    @staticmethod
    def rediscover(provider_id, config, timeout=15):
        return api_manager.rediscover(provider_id, config, timeout=timeout)

    def ensure_registry(self, settings):
        return api_manager.ensure_registry(settings, self.detected_capabilities)

    def registry(self):
        return api_manager.registry(self.detected_capabilities)

    @staticmethod
    def detect(api_key, account=None):
        return api_manager.detect(api_key, account)

    @staticmethod
    def key_problem(api_key):
        return api_manager.key_problem(api_key)

    @staticmethod
    def find_duplicate(settings, api_key):
        return api_manager.find_duplicate(settings, api_key)

    def register(self, settings, detection, api_key):
        return api_manager.register(settings, detection, api_key, capabilities=self.detected_capabilities)

    @staticmethod
    def describe_failure(detection):
        return api_manager.describe_failure(detection)

    def api_rows(self, settings):
        return api_manager.api_rows(settings, capabilities=self.detected_capabilities)

    @staticmethod
    def fmt_time(value):
        return api_manager.fmt_time(value)

    def api_details(self, settings, provider_id):
        return api_manager.api_details(settings, provider_id, capabilities=self.detected_capabilities)

    @staticmethod
    def service_of(provider_id, config):
        return api_manager.service_of(provider_id, config)

    @staticmethod
    def mask_key(api_key):
        return api_manager.mask_key(api_key)

    @staticmethod
    def update_ollama_url(settings: dict[str, Any], value: str) -> str:
        url = str(value or "").strip().rstrip("/")
        if not re.fullmatch(r"https?://\S+", url, re.IGNORECASE):
            raise ValueError("آدرس Ollama باید با http:// یا https:// شروع شود و فاصله نداشته باشد.")
        settings["ollama_url"] = url
        settings.setdefault("providers", {}).setdefault("ollama", {})["base_url"] = url
        return url
