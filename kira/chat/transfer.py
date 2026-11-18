"""Compatibility imports for versioned Chat history transfer."""
from ..app.chat_transfer_application import ChatTransfer
from ..core.interfaces.transfer import ChatTransferRepositoryPort as TransferRepository
from ..domain.transfer import (
    EXPORT_VERSION,
    MAX_CONTENT_CHARS,
    MAX_CONVERSATIONS,
    MAX_FILE_BYTES,
    MAX_MESSAGES,
    MAX_METADATA_DEPTH,
    SCHEMA_VERSION,
    ImportPreview,
    ImportResult,
    TransferError,
    sanitize_transfer_metadata,
)

# Retain the historical private helper name for existing integrations.
_sanitize_json = sanitize_transfer_metadata

__all__ = [
    "ChatTransfer",
    "EXPORT_VERSION",
    "ImportPreview",
    "ImportResult",
    "MAX_CONTENT_CHARS",
    "MAX_CONVERSATIONS",
    "MAX_FILE_BYTES",
    "MAX_MESSAGES",
    "MAX_METADATA_DEPTH",
    "SCHEMA_VERSION",
    "TransferError",
    "TransferRepository",
    "_sanitize_json",
    "sanitize_transfer_metadata",
]
