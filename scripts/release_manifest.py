"""Load and validate the exact file inventory for the Windows source release."""
from __future__ import annotations

import json
from pathlib import Path, PurePosixPath

PACKAGE_FORMAT = "kira-windows-source"
PACKAGE_MANIFEST_NAME = "release-manifest.json"
ALLOWLIST_PATH = Path(__file__).with_name("release-allowlist.json")

REQUIRED_RELEASE_FILES = frozenset(
    {
        "install.bat",
        "install_deps.py",
        "requirements.txt",
        "requirements-voice-local.txt",
        "constraints.txt",
        "constraints-voice.txt",
        "requirements-audio.txt",
        "requirements-ocr.txt",
        "requirements-system-optional.txt",
        "requirements-voice-kitten-engine.txt",
        "requirements-voice-kitten.txt",
        "start_kira.bat",
        "start_kira.vbs",
        "update_kira.bat",
        "scripts/setup_local_voice.py",
        "scripts/setup_local_chat_model.py",
        "kira/__init__.py",
        "kira/main.py",
        "kira/config.py",
        "kira/settings_schema.py",
        "kira/storage.py",
        "kira/build_info.py",
        "kira/ui/main_window_support.py",
        "reactions.json",
        "assets/kira_character.png",
        "assets/kira_icon.ico",
        "assets/kira_icon.png",
        "emotion_library/manifest.json",
    }
)


def _normalise_path(value: str | PurePosixPath) -> PurePosixPath | None:
    raw = str(value).replace("\\", "/")
    path = PurePosixPath(raw)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        return None
    if path.parts[0].endswith(":"):
        return None
    return path


def _load_allowlist() -> tuple[frozenset[str], tuple[str, ...], frozenset[str]]:
    try:
        document = json.loads(ALLOWLIST_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Release allowlist cannot be read: {ALLOWLIST_PATH}: {exc}") from exc
    if not isinstance(document, dict):
        raise RuntimeError("Release allowlist must be a JSON object")
    if document.get("package_format") != PACKAGE_FORMAT or document.get("manifest_version") != 1:
        raise RuntimeError("Release allowlist has an unsupported format or version")

    raw_files = document.get("files")
    if not isinstance(raw_files, list) or not raw_files:
        raise RuntimeError("Release allowlist must contain a non-empty files array")
    files = []
    for item in raw_files:
        path = _normalise_path(item) if isinstance(item, str) else None
        if path is None or path.as_posix() != item:
            raise RuntimeError(f"Release allowlist contains an unsafe or non-canonical path: {item!r}")
        files.append(item)
    if len(files) != len(set(files)):
        raise RuntimeError("Release allowlist contains duplicate file paths")

    dependencies = document.get("runtime_dependencies")
    setup_scripts = document.get("runtime_setup_scripts")
    if not isinstance(dependencies, list) or not dependencies or not all(isinstance(x, str) for x in dependencies):
        raise RuntimeError("Release allowlist must declare runtime dependency files")
    if not isinstance(setup_scripts, list) or not all(isinstance(x, str) for x in setup_scripts):
        raise RuntimeError("Release allowlist has an invalid runtime setup script list")
    missing = REQUIRED_RELEASE_FILES - set(files)
    if missing:
        raise RuntimeError("Release allowlist omits required runtime files: " + ", ".join(sorted(missing)))
    if not set(dependencies).issubset(files) or not set(setup_scripts).issubset(files):
        raise RuntimeError("Release allowlist metadata references files absent from its files array")
    return frozenset(files), tuple(dependencies), frozenset(setup_scripts)


ALLOWED_FILES, RUNTIME_DEPENDENCY_FILES, RUNTIME_SCRIPT_FILES = _load_allowlist()


def is_release_path_allowed(value: str | PurePosixPath) -> bool:
    """Return True only for an exact, explicitly reviewed file path."""
    path = _normalise_path(value)
    return path is not None and path.as_posix() in ALLOWED_FILES


def is_release_directory(value: str | PurePosixPath) -> bool:
    """Traverse only directories that contain at least one explicit allowlisted file."""
    path = _normalise_path(value)
    if path is None:
        return False
    name = path.as_posix()
    prefix = name + "/"
    return any(file_path.startswith(prefix) for file_path in ALLOWED_FILES)
