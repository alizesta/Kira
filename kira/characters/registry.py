"""Persistent, provider-neutral character profile registry.

Profiles are user data stored outside the application folder. The app brand and
AI/provider routing never depend on a character's name or personality.
"""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import shutil
import re
import uuid

from .kira import PROFILE as KIRA_PROFILE

DEFAULT_CHARACTER_ID = "kira"


def _normalise_profile(profile):
    if not isinstance(profile, dict):
        raise ValueError("Character profile must be an object.")
    pid = str(profile.get("id") or "").strip()
    name = str(profile.get("name") or "").strip()
    if not pid or not name:
        raise ValueError("Character profile needs an id and a name.")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", pid):
        raise ValueError("Character profile id contains unsupported path characters.")
    avatar_model_path = str(profile.get("avatar_model_path") or "").strip()[:4096]
    default_avatar = profile.get("avatar_default_enabled")
    if default_avatar is None:
        default_avatar = pid == DEFAULT_CHARACTER_ID and not avatar_model_path
    clean = {
        "id": pid[:80],
        "name": name[:80],
        "description": str(profile.get("description") or "").strip()[:4000],
        "notes": str(profile.get("notes") or "").strip()[:12000],
        "system_prompt": str(profile.get("system_prompt") or "").strip()[:30000],
        # Custom paths stay in user data; Kira's default is resolved from the project root.
        "avatar_model_path": avatar_model_path,
        "avatar_default_enabled": bool(default_avatar),
        "traits": {},
        "built_in": bool(profile.get("built_in", False)),
    }
    traits = profile.get("traits")
    if isinstance(traits, dict):
        for key, value in traits.items():
            try:
                clean["traits"][str(key)[:64]] = max(0.0, min(1.0, float(value)))
            except (TypeError, ValueError):
                continue
    return clean


class CharacterRegistry:
    """Load, create, edit, select and remove character profiles."""

    def __init__(self, data_dir, active_id=DEFAULT_CHARACTER_ID, legacy_name="", legacy_notes=""):
        self.directory = Path(data_dir) / "characters"
        self.path = self.directory / "profiles.json"
        self.directory.mkdir(parents=True, exist_ok=True)
        self.profiles = {}
        self.active_id = DEFAULT_CHARACTER_ID
        self.warnings = []
        self._load(str(active_id or DEFAULT_CHARACTER_ID), legacy_name, legacy_notes)

    def _load(self, requested_active, legacy_name, legacy_notes):
        payload = {}
        if self.path.exists():
            try:
                payload = json.loads(self.path.read_text(encoding="utf-8"))
                if not isinstance(payload, dict):
                    raise ValueError("invalid character registry root")
            except Exception as exc:
                backup = self.path.with_suffix(".corrupt.json")
                try:
                    backup.write_bytes(self.path.read_bytes())
                except OSError:
                    backup = None
                suffix = f" Backup: {backup.name}" if backup else ""
                self.warnings.append(f"Character profiles could not be read ({exc}).{suffix}")
                payload = {}
        raw_profiles = payload.get("profiles", [])
        if isinstance(raw_profiles, dict):
            raw_profiles = list(raw_profiles.values())
        for item in raw_profiles if isinstance(raw_profiles, list) else []:
            try:
                profile = _normalise_profile(item)
                self.profiles[profile["id"]] = profile
            except (ValueError, TypeError):
                continue

        if DEFAULT_CHARACTER_ID not in self.profiles:
            initial = deepcopy(KIRA_PROFILE)
            if legacy_name and str(legacy_name).strip():
                initial["name"] = str(legacy_name).strip()
            if legacy_notes and str(legacy_notes).strip():
                initial["notes"] = str(legacy_notes).strip()
            self.profiles[DEFAULT_CHARACTER_ID] = _normalise_profile(initial)
        self.active_id = str(payload.get("active_id") or requested_active)
        if self.active_id not in self.profiles:
            self.active_id = DEFAULT_CHARACTER_ID
        self.save()

    def save(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema": 1,
            "active_id": self.active_id,
            "profiles": [self.profiles[key] for key in sorted(self.profiles)],
        }
        temp = self.path.with_suffix(".json.tmp")
        temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(self.path)

    def list_profiles(self):
        return [deepcopy(self.profiles[key]) for key in sorted(
            self.profiles, key=lambda key: (key != self.active_id, self.profiles[key]["name"].casefold())
        )]

    def get(self, profile_id):
        profile = self.profiles.get(str(profile_id or ""))
        return deepcopy(profile) if profile else None

    @property
    def active_profile(self):
        return self.get(self.active_id) or self.get(DEFAULT_CHARACTER_ID)

    def set_active(self, profile_id):
        profile_id = str(profile_id or "")
        if profile_id not in self.profiles:
            raise KeyError(profile_id)
        self.active_id = profile_id
        self.save()
        return self.active_profile

    @staticmethod
    def _new_id(name):
        base = re.sub(r"[^a-z0-9]+", "-", str(name or "").lower()).strip("-")[:40] or "character"
        return f"{base}-{uuid.uuid4().hex[:6]}"

    def create(self, name, description=""):
        name = str(name or "").strip()
        if not name:
            raise ValueError("Character name cannot be empty.")
        pid = self._new_id(name)
        profile = _normalise_profile({
            "id": pid,
            "name": name,
            "description": description,
            "notes": "",
            "system_prompt": "",
            "traits": deepcopy(KIRA_PROFILE.get("traits", {})),
            "built_in": False,
        })
        self.profiles[pid] = profile
        self.active_id = pid
        self.save()
        return deepcopy(profile)

    def update(self, profile_id, **changes):
        profile_id = str(profile_id or "")
        if profile_id not in self.profiles:
            raise KeyError(profile_id)
        allowed = {"name", "description", "notes", "system_prompt", "traits", "avatar_model_path", "avatar_default_enabled"}
        current = deepcopy(self.profiles[profile_id])
        for key, value in changes.items():
            if key in allowed:
                current[key] = value
        self.profiles[profile_id] = _normalise_profile(current)
        self.save()
        return deepcopy(self.profiles[profile_id])

    def delete(self, profile_id):
        profile_id = str(profile_id or "")
        if profile_id == DEFAULT_CHARACTER_ID:
            raise ValueError("The built-in Kira profile cannot be deleted.")
        if profile_id not in self.profiles:
            return False
        profile_dir = self.directory / profile_id
        if profile_dir.exists():
            # Character-scoped voice and emotional state belong to the profile being deleted.
            # The shared user facts and shared chat history live elsewhere and are untouched.
            shutil.rmtree(profile_dir)
        del self.profiles[profile_id]
        if self.active_id == profile_id:
            self.active_id = DEFAULT_CHARACTER_ID
        self.save()
        return True
