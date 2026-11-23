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
from ..core.interfaces.transfer import ChatTransferFilePort


APPLICATION_FEATURE_DEPENDENCIES = {
    "memory": (),
    "mood": (),
    "characters": (),
    "chat_history": (),
    "conversation_lifecycle": ("chat_history",),
    "conversation_organization": ("chat_history",),
    "chat_search": ("chat_history",),
    "chat_transfer": ("chat_history",),
    "web_search": (),
    "shared_skills": (),
    "game_mode": (),
    "desktop_capture": (),
    "desktop_context": (),
    "provider": (),
    "coding_agent": (),
    "runtime_settings": (),
    "vision": ("game_mode", "desktop_capture"),
    "chat_application": ("chat_history", "conversation_lifecycle"),
    "session_application": ("chat_application",),
    "initiative_application": ("memory", "mood"),
    "brain_application": (),
    "reflection_application": ("brain_application",),
    "voice_application": (),
}

OPTIONAL_APPLICATION_MODULES = frozenset({
    "conversation_organization",
    "chat_search",
    "chat_transfer",
    "web_search",
    "shared_skills",
    "coding_agent",
    "brain_application",
    "reflection_application",
})
REQUIRED_APPLICATION_MODULES = (
    frozenset(APPLICATION_FEATURE_DEPENDENCIES) - OPTIONAL_APPLICATION_MODULES
)



