"""Application boundary for the shared, installable Skills feature."""
from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, Callable

from ..skills import SharedSkillService, SkillManifest


class SharedSkillsApplicationService:
    """Own Skill use cases, settings persistence and the domain service lifecycle."""

    def __init__(
        self,
        root: str | Path,
        settings: dict[str, Any],
        *,
        persist_settings: Callable[[dict[str, Any]], Any],
    ) -> None:
        if not isinstance(settings, dict):
            raise TypeError("settings must be a dictionary")
        if not callable(persist_settings):
            raise TypeError("persist_settings must be callable")
        self._settings = settings
        self._persist_settings = persist_settings
        self._skills = SharedSkillService(root)
        self._started = False
        self._disposed = False

    def start(self) -> None:
        if self._disposed:
            raise RuntimeError("Shared Skills service has been disposed")
        self._skills.list_installed()
        self._started = True

    def stop(self) -> None:
        self._started = False

    def dispose(self) -> None:
        self._started = False
        self._disposed = True

    def _ensure_available(self) -> None:
        if self._disposed:
            raise RuntimeError("Shared Skills service has been disposed")
        if not self._started:
            raise RuntimeError("Shared Skills service has not been started")

    def list_installed(self) -> tuple[SkillManifest, ...]:
        self._ensure_available()
        return self._skills.list_installed()

    def is_enabled(self, skill_id: str, character_id: str) -> bool:
        self._ensure_available()
        return skill_id in self._skills.enabled_for(self._settings, character_id)

    def is_globally_enabled(self, skill_id: str) -> bool:
        self._ensure_available()
        bucket = self._settings.get(SharedSkillService.SETTINGS_KEY, {})
        enabled = bucket.get("enabled", []) if isinstance(bucket, Mapping) else []
        return skill_id in enabled if isinstance(enabled, (list, tuple, set)) else False

    def install(self, source: str | Path) -> SkillManifest:
        self._ensure_available()
        return self._skills.install(source)

    def set_enabled(
        self, skill_id: str, enabled: bool, *, character_id: str | None = None
    ) -> None:
        self._ensure_available()
        self._skills.set_enabled(
            self._settings, skill_id, bool(enabled), character_id=character_id
        )
        self._persist_settings(self._settings)

    def uninstall(self, skill_id: str) -> bool:
        self._ensure_available()
        removed = self._skills.uninstall(skill_id, self._settings)
        if removed:
            self._persist_settings(self._settings)
        return removed

    def prompt_for(self, character_id: str) -> str:
        self._ensure_available()
        return self._skills.prompt_for(self._settings, character_id)
