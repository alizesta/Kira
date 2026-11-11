"""Where Kira keeps the user's data, and how it is carried over / backed up.

User data lives OUTSIDE the program folder (%LOCALAPPDATA%\\Kira on Windows) so replacing the program folder with
a new version never touches settings, API keys or chat history. Old data is only ever COPIED, never moved or deleted.
"""
from __future__ import annotations

import os
import shutil
import sqlite3
import time
from pathlib import Path

SETTINGS_NAME = "settings.json"
DB_NAME = "kira_memory.sqlite3"
EVIDENCE_DB_NAME = "kira_evidence.sqlite3"            # facts with provenance (kira/evidence_memory.py); an index that can also be rebuilt from the chat
PERSONA_MEMORY_NAME = "kira_persona_memory.json"      # local voice/fact/moment/digest memory
CLOUD_VOICE_NAME = "cloud_voice.json"                     # Cloud Voice keys + settings (kept outside the program folder, like settings.json)
MARKER = "migrated_from.txt"


def default_data_dir(root: Path) -> Path:
    env = os.environ.get("KIRA_DATA_DIR")
    if env:
        return Path(env)
    local = os.environ.get("LOCALAPPDATA")
    if local:
        return Path(local) / "Kira"
    return root / "data"                      # non-Windows development fallback


def persona_memory_files(folder: Path):
    """All built-in/custom character memory JSON files in one user-data directory."""
    try:
        return sorted(p for p in folder.glob("kira_persona_memory*.json") if p.is_file())
    except OSError:
        return []


def has_user_data(folder: Path) -> bool:
    return (any((folder / n).is_file() for n in (SETTINGS_NAME, DB_NAME, EVIDENCE_DB_NAME, CLOUD_VOICE_NAME))
            or bool(persona_memory_files(folder)))


def legacy_candidates(root: Path):
    """Old data folders, newest first: the program's own ./data, then ./data of sibling Kira folders
    (people unzip every new version next to the old one)."""
    found = []
    own = root / "data"
    if has_user_data(own):
        found.append(own)
    try:
        siblings = [p / "data" for p in root.parent.iterdir()
                    if p.is_dir() and p != root and "kira" in p.name.lower() and has_user_data(p / "data")]
    except OSError:
        siblings = []
    siblings.sort(key=lambda d: max((f.stat().st_mtime for f in d.glob("*") if f.is_file()), default=0), reverse=True)
    return found + siblings


def migrate_legacy(new_dir: Path, candidates) -> str | None:
    """Copy settings and/or chat history from an old data folder into the new one. COPY ONLY, never overwrites.

    Each file is carried over on its own: a new folder that already has settings.json but no chat database still gets the
    old chat history (this used to be skipped, which looked like 'my chats disappeared after updating').
    Runs once: after the first migration a marker file stops it, so deleted data is never resurrected."""
    new_dir.mkdir(parents=True, exist_ok=True)
    if (new_dir / MARKER).exists():
        return None
    fixed_names = (SETTINGS_NAME, DB_NAME, EVIDENCE_DB_NAME, CLOUD_VOICE_NAME)
    for source in candidates:
        source_path = Path(source)
        if source_path.resolve() == new_dir.resolve() or not has_user_data(source_path):
            continue
        missing = [name for name in fixed_names if not (new_dir / name).is_file()]
        missing.extend(p.name for p in persona_memory_files(source_path) if not (new_dir / p.name).is_file())
        if not missing:
            continue
        copied = []
        for name in missing:
            src = Path(source) / name
            if src.is_file():
                shutil.copy2(src, new_dir / name)
                copied.append(name)
        if not copied:
            continue
        (new_dir / MARKER).write_text(f"{source}\n", encoding="utf-8")
        return f"اطلاعات نسخه‌ی قبلی ({', '.join(copied)}) از «{source}» کپی شد. پوشه‌ی قدیمی دست‌نخورده ماند."
    return None


def backup_user_data(data_dir: Path, keep: int = 7, min_age_hours: float = 12.0) -> Path | None:
    """Rolling backup of settings + chat history (SQLite online-backup API, safe while the DB is in use)."""
    if not has_user_data(data_dir):
        return None
    root = data_dir / "backups"
    root.mkdir(exist_ok=True)
    existing = sorted(p for p in root.iterdir() if p.is_dir())
    if existing and time.time() - existing[-1].stat().st_mtime < min_age_hours * 3600:
        return None
    target = root / time.strftime("%Y%m%d-%H%M%S")
    target.mkdir()
    if (data_dir / SETTINGS_NAME).is_file():
        shutil.copy2(data_dir / SETTINGS_NAME, target / SETTINGS_NAME)
    if (data_dir / CLOUD_VOICE_NAME).is_file():
        shutil.copy2(data_dir / CLOUD_VOICE_NAME, target / CLOUD_VOICE_NAME)
    for source in persona_memory_files(data_dir):
        shutil.copy2(source, target / source.name)
    for db_name in (DB_NAME, EVIDENCE_DB_NAME):
        if (data_dir / db_name).is_file():
            src = sqlite3.connect(data_dir / db_name)
            try:
                dst = sqlite3.connect(target / db_name)
                try:
                    src.backup(dst)
                finally:
                    dst.close()
            finally:
                src.close()
    for old in sorted(p for p in root.iterdir() if p.is_dir())[:-keep]:
        shutil.rmtree(old, ignore_errors=True)
    return target


if __name__ == "__main__":
    # python -m kira.storage "C:\path\to\old\Project_Kira\data"   -> copy data from a specific old folder
    import sys
    from .config import DATA_DIR
    if len(sys.argv) > 1:
        print(migrate_legacy(DATA_DIR, [Path(sys.argv[1])]) or f"Nothing copied ({DATA_DIR} already has data).")
    else:
        print("Data folder:", DATA_DIR)
