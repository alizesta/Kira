"""Application policy adapter for game-mode capability permissions."""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable

from ..game_mode_policy import (
    COMPETITIVE_SAFE_MODE,
    STORY_MODE,
    game_mode_permissions,
    normalize_game_mode_profile,
    tool_categories_allowed,
)
from ..game_audio_policy import is_important_game_audio


@dataclass(frozen=True)
class GameAudioAlert:
    category: str
    message: str
    emotion: str


class GameModeApplicationService:
    """Expose game-mode decisions to UI/application adapters through one contract."""

    STORY_MODE = STORY_MODE
    COMPETITIVE_SAFE_MODE = COMPETITIVE_SAFE_MODE

    def __init__(self) -> None:
        self._game_audio_alerts: dict[str, tuple[float, str]] = {}

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

    def classify_game_audio(
        self,
        text: str,
        *,
        now: float,
        enabled: bool,
        profile: str | None,
        busy: bool,
        speaking: bool,
    ) -> GameAudioAlert | None:
        """Apply game-mode permission, importance, category and cooldown policy."""
        if (
            not enabled
            or not self.can_emit_automatic_game_audio_alerts(profile)
            or busy
            or speaking
            or not is_important_game_audio(text)
        ):
            return None
        lower = str(text).casefold()
        category = (
            "urgent"
            if re.search(
                r"low health|low hp|critical|danger|warning|خطر|هشدار|خونت کم|جونت کم",
                lower,
                re.I,
            )
            else "complete"
            if re.search(
                r"mission complete|quest complete|victory|achievement|مرحله تمام|ماموریت تمام|دستاورد",
                lower,
                re.I,
            )
            else "combat"
        )
        previous = self._game_audio_alerts.get(category, (0.0, ""))
        if now - previous[0] < 25 or lower == previous[1]:
            return None
        self._game_audio_alerts[category] = (now, lower)
        messages = {
            "urgent": "حواست باشه، از صدای بازی هشدار خطر یا کمبود سلامتی شنیدم.",
            "complete": "به نظر می‌رسه یک مرحله، مأموریت یا دستاورد مهم تکمیل شده.",
            "combat": "به نظر می‌رسه اتفاق مهمی در مبارزه یا نزدیک‌شدن دشمن رخ داده.",
        }
        return GameAudioAlert(
            category=category,
            message=messages[category],
            emotion="surprised" if category == "urgent" else "thinking",
        )

    def command_denial_reason(self, profile: str | None, required_permissions: Iterable[str]) -> str | None:
        required = set(required_permissions or ())
        if "desktop.launch" in required and not self.can_use_input_automation(profile):
            return "در حالت Competitive Safe اجرای میانبرهای دسکتاپ غیرفعال است."
        return None
