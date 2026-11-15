"""Where Kira keeps the user's data, and how it is carried over / backed up.

User data lives OUTSIDE the program folder in A:\\Project KIRA\\Kira Attachments on Windows (with a safe
per-user fallback when A: is unavailable), so replacing the program folder never touches settings, API keys,
chat history or model caches. Old data is only ever COPIED, never moved or deleted.
"""
from __future__ import annotations

import os
import shutil
import sqlite3
import tempfile
import time
from pathlib import Path

SETTINGS_NAME = "settings.json"
DB_NAME = "kira_memory.sqlite3"
EVIDENCE_DB_NAME = "kira_evidence.sqlite3"            # facts with provenance (kira/evidence_memory.py); an index that can also be rebuilt from the chat
PERSONA_MEMORY_NAME = "kira_persona_memory.json"      # local voice/fact/moment/digest memory
CLOUD_VOICE_NAME = "cloud_voice.json"                     # Cloud Voice keys + settings (kept outside the program folder, like settings.json)
MARKER = "migrated_from.txt"
DATA_DIR_WARNING: str | None = None


def _writable_directory(path: Path) -> bool:
    """Create a directory and verify that this process can actually write to it."""
    try:
        path = Path(path)
        path.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(prefix=".kira-write-check-", dir=str(path)):
            pass
        return True
    except OSError:
        return False


def default_data_dir(root: Path) -> Path:
    """Resolve Kira's persistent data folder and verify it is writable before startup.

    KIRA_DATA_DIR is an explicit override (also used by tests and portable installs).
    On Windows, A:\\Project KIRA\\Kira Attachments is preferred. If the selected
    location exists but is read-only / disconnected / out of reach, fall back to
    the per-user data directory instead of crashing during configuration import.
    """
    global DATA_DIR_WARNING
    env = str(os.environ.get("KIRA_DATA_DIR") or "").strip()
    if env:
        primary = Path(env)
    elif os.name == "nt" and Path("A:/").exists():
        primary = Path("A:/Project KIRA/Kira Attachments")
    else:
        local = os.environ.get("LOCALAPPDATA")
        primary = Path(local) / "Kira" if local else Path(root) / "data"

    local = os.environ.get("LOCALAPPDATA")
    fallbacks = []
    if local:
        fallbacks.append(Path(local) / "Kira")
    fallbacks.append(Path(root) / "data")

    seen = set()
    candidates = [primary, *fallbacks]
    for candidate in candidates:
        key = str(candidate).casefold()
        if key in seen:
            continue
        seen.add(key)
        if _writable_directory(candidate):
            data_dir = candidate
            if candidate != primary:
                DATA_DIR_WARNING = (
                    f"مسیر ذخیره‌سازی اصلی «{primary}» قابل نوشتن نبود؛ "
                    f"اطلاعات Kira موقتاً در «{candidate}» ذخیره می‌شود."
                )
            else:
                DATA_DIR_WARNING = None
            # Keep child processes and model libraries on exactly the same path.
            os.environ["KIRA_DATA_DIR"] = str(data_dir)
            configure_cache_environment(data_dir)
            return data_dir

    raise OSError(
        "هیچ مسیر قابل‌نوشتنی برای اطلاعات Kira پیدا نشد. "
        "دسترسی درایو A و فضای خالی AppData را بررسی کن."
    )


def configure_cache_environment(data_dir: Path) -> None:
    """Route common AI/runtime caches into the same persistent Kira data folder."""
    cache_root = Path(data_dir) / "cache"
    paths = {
        "HF_HOME": Path(data_dir) / "huggingface",
        "HUGGINGFACE_HUB_CACHE": Path(data_dir) / "huggingface" / "hub",
        "HF_HUB_CACHE": Path(data_dir) / "huggingface" / "hub",
        "TRANSFORMERS_CACHE": Path(data_dir) / "huggingface" / "hub",
        "TORCH_HOME": cache_root / "torch",
        "XDG_CACHE_HOME": cache_root,
        "PIP_CACHE_DIR": cache_root / "pip",
    }
    for name, path in paths.items():
        os.environ[name] = str(path)


def persona_memory_files(folder: Path):
    """All built-in/custom character memory JSON files in one user-data directory."""
    try:
        return sorted(p for p in folder.glob("kira_persona_memory*.json") if p.is_file())
    except OSError:
        return []


def has_user_data(folder: Path) -> bool:
    return (any((folder / n).is_file() for n in (SETTINGS_NAME, DB_NAME, EVIDENCE_DB_NAME, CLOUD_VOICE_NAME))
            or bool(persona_memory_files(folder))
            or any((folder / name).is_dir() for name in ("huggingface", "voice_cache", "cache")))


def legacy_candidates(root: Path):
    """Find the previous per-user folder, this program's ./data, and sibling Kira ./data folders."""
    found = []
    # Previous releases stored user data and model caches under %LOCALAPPDATA%\\Kira.
    local = os.environ.get("LOCALAPPDATA")
    previous_user_dir = Path(local) / "Kira" if local else None
    if previous_user_dir and has_user_data(previous_user_dir):
        found.append(previous_user_dir)
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
    """Copy settings, chat history and caches from old data folders. COPY ONLY, never overwrites.

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
        copy_dirs = ("huggingface", "voice_cache", "cache")
        dirs_to_copy = [name for name in copy_dirs if (source_path / name).is_dir()]
        if not missing and not dirs_to_copy:
            continue
        copied = []
        for name in missing:
            src = Path(source) / name
            if src.is_file():
                shutil.copy2(src, new_dir / name)
                copied.append(name)
        for dirname in dirs_to_copy:
            source_dir = source_path / dirname
            for src in source_dir.rglob("*"):
                if not src.is_file():
                    continue
                relative = src.relative_to(source_dir)
                dst = new_dir / dirname / relative
                if not dst.exists():
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dst)
                    copied.append(f"{dirname}/{relative}")
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
