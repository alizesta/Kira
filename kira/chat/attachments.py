"""Session-scoped attachment storage and content preparation.

This module is UI-, Qt-, Provider-, and Persistence-independent.  It owns
managed copies of attachment bytes and delegates format extraction to the
legacy pure parser until callers migrate to this API.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
import uuid
import zipfile
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from kira import attachments as _legacy


class AttachmentStatus(str, Enum):
    READY = "ready"
    FAILED = "failed"
    REMOVED = "removed"


class AttachmentSource(str, Enum):
    FILE = "file"
    MEMORY = "memory"


@dataclass(frozen=True, slots=True)
class Attachment:
    attachment_id: str
    message_id: str | None
    session_id: str
    filename: str
    mime_type: str
    size: int
    source: AttachmentSource
    path: str
    metadata: Mapping[str, Any] = field(default_factory=dict)
    status: AttachmentStatus = AttachmentStatus.READY

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


class AttachmentManager:
    """Own attachment validation, managed files, session isolation and cleanup."""

    IMAGE_MIMES = {
        ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".webp": "image/webp", ".gif": "image/gif", ".bmp": "image/bmp",
    }
    TEXT_EXTENSIONS = frozenset({
        ".txt", ".md", ".rst", ".json", ".jsonl", ".csv", ".tsv", ".log",
        ".py", ".pyi", ".js", ".jsx", ".ts", ".tsx", ".html", ".htm",
        ".css", ".scss", ".xml", ".yaml", ".yml", ".toml", ".ini", ".cfg",
        ".conf", ".bat", ".cmd", ".ps1", ".sh", ".sql", ".java", ".kt",
        ".kts", ".c", ".h", ".cpp", ".hpp", ".cs", ".go", ".rs", ".php",
        ".rb", ".swift", ".dart", ".vue", ".svelte", ".gradle", ".properties",
    })
    DOCUMENT_MIMES = {
        ".pdf": "application/pdf",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".zip": "application/zip",
    }

    def __init__(
        self,
        storage_root: str | os.PathLike[str] | None = None,
        *,
        max_files: int = _legacy.MAX_FILES,
        max_image_bytes: int = _legacy.MAX_IMAGE_BYTES,
        max_file_bytes: int = _legacy.MAX_FILE_BYTES,
    ) -> None:
        if max_files < 1 or max_image_bytes < 1 or max_file_bytes < 1:
            raise ValueError("attachment limits must be positive")
        self._owns_root = storage_root is None
        self._root = Path(storage_root or tempfile.mkdtemp(prefix="kira-chat-attachments-")).resolve()
        self._root.mkdir(parents=True, exist_ok=True)
        self.max_files = int(max_files)
        self.max_image_bytes = int(max_image_bytes)
        self.max_file_bytes = int(max_file_bytes)
        self._records: dict[str, Attachment] = {}
        self._content_index: dict[tuple[str, str, str], str] = {}
        self._closed = False

    @property
    def storage_root(self) -> Path:
        return self._root

    def _ensure_open(self) -> None:
        if self._closed:
            raise _legacy.AttachmentError("مدیر ضمیمه‌ها بسته شده است.")

    @staticmethod
    def _safe_name(filename: str) -> str:
        name = Path(str(filename or "")).name.replace("\\", "_").strip()
        if not name or name in {".", ".."} or "\x00" in name:
            raise _legacy.AttachmentError("نام فایل معتبر نیست.")
        return name[:240]

    @staticmethod
    def _sniff(data: bytes, extension: str) -> str:
        if data.startswith(b"\x89PNG\r\n\x1a\n"):
            return "image/png"
        if data.startswith(b"\xff\xd8\xff"):
            return "image/jpeg"
        if data.startswith((b"GIF87a", b"GIF89a")):
            return "image/gif"
        if data.startswith(b"BM"):
            return "image/bmp"
        if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
            return "image/webp"
        if data.startswith(b"%PDF-"):
            return "application/pdf"
        if data.startswith(b"PK\x03\x04"):
            if extension == ".docx":
                try:
                    import io
                    with zipfile.ZipFile(io.BytesIO(data)) as archive:
                        if "word/document.xml" in archive.namelist():
                            return AttachmentManager.DOCUMENT_MIMES[".docx"]
                except (OSError, zipfile.BadZipFile):
                    pass
            return "application/zip"
        sample = data[:4096]
        if sample.startswith((b"\xff\xfe", b"\xfe\xff")):
            return "text/plain"
        controls = sum(byte < 32 and byte not in (9, 10, 12, 13) for byte in sample)
        if b"\x00" not in sample and (not sample or controls / len(sample) <= 0.01):
            return "text/plain"
        return "application/octet-stream"

    def validate_attachment(self, filename: str, data: bytes) -> tuple[str, int]:
        self._ensure_open()
        name = self._safe_name(filename)
        extension = Path(name).suffix.lower()
        if not isinstance(data, (bytes, bytearray, memoryview)):
            raise TypeError("attachment content must be bytes-like")
        raw = bytes(data)
        size = len(raw)
        if extension in self.IMAGE_MIMES:
            if size > self.max_image_bytes:
                raise _legacy.AttachmentError("حجم تصویر از محدودیت مجاز بیشتر است.")
            expected = self.IMAGE_MIMES[extension]
        elif extension == ".pdf" or extension == ".docx" or extension == ".zip":
            if size > self.max_file_bytes:
                raise _legacy.AttachmentError("حجم فایل از محدودیت مجاز بیشتر است.")
            expected = self.DOCUMENT_MIMES[extension]
        elif extension in self.TEXT_EXTENSIONS:
            if size > self.max_file_bytes:
                raise _legacy.AttachmentError("حجم فایل از محدودیت مجاز بیشتر است.")
            expected = "text/plain"
        else:
            raise _legacy.AttachmentError("این نوع فایل در نسخه فعلی پشتیبانی نمی‌شود.")

        actual = self._sniff(raw, extension)
        if expected.startswith("image/") and actual != expected:
            raise _legacy.AttachmentError("نوع واقعی تصویر با پسوند فایل مطابقت ندارد.")
        if expected == "application/pdf" and actual != expected:
            raise _legacy.AttachmentError("محتوای فایل PDF معتبر نیست.")
        if expected.endswith("wordprocessingml.document") and actual != expected:
            raise _legacy.AttachmentError("محتوای فایل Word معتبر نیست.")
        if expected == "application/zip" and actual != expected:
            raise _legacy.AttachmentError("محتوای فایل ZIP معتبر نیست.")
        if expected == "text/plain" and actual != expected:
            raise _legacy.AttachmentError("محتوای فایل متنی معتبر نیست.")
        return expected, size

    def add_attachment(
        self,
        source: str | os.PathLike[str] | bytes | bytearray | memoryview,
        *,
        filename: str | None = None,
        session_id: str,
        message_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> Attachment:
        self._ensure_open()
        owner = str(session_id or "").strip()
        if not owner:
            raise ValueError("session_id must not be empty")
        if isinstance(source, (bytes, bytearray, memoryview)):
            if not filename:
                raise ValueError("filename is required for in-memory attachments")
            raw = bytes(source)
            origin = AttachmentSource.MEMORY
            name = self._safe_name(filename)
        else:
            source_path = Path(source).expanduser()
            try:
                if source_path.is_symlink() or not source_path.is_file():
                    raise _legacy.AttachmentError("مسیر فایل معتبر نیست.")
                name = self._safe_name(filename or source_path.name)
                if source_path.stat().st_size > max(self.max_file_bytes, self.max_image_bytes):
                    raise _legacy.AttachmentError("حجم فایل از محدودیت مجاز بیشتر است.")
                raw = source_path.read_bytes()
            except OSError as exc:
                raise _legacy.AttachmentError("فایل قابل خواندن نیست.") from exc
            origin = AttachmentSource.FILE

        mime_type, size = self.validate_attachment(name, raw)
        existing_count = sum(
            1 for item in self._records.values()
            if item.session_id == owner
            and item.message_id == (str(message_id) if message_id is not None else None)
            and item.status is AttachmentStatus.READY
        )
        if existing_count >= self.max_files:
            raise _legacy.AttachmentError(f"حداکثر {self.max_files} ضمیمه برای هر پیام.")
        digest = hashlib.sha256(raw).hexdigest()
        index_key = (owner, str(message_id or ""), digest)
        existing_id = self._content_index.get(index_key)
        if existing_id:
            existing = self._records.get(existing_id)
            if existing and existing.status is AttachmentStatus.READY:
                if message_id and existing.message_id != message_id:
                    return Attachment(
                        attachment_id=existing.attachment_id, message_id=message_id,
                        session_id=owner, filename=existing.filename,
                        mime_type=existing.mime_type, size=existing.size,
                        source=existing.source, path=existing.path,
                        metadata=existing.metadata, status=existing.status,
                    )
                return existing

        attachment_id = uuid.uuid4().hex
        session_dir = self._root / hashlib.sha256(owner.encode("utf-8")).hexdigest()[:24]
        session_dir.mkdir(parents=True, exist_ok=True)
        target = (session_dir / f"{attachment_id}{Path(name).suffix.lower()}").resolve()
        if not target.is_relative_to(session_dir.resolve()):
            raise _legacy.AttachmentError("مسیر ذخیره‌سازی ضمیمه نامعتبر است.")
        try:
            with target.open("xb") as stream:
                stream.write(raw)
        except OSError as exc:
            raise _legacy.AttachmentError("ذخیره‌سازی موقت فایل ناموفق بود.") from exc

        record = Attachment(
            attachment_id=attachment_id, message_id=str(message_id) if message_id else None,
            session_id=owner, filename=name, mime_type=mime_type, size=size,
            source=origin, path=str(target), metadata={
                **dict(metadata or {}), "sha256": digest, "extension": Path(name).suffix.lower(),
            },
        )
        self._records[attachment_id] = record
        self._content_index[index_key] = attachment_id
        return record

    def get_attachment(self, attachment_id: str, *, session_id: str | None = None) -> Attachment | None:
        self._ensure_open()
        record = self._records.get(str(attachment_id or ""))
        if record is None or record.status is not AttachmentStatus.READY:
            return None
        if session_id is not None and record.session_id != str(session_id):
            return None
        return record

    def list_attachments(
        self, *, session_id: str, message_id: str | None = None
    ) -> tuple[Attachment, ...]:
        self._ensure_open()
        owner = str(session_id or "")
        return tuple(
            record for record in self._records.values()
            if record.session_id == owner and record.status is AttachmentStatus.READY
            and (message_id is None or record.message_id == str(message_id))
        )

    def prepare_content(
        self, attachment_ids: list[str] | tuple[str, ...], *, session_id: str,
        text: str = "", search: bool = False,
    ) -> dict[str, Any]:
        self._ensure_open()
        prepared = []
        for attachment_id in attachment_ids:
            record = self.get_attachment(attachment_id, session_id=session_id)
            if record is None:
                raise _legacy.AttachmentError("ضمیمه وجود ندارد یا متعلق به این نشست نیست.")
            try:
                prepared.append(_legacy.load_attachment(record.path))
            except (OSError, _legacy.AttachmentError) as exc:
                raise _legacy.AttachmentError(f"پردازش فایل «{record.filename}» ناموفق بود.") from exc
        return _legacy.compose(text, prepared, search=search)

    def remove_attachment(self, attachment_id: str, *, session_id: str) -> bool:
        self._ensure_open()
        record = self._records.get(str(attachment_id or ""))
        if record is None or record.session_id != str(session_id or ""):
            return False
        path = Path(record.path).resolve()
        owner_dir = (self._root / hashlib.sha256(record.session_id.encode("utf-8")).hexdigest()[:24]).resolve()
        if not path.is_relative_to(owner_dir) or not path.is_relative_to(self._root):
            return False
        try:
            path.unlink(missing_ok=True)
        except OSError:
            return False
        removed = Attachment(
            attachment_id=record.attachment_id, message_id=record.message_id,
            session_id=record.session_id, filename=record.filename,
            mime_type=record.mime_type, size=record.size, source=record.source,
            path=record.path, metadata=record.metadata, status=AttachmentStatus.REMOVED,
        )
        self._records[record.attachment_id] = removed
        self._content_index.pop((record.session_id, str(record.message_id or ""), str(record.metadata.get("sha256", ""))), None)
        return True

    def cleanup(self, *, session_id: str | None = None) -> int:
        self._ensure_open()
        records = [
            record for record in self._records.values()
            if record.status is AttachmentStatus.READY
            and (session_id is None or record.session_id == str(session_id))
        ]
        removed = sum(self.remove_attachment(record.attachment_id, session_id=record.session_id) for record in records)
        if session_id is not None:
            owner_dir = (self._root / hashlib.sha256(str(session_id).encode("utf-8")).hexdigest()[:24]).resolve()
            if owner_dir.is_relative_to(self._root):
                try:
                    owner_dir.rmdir()
                except OSError:
                    pass
        return removed

    def close(self) -> None:
        if self._closed:
            return
        self.cleanup()
        self._closed = True
        if self._owns_root:
            shutil.rmtree(self._root, ignore_errors=True)

    def __enter__(self) -> "AttachmentManager":
        self._ensure_open()
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.close()


AttachmentError = _legacy.AttachmentError
\n\n# Compatibility surface for the existing Qt worker/controller during migration.\nAttachmentError = _legacy.AttachmentError\nIMAGE_TYPES = _legacy.IMAGE_TYPES\nMAX_FILES = _legacy.MAX_FILES\nMAX_IMAGE_BYTES = _legacy.MAX_IMAGE_BYTES\nMAX_FILE_BYTES = _legacy.MAX_FILE_BYTES\nload_attachment = _legacy.load_attachment\nimage_attachment = _legacy.image_attachment\ncompose = _legacy.compose\nsummary = _legacy.summary\n