"""Application feature registrations and dependency ordering.

Application-wide services and composition factories are created through
ServiceModule. Concrete Chat/Session/Voice instances remain window-scoped
because they are constructed with live Qt callback/worker ports.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from .dependency_container import DependencyContainer
from .module_manager import ModuleManager
from .service_module import ServiceModule


APPLICATION_FEATURE_DEPENDENCIES = {
    "memory": (),
    "mood": (),
    "characters": (),
    "chat_history": (),
    "web_search": (),
    "game_mode": (),
    "provider": (),
    "coding_agent": (),
    "runtime_settings": (),
    "vision": ("game_mode",),
    "chat_application": ("chat_history",),
    "session_application": ("chat_application",),
    "voice_application": (),
}


def register_application_modules(
    module_manager: ModuleManager,
    container: DependencyContainer,
    *,
    settings: dict[str, Any],
    event_publisher: Any,
    service_factories: Mapping[str, Callable[[], Any]] | None = None,
) -> tuple[str, ...]:
    """Register every app service/factory under one dependency-aware lifecycle."""
    if module_manager.container is not container:
        raise ValueError("module_manager and container must share the same instance")
    overrides = dict(service_factories or {})

    from ..services import (
        CharacterProfileService,
        MoodStateService,
        PersonaMemoryService,
        SqliteChatHistoryService,
    )
    from .coding_agent_application import CodingAgentApplicationService
    from .game_mode_application import GameModeApplicationService
    from .provider_application import ProviderApplicationService
    from .runtime_settings_application import RuntimeSettingsApplicationService
    from .vision_application import VisionApplicationService
    from .web_search import WebSearchApplicationService
    from .chat_composition import create_chat_application_service_factory
    from .session_composition import create_session_application_service_factory
    from .voice_composition import create_voice_application_service_factory

    def selected(key: str, default: Callable[[], Any]) -> Callable[[], Any]:
        factory = overrides.get(key, default)
        if not callable(factory):
            raise TypeError(f"Feature factory must be callable: {key}")
        return factory

    def create_vision() -> Any:
        game_mode = container.resolve("game_mode_application_service")
        return VisionApplicationService(game_mode, settings.get("vision_mode", "economic"))

    def create_chat_factory() -> Any:
        return create_chat_application_service_factory(
            persistence=container.resolve("chat_history_service"),
            event_publisher=event_publisher,
        )

    def create_session_factory() -> Any:
        return create_session_application_service_factory(event_publisher=event_publisher)

    factories: dict[str, Callable[[], Any]] = {
        "memory_service": selected("memory_service", PersonaMemoryService),
        "mood_service": selected("mood_service", MoodStateService),
        "character_service": selected("character_service", CharacterProfileService),
        "chat_history_service": selected("chat_history_service", SqliteChatHistoryService),
        "web_search_service": selected("web_search_service", WebSearchApplicationService),
        "game_mode_application_service": selected("game_mode_application_service", GameModeApplicationService),
        "provider_application_service": selected("provider_application_service", ProviderApplicationService),
        "coding_agent_application_service": selected("coding_agent_application_service", CodingAgentApplicationService),
        "runtime_settings_application_service": selected("runtime_settings_application_service", RuntimeSettingsApplicationService),
        "vision_application_service": selected("vision_application_service", create_vision),
        "chat_application_service_factory": selected("chat_application_service_factory", create_chat_factory),
        "session_application_service_factory": selected("session_application_service_factory", create_session_factory),
        "voice_application_service_factory": selected("voice_application_service_factory", create_voice_application_service_factory),
    }
    modules = (
        ("memory", "memory_service"),
        ("mood", "mood_service"),
        ("characters", "character_service"),
        ("chat_history", "chat_history_service"),
        ("web_search", "web_search_service"),
        ("game_mode", "game_mode_application_service"),
        ("provider", "provider_application_service"),
        ("coding_agent", "coding_agent_application_service"),
        ("runtime_settings", "runtime_settings_application_service"),
        ("vision", "vision_application_service"),
        ("chat_application", "chat_application_service_factory"),
        ("session_application", "session_application_service_factory"),
        ("voice_application", "voice_application_service_factory"),
    )
    for module_id, service_key in modules:
        module_manager.register(
            module_id,
            lambda key=service_key, factory=factories[service_key]: ServiceModule(key, factory),
            dependencies=APPLICATION_FEATURE_DEPENDENCIES[module_id],
            optional=False,
        )
    return tuple(module_id for module_id, _ in modules)
