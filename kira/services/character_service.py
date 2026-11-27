"""Application adapter for built-in and user-editable character profiles."""
from __future__ import annotations

from pathlib import Path
import time
import math
import re

from .. import characters


class CharacterProfileService:
    """Own character profile and per-character preference mutations."""

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

    def chat_background_file(self, profile: dict, root: str | Path) -> Path | None:
        return characters.chat_background_file(profile, root)

    def is_builtin(self, character_id: str) -> bool:
        return str(character_id or "") in characters.CHARACTERS

    def create_profile(self, settings: dict, name: str, description: str = "", prompt: str = "") -> dict:
        name = str(name or "").strip()
        if not name:
            raise ValueError("Character name cannot be empty.")
        character_id = "custom_" + str(time.time_ns())
        profile = {
            "id": character_id,
            "name": name,
            "name_fa": name,
            "gender": "unspecified",
            "description": str(description or "").strip(),
            "image": "assets/characters/ren.svg",
            "prompt": str(prompt or "").strip(),
        }
        settings.setdefault("characters", []).append(profile)
        settings.setdefault("character_voice", {}).setdefault(character_id, {})
        settings.setdefault("character_notes", {}).setdefault(character_id, "")
        settings.setdefault("character_resources", {}).setdefault(character_id, {})
        settings["active_character_id"] = character_id
        return dict(profile)

    def update_profile(
        self, settings: dict, character_id: str, *, name: str, description: str, prompt: str
    ) -> dict:
        character_id = str(character_id or "")
        if character_id == "kira":
            raise ValueError("The default Kira profile cannot be edited.")
        profiles = settings.setdefault("characters", [])
        target_index = next(
            (index for index, item in enumerate(profiles)
             if isinstance(item, dict) and str(item.get("id") or "") == character_id),
            None,
        )
        if target_index is None:
            base = self.all_profiles(settings).get(character_id)
            if base is None:
                raise KeyError(character_id)
            updated = dict(base)
        else:
            updated = dict(profiles[target_index])
        updated.update({
            "name": str(name or "").strip(),
            "name_fa": str(name or "").strip(),
            "description": str(description or "").strip(),
            "prompt": str(prompt or "").strip(),
        })
        if not updated["name"]:
            raise ValueError("Character name cannot be empty.")
        if target_index is None:
            profiles.append(updated)
        else:
            profiles[target_index] = updated
        return dict(updated)

    def delete_profile(self, settings: dict, character_id: str) -> bool:
        character_id = str(character_id or "")
        if character_id == "kira":
            raise ValueError("The default Kira profile cannot be deleted.")
        if character_id not in self.all_profiles(settings):
            return False
        if self.is_builtin(character_id):
            hidden = settings.setdefault("deleted_character_ids", [])
            if character_id not in hidden:
                hidden.append(character_id)
            settings["characters"] = [
                item for item in settings.get("characters", [])
                if not isinstance(item, dict) or str(item.get("id") or "") != character_id
            ]
        else:
            settings["characters"] = [
                item for item in settings.get("characters", [])
                if not isinstance(item, dict) or str(item.get("id") or "") != character_id
            ]
        settings["active_character_id"] = "kira"
        for key in (
            "character_voice", "character_notes", "character_resources", "character_traits",
            "character_initiative", "character_initiative_history",
        ):
            bucket = settings.get(key)
            if isinstance(bucket, dict):
                bucket.pop(character_id, None)
        return True

    def set_active(self, settings: dict, character_id: str) -> str:
        character_id = str(character_id or "")
        if character_id not in self.all_profiles(settings):
            raise KeyError(character_id)
        settings["active_character_id"] = character_id
        return character_id

    @staticmethod
    def _resource_values(value) -> list[str]:
        if isinstance(value, str):
            value = re.split(r"[,;\n]+", value)
        if not isinstance(value, (list, tuple)):
            return []
        result = []
        for item in value:
            label = str(item or "").strip()
            if label and label not in result:
                result.append(label[:120])
        return result[:30]

    def save_preferences(
        self, settings: dict, character_id: str, *, voice: dict, resources: dict, notes: str | None = None
    ) -> None:
        character_id = str(character_id or "")
        if character_id not in self.all_profiles(settings):
            raise KeyError(character_id)
        voice_values = {}
        if "voice_rate" in voice:
            voice_values["voice_rate"] = int(voice["voice_rate"])
        if "voice_volume" in voice:
            volume = float(voice["voice_volume"])
            if not math.isfinite(volume):
                raise ValueError("Character voice volume must be finite.")
            voice_values["voice_volume"] = max(0.0, min(1.0, volume))
        settings.setdefault("character_voice", {})[character_id] = voice_values
        settings.setdefault("character_resources", {})[character_id] = {
            key: self._resource_values(resources.get(key))
            for key in ("skills", "mcp", "connectors")
        }
        if notes is not None:
            settings.setdefault("character_notes", {})[character_id] = str(notes).strip()[:12000]

    def save_personality(self, settings: dict, character_id: str, *, traits: dict, notes: str | None = None) -> dict:
        character_id = str(character_id or "")
        if character_id not in self.all_profiles(settings):
            raise KeyError(character_id)
        clean = {}
        for key, value in (traits or {}).items():
            try:
                number = float(value)
            except (TypeError, ValueError):
                continue
            if math.isfinite(number):
                clean[str(key)[:64]] = max(0.0, min(1.0, number))
        settings.setdefault("character_traits", {})[character_id] = clean
        if notes is not None:
            settings.setdefault("character_notes", {})[character_id] = str(notes).strip()[:12000]
        return dict(clean)
