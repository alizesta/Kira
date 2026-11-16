"""Application service adapter for the shared companion mood state."""
from __future__ import annotations

from typing import Any

from .. import mood


class MoodStateService:
    def current(self) -> dict[str, Any]:
        return mood.current()

    def reset(self) -> None:
        mood.reset()
