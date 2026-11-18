"""Safe discovery and installation for instruction-only shared Skills.

A Skill is a directory containing manifest.json and SKILL.md. Skill files are
never imported or executed; they are rendered as bounded prompt instructions.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tempfile
import zipfile


SKILL_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,63}$")
MAX_SKILLS = 200
MAX_FILES = 64
MAX_FILE_BYTES = 256 * 1024
MAX_TOTAL_BYTES = 1024 * 1024
MAX_PROMPT_CHARS = 20_000


class SkillError(ValueError):
    """Invalid, unsafe, or unavailable Skill operation."""


@dataclass(frozen=True)
class SkillManifest:
    skill_id: str
    name: str
    version: str
    description: str
    entry: str = "SKILL.md"

    @classmethod
    def from_directory(cls, directory: Path) -> "SkillManifest":
        manifest_path = directory / "manifest.json"
        if not manifest_path.is_file() or manifest_path.is_symlink():
            raise SkillError("Skill must contain a regular manifest.json file.")
        try:
            raw = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise SkillError(f"Invalid Skill manifest: {exc}") from exc
        if not isinstance(raw, dict):
            raise SkillError("Skill manifest must be a JSON object.")
        skill_id = str(raw.get("id") or "").strip().lower()
        if not SKILL_ID_RE.fullmatch(skill_id):
            raise SkillError("Skill id must be 2-64 lowercase letters, digits, dots, underscores or hyphens.")
        name = str(raw.get("name") or "").strip()
        version = str(raw.get("version") or "").strip()
        description = str(raw.get("description") or "").strip()
        entry = str(raw.get("entry") or "SKILL.md").strip()
        if not name or len(name) > 120 or not version or len(version) > 40:
            raise SkillError("Skill name and version are required and must be short.")
        if len(description) > 500:
            raise SkillError("Skill description is too long.")
        if entry != "SKILL.md":
            raise SkillError("Only SKILL.md instruction files are supported.")
        content = directory / entry
        if not content.is_file() or content.is_symlink():
            raise SkillError("Skill must contain a regular SKILL.md file.")
        if content.stat().st_size > MAX_FILE_BYTES:
            raise SkillError("SKILL.md exceeds the 256 KiB limit.")
        return cls(skill_id, name, version, description, entry)


class SkillRegistry:
    """Own one shared on-disk library, independent of character profiles."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def discover(self) -> dict[str, SkillManifest]:
        found: dict[str, SkillManifest] = {}
        for directory in sorted(self.root.iterdir()):
            if not directory.is_dir() or directory.is_symlink():
                continue
            try:
                manifest = SkillManifest.from_directory(directory)
            except (OSError, SkillError):
                continue
            if directory.name == manifest.skill_id:
                found[manifest.skill_id] = manifest
        return found

    def get(self, skill_id: str) -> tuple[SkillManifest, str]:
        key = self._validate_id(skill_id)
        directory = (self.root / key).resolve()
        if directory.parent != self.root:
            raise SkillError("Invalid Skill location.")
        manifest = SkillManifest.from_directory(directory)
        if manifest.skill_id != key:
            raise SkillError("Skill directory and manifest ids do not match.")
        try:
            instructions = (directory / manifest.entry).read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise SkillError(f"Could not read Skill instructions: {exc}") from exc
        if not instructions.strip():
            raise SkillError("Skill instructions are empty.")
        return manifest, instructions[:MAX_FILE_BYTES]

    def install(self, source: str | Path) -> SkillManifest:
        """Install a directory or ZIP archive atomically; never execute bundled code."""
        source_path = Path(source).expanduser()
        if not source_path.exists():
            raise SkillError("Skill source does not exist.")
        staging = Path(tempfile.mkdtemp(prefix=".skill-install-", dir=str(self.root)))
        try:
            payload = staging / "payload"
            payload.mkdir()
            if source_path.is_dir():
                self._copy_directory(source_path.resolve(), payload)
            elif source_path.is_file() and zipfile.is_zipfile(source_path):
                self._extract_zip(source_path, payload)
            else:
                raise SkillError("Skill source must be a directory or ZIP archive.")
            skill_directory = self._locate_skill_directory(payload)
            manifest = SkillManifest.from_directory(skill_directory)
            if manifest.skill_id in self.discover():
                raise SkillError(f"Skill is already installed: {manifest.skill_id}")
            if len(self.discover()) >= MAX_SKILLS:
                raise SkillError("The shared Skill library has reached its 200 Skill limit.")
            target = self.root / manifest.skill_id
            if target.exists():
                raise SkillError(f"Skill target already exists: {manifest.skill_id}")
            shutil.move(str(skill_directory), str(target))
            return SkillManifest.from_directory(target)
        finally:
            shutil.rmtree(staging, ignore_errors=True)

    def uninstall(self, skill_id: str) -> bool:
        key = self._validate_id(skill_id)
        target = self.root / key
        if not target.exists():
            return False
        resolved = target.resolve()
        if resolved.parent != self.root or target.is_symlink() or not target.is_dir():
            raise SkillError("Refusing to remove an unsafe Skill path.")
        shutil.rmtree(target)
        return True

    @staticmethod
    def _validate_id(skill_id: str) -> str:
        key = str(skill_id or "").strip().lower()
        if not SKILL_ID_RE.fullmatch(key):
            raise SkillError("Invalid Skill id.")
        return key

    @staticmethod
    def _locate_skill_directory(payload: Path) -> Path:
        if (payload / "manifest.json").is_file():
            return payload
        candidates = [
            item for item in payload.iterdir()
            if item.is_dir() and (item / "manifest.json").is_file()
        ]
        if len(candidates) != 1:
            raise SkillError("ZIP must contain one Skill folder or manifest.json at its root.")
        return candidates[0]

    @staticmethod
    def _copy_directory(source: Path, destination: Path) -> None:
        files = 0
        total = 0
        for current, directories, filenames in os.walk(source, followlinks=False):
            current_path = Path(current)
            directories[:] = [
                name for name in directories
                if not (current_path / name).is_symlink()
            ]
            relative = current_path.relative_to(source)
            target_dir = destination / relative
            target_dir.mkdir(parents=True, exist_ok=True)
            for filename in filenames:
                src = current_path / filename
                if src.is_symlink() or not src.is_file():
                    continue
                size = src.stat().st_size
                files += 1
                total += size
                if files > MAX_FILES or size > MAX_FILE_BYTES or total > MAX_TOTAL_BYTES:
                    raise SkillError("Skill package exceeds file-count or size limits.")
                shutil.copy2(src, target_dir / filename)

    @staticmethod
    def _extract_zip(archive: Path, destination: Path) -> None:
        files = 0
        total = 0
        with zipfile.ZipFile(archive) as bundle:
            for info in bundle.infolist():
                if info.is_dir():
                    continue
                member = PurePosixPath(info.filename)
                mode = info.external_attr >> 16
                if (member.is_absolute() or ".." in member.parts or not member.parts
                        or any("\\" in part or ":" in part or "\x00" in part for part in member.parts)):
                    raise SkillError("ZIP contains an unsafe path.")
                if stat.S_ISLNK(mode):
                    raise SkillError("ZIP symlinks are not allowed.")
                files += 1
                total += info.file_size
                if files > MAX_FILES or info.file_size > MAX_FILE_BYTES or total > MAX_TOTAL_BYTES:
                    raise SkillError("Skill ZIP exceeds file-count or size limits.")
                target = destination.joinpath(*member.parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(info) as src, target.open("wb") as dst:
                    shutil.copyfileobj(src, dst)
