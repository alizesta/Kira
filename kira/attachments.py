"""Compatibility import surface for the Qt-free chat attachment parser.

New code should use kira.chat.attachments.AttachmentManager for managed
storage and kira.chat.attachment_content for bounded content extraction.
"""
from .chat.attachment_content import (
    AttachmentError,
    HISTORY_EXCERPT,
    IMAGE_TYPES,
    MAX_ARCHIVE_ENTRIES,
    MAX_ARCHIVE_MEMBER_BYTES,
    MAX_ARCHIVE_UNPACKED_BYTES,
    MAX_FILE_BYTES,
    MAX_FILES,
    MAX_IMAGE_BYTES,
    MAX_IMAGE_SIDE,
    MAX_TEXT_CHARS,
    compose,
    image_attachment,
    load_attachment,
    summary,
)

__all__ = [
    "AttachmentError", "HISTORY_EXCERPT", "IMAGE_TYPES",
    "MAX_ARCHIVE_ENTRIES", "MAX_ARCHIVE_MEMBER_BYTES",
    "MAX_ARCHIVE_UNPACKED_BYTES", "MAX_FILE_BYTES", "MAX_FILES",
    "MAX_IMAGE_BYTES", "MAX_IMAGE_SIDE", "MAX_TEXT_CHARS",
    "compose", "image_attachment", "load_attachment", "summary",
]
