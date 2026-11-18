"""Compatibility imports for conversation organization.

New application code should depend on kira.app.organization_application and
kira.domain.organization. This facade remains for existing consumers.
"""
from ..app.organization_application import (
    ChatOrganizationService,
    OrganizationRepositoryError,
    OrganizationResult,
)
from ..core.interfaces.organization import (
    ConversationOrganizationRepositoryPort as OrganizationRepository,
)
from ..domain.organization import (
    DEFAULT_FOLDER_ID,
    MAX_DESCRIPTION_LENGTH,
    MAX_LABEL_LENGTH,
    MAX_METADATA_DEPTH,
    MAX_TITLE_LENGTH,
    ORGANIZATION_KEY,
    Folder,
    OrganizationError,
    OrganizationFilter,
    Tag,
    normalize_key,
    normalize_label,
    organization_metadata,
    sanitize_metadata,
)

__all__ = [
    "ChatOrganizationService",
    "DEFAULT_FOLDER_ID",
    "Folder",
    "MAX_DESCRIPTION_LENGTH",
    "MAX_LABEL_LENGTH",
    "MAX_METADATA_DEPTH",
    "MAX_TITLE_LENGTH",
    "ORGANIZATION_KEY",
    "OrganizationError",
    "OrganizationFilter",
    "OrganizationRepository",
    "OrganizationRepositoryError",
    "OrganizationResult",
    "Tag",
    "normalize_key",
    "normalize_label",
    "organization_metadata",
    "sanitize_metadata",
]
