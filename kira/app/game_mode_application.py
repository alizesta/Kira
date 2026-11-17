"""Application policy adapter for game-mode capability permissions."""
from __future__ import annotations

from typing import Iterable

from ..game_mode_policy import (
    COMPETITIVE_SAFE_MODE,
    STORY_MODE,
    game_mode_permissions,
    normalize_game_mode_profile,
    tool_categories_allowed,
)


class GameModeApplicationService:
    """Expose game-mode decisions to UI/application adapters through one contract."""

    STORY_MODE = STORY_MODE
    COMPETITIVE_SAFE_MODE = COMPETITIVE_SAFE_MODE

    @staticmethod
    def normalize_profile(profile: str | None) -> str:
        return normalize_game_mode_profile(profile)

    @staticmethod
    def permissions(profile: str | None) -> dict[str, bool]:
        return game_mode_permissions(profile)

    def is_story(self, profile: str | None) -> bool:
        return self.normalize_profile(profile) == self.STORY_MODE

    def is_competitive_safe(self, profile: str | None) -> bool:
        return self.normalize_profile(profile) == self.COMPETITIVE_SAFE_MODE

    def can_capture_vision(self, profile: str | None) -> bool:
        return self.permissions(profile)["vision_capture"]

    def can_use_game_audio_loopback(self, profile: str | None) -> bool:
        return self.permissions(profile)["game_audio_loopback"]

    def can_emit_automatic_game_audio_alerts(self, profile: str | None) -> bool:
        return self.permissions(profile)["automatic_game_audio_alerts"]

    def can_use_input_automation(self, profile: str | None) -> bool:
        return self.permissions(profile)["input_automation"]

    def tool_categories_allowed(self, profile: str | None, categories: Iterable[str]) -> bool:
        return tool_categories_allowed(profile, categories)

    def command_denial_reason(self, profile: str | None, required_permissions: Iterable[str]) -> str | None:
        required = set(required_permissions or ())
        if "desktop.launch" in required and not self.can_use_input_automation(profile):
            return "در حالت Competitive Safe اجرای میانبرهای دسکتاپ غیرفعال است."
        return None