def register_application_modules(
    module_manager: ModuleManager,
    container: DependencyContainer,
    *,
    settings: dict[str, Any],
    event_publisher: Any,
    service_factories: Mapping[str, Callable[[], Any]] | None = None,
    transfer_file_port: ChatTransferFilePort | None = None,
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
    from .game_mode_application import GameModeApplicationService
    from .provider_application import ProviderApplicationService
    from .runtime_settings_application import RuntimeSettingsApplicationService
    from .vision_application import VisionApplicationService
    from .desktop_capture_application import DesktopCaptureApplicationService
    from .desktop_context import DesktopContext
    from ..config import DATA_DIR, save_settings
    from .chat_composition import create_chat_application_service_factory
    from .session_composition import create_session_application_service_factory
    from .initiative_composition import create_initiative_application_service_factory
    from .voice_composition import create_voice_application_service_factory

    def selected(key: str, default: Callable[[], Any]) -> Callable[[], Any]:
        factory = overrides.get(key, default)
        if not callable(factory):
            raise TypeError(f"Feature factory must be callable: {key}")
        return factory

    def create_desktop_capture_service() -> Any:
        return DesktopCaptureApplicationService(settings)

    def create_vision() -> Any:
        game_mode = container.resolve("game_mode_application_service")
        desktop_capture = container.resolve("desktop_capture_application_service")
        return VisionApplicationService(
            game_mode, settings.get("vision_mode", "economic"), desktop_capture
        )

    def create_coding_agent_service() -> Any:
        from .coding_agent_application import KodeApplicationService

        return KodeApplicationService()

    def create_brain_application_service() -> Any:
        from .brain_application import BrainApplicationService

        return BrainApplicationService()

    def create_reflection_application_service() -> Any:
        from .reflection_application import ReflectionApplicationService

        return ReflectionApplicationService()

    def create_conversation_lifecycle_service() -> Any:
        from ..chat.conversation_lifecycle import ConversationLifecycleService

        return ConversationLifecycleService(
            container.resolve("chat_history_service"),
            event_publisher,
        )

    def create_chat_factory() -> Any:
        return create_chat_application_service_factory(
            persistence=container.resolve("chat_history_service"),
            event_publisher=event_publisher,
            conversation_lifecycle=container.resolve("conversation_lifecycle_service"),
        )

    def create_session_factory() -> Any:
        return create_session_application_service_factory(event_publisher=event_publisher)

    def create_initiative_factory() -> Any:
        return create_initiative_application_service_factory(
            memory_service=container.resolve("memory_service"),
            mood_service=container.resolve("mood_service"),
        )

    def create_organization_service() -> Any:
        from .organization_application import ChatOrganizationService

        return ChatOrganizationService(
            container.resolve("chat_history_service"),
            event_publisher=event_publisher,
        )

    def create_search_service() -> Any:
        from .chat_search_application import ChatSearchService

        repository = container.resolve("chat_history_service")
        return ChatSearchService(
            repository,
            conversation_reader=repository,
        )

    def create_transfer_service() -> Any:
        from .chat_transfer_application import ChatTransfer

        return ChatTransfer(
            container.resolve("chat_history_service"),
            file_port=transfer_file_port,
        )

    def create_web_search_service() -> Any:
        from .web_search import WebSearchApplicationService

        return WebSearchApplicationService()

    def create_shared_skills_service() -> Any:
        from .shared_skills_application import SharedSkillsApplicationService

        return SharedSkillsApplicationService(
            DATA_DIR / "skills", settings, persist_settings=save_settings
        )

    factories: dict[str, Callable[[], Any]] = {
        "memory_service": selected("memory_service", PersonaMemoryService),
        "mood_service": selected("mood_service", MoodStateService),
        "character_service": selected("character_service", CharacterProfileService),
        "chat_history_service": selected("chat_history_service", SqliteChatHistoryService),
        "conversation_lifecycle_service": selected(
            "conversation_lifecycle_service",
            create_conversation_lifecycle_service,
        ),
        "conversation_organization_application_service": selected(
            "conversation_organization_application_service",
            create_organization_service,
        ),
        "chat_search_application_service": selected(
            "chat_search_application_service",
            create_search_service,
        ),
        "chat_transfer_application_service": selected(
            "chat_transfer_application_service",
            create_transfer_service,
        ),
        "web_search_service": selected("web_search_service", create_web_search_service),
        "shared_skills_application_service": selected(
            "shared_skills_application_service", create_shared_skills_service
        ),
        "game_mode_application_service": selected("game_mode_application_service", GameModeApplicationService),
        "desktop_capture_application_service": selected(
            "desktop_capture_application_service", create_desktop_capture_service
        ),
        "desktop_context_application_service": selected(
            "desktop_context_application_service", DesktopContext
        ),
        "provider_application_service": selected("provider_application_service", ProviderApplicationService),
        "coding_agent_application_service": selected(
            "coding_agent_application_service", create_coding_agent_service
        ),
        "runtime_settings_application_service": selected("runtime_settings_application_service", RuntimeSettingsApplicationService),
        "vision_application_service": selected("vision_application_service", create_vision),
        "chat_application_service_factory": selected("chat_application_service_factory", create_chat_factory),
        "session_application_service_factory": selected("session_application_service_factory", create_session_factory),
        "initiative_application_service_factory": selected(
            "initiative_application_service_factory", create_initiative_factory
        ),
        "brain_application_service": selected(
            "brain_application_service", create_brain_application_service
        ),
        "reflection_application_service": selected(
            "reflection_application_service", create_reflection_application_service
        ),
        "voice_application_service_factory": selected("voice_application_service_factory", create_voice_application_service_factory),
    }
    modules = (
        ("memory", "memory_service"),
        ("mood", "mood_service"),
        ("characters", "character_service"),
        ("chat_history", "chat_history_service"),
        ("conversation_lifecycle", "conversation_lifecycle_service"),
        ("conversation_organization", "conversation_organization_application_service"),
        ("chat_search", "chat_search_application_service"),
        ("chat_transfer", "chat_transfer_application_service"),
        ("web_search", "web_search_service"),
        ("shared_skills", "shared_skills_application_service"),
        ("game_mode", "game_mode_application_service"),
        ("desktop_capture", "desktop_capture_application_service"),
        ("desktop_context", "desktop_context_application_service"),
        ("provider", "provider_application_service"),
        ("coding_agent", "coding_agent_application_service"),
        ("runtime_settings", "runtime_settings_application_service"),
        ("vision", "vision_application_service"),
        ("chat_application", "chat_application_service_factory"),
        ("session_application", "session_application_service_factory"),
        ("initiative_application", "initiative_application_service_factory"),
        ("brain_application", "brain_application_service"),
        ("reflection_application", "reflection_application_service"),
        ("voice_application", "voice_application_service_factory"),
    )
    # Optional constructors stay cold until the owning capability is first used.
    lazy_modules = OPTIONAL_APPLICATION_MODULES
    for module_id, service_key in modules:
        module_manager.register(
            module_id,
            lambda key=service_key, factory=factories[service_key], lazy=module_id in lazy_modules:
                ServiceModule(key, factory, lazy=lazy),
            dependencies=APPLICATION_FEATURE_DEPENDENCIES[module_id],
            optional=module_id in OPTIONAL_APPLICATION_MODULES,
        )
    return tuple(module_id for module_id, _ in modules)
