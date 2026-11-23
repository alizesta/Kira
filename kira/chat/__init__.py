"""Public contracts for the independent chat feature.

Exports are resolved on first access so importing a small Chat submodule does
not import persistence, orchestration, attachments and every other feature.
The historical package-level API remains available.
"""
from __future__ import annotations

from importlib import import_module

_EXPORTS = {
    "CHAT_EVENT_TYPES": "events",
    "ChatEvent": "events",
    "ChatEventDispatch": "events",
    "ChatEventPublisher": "events",
    "ChatEventType": "events",
    "Attachment": "attachments",
    "AttachmentError": "attachments",
    "AttachmentManager": "attachments",
    "AttachmentSource": "attachments",
    "AttachmentStatus": "attachments",
    "CommandCancelled": "commands",
    "CommandDefinition": "commands",
    "CommandDispatch": "commands",
    "CommandExecutionContext": "commands",
    "CommandOutcome": "commands",
    "CommandRegistry": "commands",
    "CommandRequest": "commands",
    "CommandResult": "commands",
    "CommandStatus": "commands",
    "PermissionDecision": "commands",
    "validate_parameters": "commands",
    "create_default_command_registry": "command_adapters",
    "ChatPersistence": "persistence",
    "ChatRepository": "persistence",
    "SqliteChatRepository": "persistence",
    "PersistenceError": "persistence",
    "create_default_chat_persistence": "persistence",
    "ChatCoordinator": "coordinator",
    "ChatProviderDispatcher": "coordinator",
    "ChatRequest": "coordinator",
    "SubmissionResult": "coordinator",
    "ChatResponseResult": "response_handler",
    "ProviderEvent": "response_handler",
    "ProviderEventKind": "response_handler",
    "ResponseError": "response_handler",
    "ResponseEventKind": "response_handler",
    "ResponseHandler": "response_handler",
    "ResponseStatus": "response_handler",
    "ResponseStreamEvent": "response_handler",
    "ApplicationEventKind": "application_service",
    "ChatApplicationEvent": "application_service",
    "ChatApplicationRequest": "application_service",
    "ChatApplicationService": "application_service",
    "PersistenceOutcome": "application_service",
    "RequestStatus": "application_service",
    "Submission": "application_service",
    "SessionManager": "session_manager",
    "SessionState": "session_manager",
    "SessionStateChanged": "session_manager",
    "ChatMessageReference": "search",
    "ChatSearchError": "search",
    "ChatSearchHit": "search",
    "ChatSearchPage": "search",
    "ChatSearchRepository": "search",
    "ChatSearchRepositoryError": "search",
    "ChatSearchRequest": "search",
    "ChatSearchService": "search",
    "ChatSearchValidationError": "search",
    "ChatTransfer": "transfer",
    "ImportPreview": "transfer",
    "ImportResult": "transfer",
    "TransferError": "transfer",
    "TransferRepository": "transfer",
    "ConversationLifecycleError": "conversation_lifecycle",
    "ConversationLifecycleResult": "conversation_lifecycle",
    "ConversationLifecycleService": "conversation_lifecycle",
    "ConversationNotFound": "conversation_lifecycle",
    "ConversationOperation": "conversation_lifecycle",
    "ConversationStatus": "conversation_lifecycle",
    "InvalidConversationTransition": "conversation_lifecycle",
    "PermanentDeleteAuthorization": "conversation_lifecycle",
    "PermanentDeleteAuthorizationError": "conversation_lifecycle",
    "ChatOrganizationService": "organization",
    "Folder": "organization",
    "OrganizationError": "organization",
    "OrganizationFilter": "organization",
    "OrganizationRepository": "organization",
    "OrganizationRepositoryError": "organization",
    "OrganizationResult": "organization",
    "Tag": "organization",
}
__all__ = tuple(_EXPORTS)


def __getattr__(name: str):
    """Resolve and memoize one historical package-level export on demand."""
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module(f".{module_name}", __name__)
    value = getattr(module, name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
