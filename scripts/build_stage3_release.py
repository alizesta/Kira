from __future__ import annotations

import ast
import json
import os
from pathlib import Path
import tempfile
import zipfile

SOURCE_ARCHIVE = Path("ProjectKira_261111_0059.zip")
THEME_SOURCE = Path("kira/theme.py")
MOOD_SOURCE = Path("kira/mood.py")
EMOTIONS_SOURCE = Path("emotion_library/emotions.json")
OUTPUT_ARCHIVE = Path("dist/ProjectKira_Stage3_Neon_Glass.zip")

SKIP_DIRS = {
    ".git", ".venv", "venv", "__pycache__", ".pytest_cache",
    ".mypy_cache", ".ruff_cache", ".tox", "node_modules", "logs",
}
SKIP_SUFFIXES = {
    ".pyc", ".pyo", ".log", ".db", ".sqlite", ".sqlite3",
    ".key", ".pem", ".p12", ".pfx", ".zip", ".7z", ".rar",
}
SKIP_NAMES = {
    ".env", "secrets.json", "api_keys.json",
    "settings.local.json", "user_settings.json",
}


def safe_extract(source: Path, destination: Path) -> None:
    root = destination.resolve()
    with zipfile.ZipFile(source) as archive:
        for entry in archive.infolist():
            target = (destination / entry.filename).resolve()
            if target != root and root not in target.parents:
                raise RuntimeError(f"Unsafe path in Stage 3 archive: {entry.filename}")
        archive.extractall(destination)


def locate_kira_package(extracted: Path) -> tuple[Path, Path]:
    candidates = []
    for main_file in extracted.rglob("main.py"):
        if main_file.parent.name != "kira":
            continue
        try:
            source = main_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if "build_style" in source and ".theme" in source:
            candidates.append((main_file.parent, main_file))
    if len(candidates) != 1:
        found = [str(main.relative_to(extracted)) for _, main in candidates]
        raise RuntimeError(
            "Could not identify exactly one Stage 3 Kira UI package. "
            f"Matching main.py files: {found}"
        )
    return candidates[0]


def should_skip(path: Path) -> bool:
    if any(part in SKIP_DIRS for part in path.parts):
        return True
    lower = path.name.lower()
    if lower in SKIP_NAMES:
        return True
    if lower.startswith(".env.") and lower != ".env.example":
        return True
    if path.suffix.lower() in SKIP_SUFFIXES:
        return True
    return False


def main() -> None:
    if not SOURCE_ARCHIVE.is_file():
        raise FileNotFoundError(f"Missing Stage 3 source archive: {SOURCE_ARCHIVE}")
    for required in (THEME_SOURCE, MOOD_SOURCE, EMOTIONS_SOURCE):
        if not required.is_file():
            raise FileNotFoundError(f"Missing reviewed Kira source: {required}")

    OUTPUT_ARCHIVE.parent.mkdir(parents=True, exist_ok=True)
    excluded = 0
    included = 0

    with tempfile.TemporaryDirectory(prefix="kira-stage3-") as temp_dir:
        extracted = Path(temp_dir) / "payload"
        extracted.mkdir()
        safe_extract(SOURCE_ARCHIVE, extracted)

        kira_dir, main_file = locate_kira_package(extracted)
        theme_target = kira_dir / "theme.py"
        if not theme_target.is_file():
            raise RuntimeError("Stage 3 archive does not contain kira/theme.py")

        main_source = main_file.read_text(encoding="utf-8")
        if "build_style" not in main_source or ".theme" not in main_source:
            raise RuntimeError("Stage 3 UI no longer uses the expected theme interface")

        theme_text = THEME_SOURCE.read_text(encoding="utf-8")
        ast.parse(theme_text, filename="kira/theme.py")
        if "def build_style(" not in theme_text or "QFrame#chatCard" not in theme_text:
            raise RuntimeError("Neon glass theme contract check failed")

        # Apply the reviewed UI and emotional-state sources to the uploaded Stage 3 package.
        reviewed_sources = {
            "kira/theme.py": THEME_SOURCE,
            "kira/main.py": Path("kira/main.py"),
            "kira/chat_render.py": Path("kira/chat_render.py"),
            "kira/mood.py": MOOD_SOURCE,
            "kira/emotion/runtime.py": Path("kira/emotion/runtime.py"),
            "kira/emotion/director.py": Path("kira/emotion/director.py"),
            "emotion_library/emotions.json": EMOTIONS_SOURCE,
            "emotion_library/rules.json": Path("emotion_library/rules.json"),
            "emotion_library/events.json": Path("emotion_library/events.json"),
        }
        for relative, source_path in reviewed_sources.items():
            if not source_path.is_file():
                raise RuntimeError(f"Missing reviewed source: {relative}")
            rel_path = Path(relative)
            target = kira_dir.parent / rel_path
            target.parent.mkdir(parents=True, exist_ok=True)
            updated = source_path.read_text(encoding="utf-8")
            if relative.endswith(".py"):
                ast.parse(updated, filename=relative)
            target.write_text(updated, encoding="utf-8", newline="\n")

        main_text = (kira_dir / "main.py").read_text(encoding="utf-8")
        mood_text = (kira_dir / "mood.py").read_text(encoding="utf-8")
        if "def chat_actions_html(" not in main_text or "def apply_neon_glow(" not in main_text:
            raise RuntimeError("Neon action controls / glow effects were not applied")
        if "BEHAVIOR_REST" not in mood_text or "def _energy_at(" not in mood_text:
            raise RuntimeError("Legacy mood compatibility layer was not applied")
        runtime_target = kira_dir / "emotion" / "runtime.py"
        if not runtime_target.is_file() or "class EmotionalRuntime" not in runtime_target.read_text(encoding="utf-8"):
            raise RuntimeError("Persistent layered emotional runtime was not packaged")
        emotion_data = json.loads((kira_dir.parent / EMOTIONS_SOURCE).read_text(encoding="utf-8"))
        emotion_ids = {item.get("id") for item in emotion_data.get("emotions", [])}
        if not {"fearful", "disgusted"}.issubset(emotion_ids):
            raise RuntimeError("Primary emotion library is missing fearful/disgusted")

        # Parse the complete Python source tree without importing providers or starting services.
        for py_file in extracted.rglob("*.py"):
            if should_skip(py_file):
                continue
            try:
                ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
            except (SyntaxError, UnicodeDecodeError) as exc:
                raise RuntimeError(f"Python syntax check failed: {py_file}: {exc}") from exc

        if OUTPUT_ARCHIVE.exists():
            OUTPUT_ARCHIVE.unlink()
        with zipfile.ZipFile(
            OUTPUT_ARCHIVE, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=7
        ) as result:
            for path in extracted.rglob("*"):
                relative = path.relative_to(extracted)
                if should_skip(relative):
                    if path.is_file():
                        excluded += 1
                    continue
                if path.is_dir():
                    continue
                result.write(path, arcname=relative.as_posix())
                included += 1

    print(f"Stage 3 source: {SOURCE_ARCHIVE}")
    print("Applied visual theme update: kira/theme.py")
    print("Applied layered emotional runtime: emotions, behavior, energy, relationship and emotional memory")
    print(f"Python syntax checks: passed")
    print(f"Files included: {included}; runtime/sensitive files excluded: {excluded}")
    print(f"Release asset: {OUTPUT_ARCHIVE}")
    print(f"Asset size: {OUTPUT_ARCHIVE.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
