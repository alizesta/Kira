"""Core-owned Persistence port for atomic Chat history imports and exports."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol



class ChatTransferFilePort(Protocol):
    """File-system adapter for bounded import reads and atomic export writes."""

    def read_bytes(self, source: Path) -> bytes:
        """Read one regular import file; the Application layer enforces size limits."""
        ...

    def write_bytes_atomically(
        self,
        directory: Path,
        filename: str,
        content: bytes,
    ) -> Path:
        """Write complete bytes using a temporary file and atomic replacement."""
        ...


class ChatTransferRepositoryPort(Protocol):
    """Read export records and commit validated imports through Persistence."""

    def list_conversations(
        self, character_id: str | None = None
    ) -> list[dict[str, Any]]: ...

    def get_transfer_messages(
        self,
        conversation_id: str,
        character_id: str,
        after_created_at: str = "",
        after_id: int = 0,
        limit: int = 1000,
    ) -> list[dict[str, Any]]: ...

    def messages_after(
        self, after_id: int = 0, limit: int = 500
    ) -> list[dict[str, Any]]: ...

    def import_transfer_records(
        self,
        conversations: list[dict[str, Any]],
        messages: list[dict[str, Any]],
    ) -> dict[str, Any]: ...


__all__ = ["ChatTransferFilePort", "ChatTransferRepositoryPort"]
