"""Character profiles and character-independent decision engines."""
from .registry import CharacterRegistry, DEFAULT_CHARACTER_ID
from ..personas import (
    CHARACTERS,
    active,
    active_id,
    all_profiles,
    avatar_file,
    display_name,
    prompt_for,
)

__all__ = [
    "CharacterRegistry",
    "DEFAULT_CHARACTER_ID",
    "CHARACTERS",
    "active",
    "active_id",
    "all_profiles",
    "avatar_file",
    "display_name",
    "prompt_for",
]
