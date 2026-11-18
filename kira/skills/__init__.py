"""Shared, installable, character-neutral Skills."""
from .registry import SkillError, SkillManifest, SkillRegistry
from .service import SharedSkillService

__all__ = ["SkillError", "SkillManifest", "SkillRegistry", "SharedSkillService"]
