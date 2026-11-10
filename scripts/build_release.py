from __future__ import annotations

import ast
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import zipfile

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"

SKIP_DIRS = {
    ".git", ".venv", "venv", "__pycache__", ".pytest_cache", ".mypy_cache",
    ".ruff_cache", ".tox", "node_modules", "logs", "data", "dist", "build",
    ".idea", ".vscode",
}
SKIP_SUFFIXES = {
    ".pyc", ".pyo", ".log", ".db", ".sqlite", ".sqlite3",
    ".key", ".pem", ".p12", ".pfx", ".zip", ".7z", ".rar",
}
SKIP_NAMES = {
    ".env", "secrets.json", "api_keys.json", "settings.json",
    "settings.local.json", "user_settings.json", "config.local.json",
    "kira_memory.sqlite3", "kira_evidence.sqlite3",
}


def release_stamp(now: datetime | None = None) -> str:
    """Return the user's established ZIP timestamp format in Iran local time."""
    if now is None:
        now = datetime.now(ZoneInfo("Asia/Tehran"))
    elif now.tzinfo is None:
        now = now.replace(tzinfo=ZoneInfo("Asia/Tehran"))
    else:
        now = now.astimezone(ZoneInfo("Asia/Tehran"))
    return now.strftime("%y%m%d_%H%M")


def should_skip(path: Path) -> bool:
    path = Path(path)
    if any(part.lower() in SKIP_DIRS for part in path.parts):
        return True
    name = path.name.lower()
    if name in SKIP_NAMES:
        return True
    if name.startswith(".env.") and name != ".env.example":
        return True
    return path.suffix.lower() in SKIP_SUFFIXES


def source_files():
    """Walk the checkout without following symlinks or entering local/runtime folders."""
    for current, dirs, files in os.walk(ROOT, topdown=True, followlinks=False):
        current_path = Path(current)
        rel_dir = current_path.relative_to(ROOT)
        dirs[:] = sorted(
            d for d in dirs
            if not should_skip(rel_dir / d) and not (current_path / d).is_symlink()
        )
        for filename in sorted(files):
            path = current_path / filename
            relative = path.relative_to(ROOT)
            if should_skip(relative) or path.is_symlink() or not path.is_file():
                continue
            yield path, relative


def _write_github_output(values: dict[str, str]) -> None:
    target = os.environ.get("GITHUB_OUTPUT")
    if not target:
        return
    with open(target, "a", encoding="utf-8", newline="\n") as fh:
        for key, value in values.items():
            fh.write(f"{key}={value}\n")


def main() -> Path:
    stamp = release_stamp()
    archive = DIST / f"ProjectKira_{stamp}.zip"
    DIST.mkdir(parents=True, exist_ok=True)
    if archive.exists():
        archive.unlink()

    included = 0
    syntax_checked = 0
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=7) as result:
        for path, relative in source_files():
            if path.suffix.lower() == ".py":
                try:
                    ast.parse(path.read_text(encoding="utf-8"), filename=relative.as_posix())
                except (OSError, UnicodeDecodeError, SyntaxError) as exc:
                    raise RuntimeError(f"Python source check failed for {relative}: {exc}") from exc
                syntax_checked += 1
            result.write(path, arcname=relative.as_posix())
            included += 1

    size = archive.stat().st_size
    print(f"Release timestamp (Asia/Tehran): {stamp}")
    print(f"Python files syntax-checked: {syntax_checked}")
    print(f"Files included: {included}")
    print(f"Release ZIP: {archive.relative_to(ROOT).as_posix()}")
    print(f"ZIP size: {size:,} bytes")
    _write_github_output({
        "stamp": stamp,
        "asset": archive.relative_to(ROOT).as_posix(),
    })
    return archive


if __name__ == "__main__":
    main()
