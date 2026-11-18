"""Pure conversation organization values and normalization rules.

This module owns metadata shape and validation only. It performs no persistence,
event publication, synchronization, or application orchestration.
"""
from __future__ import annotations

import copy
import math
import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Mapping

ORGANIZATION_KEY = "organization"
DEFAULT_FOLDER_ID = "inbox"
MAX_TITLE_LENGTH = 120
MAX_LABEL_LENGTH = 64
MAX_DESCRIPTION_LENGTH = 500
MAX_METADATA_DEPTH = 8
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_SPACE = re.compile(r"\s+")


class OrganizationError(ValueError):
    """Invalid organization metadata or operation input."""


@dataclass(frozen=True)
class OrganizationFilter:
    folder_id: str | None = None
    tags: tuple[str, ...] = ()
    favorite: bool | None = None
    category: str | None = None
    query: str | None = None
    sort_by: str = "updated"
    descending: bool = True


@dataclass(frozen=True)
class Tag:
    id: str
    name: str


@dataclass(frozen=True)
class Folder:
    id: str
    name: str


def normalize_label(
    value: Any,
    field_name: str,
    maximum: int = MAX_LABEL_LENGTH,
) -> str:
    """Normalize one printable label while enforcing its domain length limit."""
    if not isinstance(value, str):
        raise OrganizationError(f"{field_name} must be text")
    if _CONTROL.search(value):
        raise OrganizationError(
            f"{field_name} must contain 1 to {maximum} printable characters"
        )
    normalized = unicodedata.normalize("NFKC", _SPACE.sub(" ", value)).strip()
    if not normalized or len(normalized) > maximum or _CONTROL.search(normalized):
        raise OrganizationError(
            f"{field_name} must contain 1 to {maximum} printable characters"
        )
    return normalized


def contains_control_characters(value: Any) -> bool:
    """Return whether text contains ASCII control characters."""
    return isinstance(value, str) and _CONTROL.search(value) is not None


def normalize_key(value: Any, field_name: str) -> str:
    """Return the case-insensitive identity form for a validated label."""
    return normalize_label(value, field_name).casefold()


def sanitize_metadata(value: Any, depth: int = 0) -> Any:
    """Copy a bounded JSON-like metadata value, rejecting unsupported values."""
    if depth > MAX_METADATA_DEPTH:
        raise OrganizationError("metadata nesting exceeds the supported depth")
    if isinstance(value, float) and not math.isfinite(value):
        raise OrganizationError("metadata numbers must be finite")
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, Mapping):
        result = {}
        for key, item in value.items():
            if not isinstance(key, str) or len(key) > 128:
                raise OrganizationError("metadata keys must be bounded strings")
            result[key] = sanitize_metadata(item, depth + 1)
        return result
    if isinstance(value, (list, tuple)):
        if len(value) > 1000:
            raise OrganizationError("metadata arrays are limited to 1,000 items")
        return [sanitize_metadata(item, depth + 1) for item in value]
    raise OrganizationError(f"unsupported metadata value: {type(value).__name__}")


def organization_metadata(metadata: Any) -> dict[str, Any]:
    """Return a defensive copy of a conversation's organization namespace."""
    source = copy.deepcopy(dict(metadata)) if isinstance(metadata, Mapping) else {}
    value = source.get(ORGANIZATION_KEY)
    return copy.deepcopy(dict(value)) if isinstance(value, Mapping) else {}


__all__ = [
    "DEFAULT_FOLDER_ID",
    "MAX_DESCRIPTION_LENGTH",
    "MAX_LABEL_LENGTH",
    "MAX_METADATA_DEPTH",
    "MAX_TITLE_LENGTH",
    "ORGANIZATION_KEY",
    "Folder",
    "OrganizationError",
    "OrganizationFilter",
    "Tag",
    "contains_control_characters",
    "normalize_key",
    "normalize_label",
    "organization_metadata",
    "sanitize_metadata",
]
