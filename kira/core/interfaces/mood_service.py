"""Consumer-facing contract for the shared companion mood state."""
from __future__ import annotations

from typing import Any, Protocol


class MoodService(Protocol):
    def current(self) -> dict[str, Any]: ...

    def reset(self) -> None: ...
