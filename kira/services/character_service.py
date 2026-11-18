"""Application adapter for built-in and user-editable character profiles."""
from __future__ import annotations

from pathlib import Path

from .. import characters


class CharacterProfileService:
    """Expose character profile operations behind a consumer-facing service contract."""

    def active_id(self, settings: dict) -> str:
        return characters.active_id(settings)

    def all_profiles(self, settings: dict) -> dict[str, dict]:
        return characters.all_profiles(settings)

    def active(self, settings: dict) -> dict:
        return characters.active(settings)

    def display_name(self, settings: dict) -> str:
        return characters.display_name(settings)

    def prompt_for(self, settings: dict) -> str:
        return characters.prompt_for(settings)

    def avatar_file(self, profile: dict, root: str | Path) -> Path | None:
        return characters.avatar_file(profile, root)

    def is_builtin(self, character_id: str) -> bool:
        return str(character_id or "") in characters.CHARACTERS
