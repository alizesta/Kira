"""Pure contracts and safety rules for versioned Chat history transfer."""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Mapping

SCHEMA_VERSION = 1
EXPORT_VERSION = "1.0"
MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_CONVERSATIONS = 1_000
MAX_MESSAGES = 100_000
MAX_CONTENT_CHARS = 2_000_000
MAX_METADATA_DEPTH = 12
_SECRET_KEY = re.compile(
    r"(?:api.?key|access.?token|refresh.?token|token|password|passwd|secret|credential|authorization|cookie|private.?key)",
    re.I,
)
_ALLOWED_ROLES = {"user", "assistant", "system"}
_ALLOWED_STATUSES = {"streaming", "complete", "interrupted", "failed", "cancelled"}


class TransferError(ValueError):
    """Invalid transfer document or operation."""


@dataclass(frozen=True)
class ImportPreview:
    valid: bool
    conversation_count: int
    message_count: int
    errors: tuple[str, ...]
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class ImportResult:
    imported_conversations: int
    imported_messages: int
    skipped_duplicates: int
    remapped_conversations: int
    remapped_messages: int
    conversation_id_map: Mapping[str, str]


def sanitize_transfer_metadata(value: Any, depth: int = 0) -> Any:
    """Copy JSON-compatible export metadata while removing secret-like fields."""
    if depth > MAX_METADATA_DEPTH:
        raise TransferError("Metadata nesting exceeds the supported depth")
    if value is None or isinstance(value, (str, bool, int, float)):
        if isinstance(value, float) and not math.isfinite(value):
            raise TransferError("Non-finite metadata numbers are not supported")
        return value
    if isinstance(value, (list, tuple)):
        return [
            sanitize_transfer_metadata(item, depth + 1)
            for item in value[:10000]
        ]
    if isinstance(value, Mapping):
        return {
            str(key)[:256]: sanitize_transfer_metadata(item, depth + 1)
            for key, item in value.items()
            if not _SECRET_KEY.search(str(key))
        }
    return None


__all__ = [
    "ALLOWED_ROLES",
    "ALLOWED_STATUSES",
    "EXPORT_VERSION",
    "MAX_CONTENT_CHARS",
    "MAX_CONVERSATIONS",
    "MAX_FILE_BYTES",
    "MAX_MESSAGES",
    "MAX_METADATA_DEPTH",
    "SCHEMA_VERSION",
    "ImportPreview",
    "ImportResult",
    "TransferError",
    "sanitize_transfer_metadata",
]
