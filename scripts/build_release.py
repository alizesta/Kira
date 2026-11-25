from __future__ import annotations

import ast
import json
import os
import re
import stat
from datetime import datetime
from pathlib import Path, PurePosixPath
from zoneinfo import ZoneInfo
import zipfile

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"

if __package__:
    from . import build_metadata, release_manifest
else:  # Executed as `python scripts/build_release.py`.
    import build_metadata  # type: ignore
    import release_manifest  # type: ignore

SKIP_DIRS = {
    ".git", ".venv", "venv", "__pycache__", ".pytest_cache", ".mypy_cache",
    ".ruff_cache", ".tox", "node_modules", "logs", "data", "dist", "build",
    ".idea", ".vscode", ".uvboot",
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

# High-confidence credential formats commonly used by the providers supported
# by Kira. Patterns run against the exact bytes being written to the archive.
_SECRET_PATTERNS = (
    ("google_api_key", re.compile(rb"\bAIza[0-9A-Za-z_-]{30,}\b")),
    ("groq_api_key", re.compile(rb"\bgsk_[A-Za-z0-9]{20,}\b")),
    ("openrouter_api_key", re.compile(rb"\bsk-or-v1-[A-Za-z0-9]{20,}\b")),
    ("openai_api_key", re.compile(rb"\bsk-[A-Za-z0-9]{32,}\b")),
    ("github_pat", re.compile(rb"\bgithub_pat_[A-Za-z0-9_]{30,}\b")),
    ("github_token", re.compile(rb"\bgh[pousr]_[A-Za-z0-9]{30,}\b")),
    ("aws_access_key_id", re.compile(rb"\bAKIA[0-9A-Z]{16}\b")),
    ("slack_token", re.compile(rb"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("bearer_token", re.compile(rb"\bBearer\s+[A-Za-z0-9._~+/-]{30,}=?", re.IGNORECASE)),
    ("private_key", re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----")),
)


class ReleaseSecurityError(RuntimeError):
    """A distributable file contains a credential-like value."""


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
    """Reject known local/user artifacts before the release allowlist is applied."""
    path = Path(path)
    if any(part.lower() in SKIP_DIRS for part in path.parts):
        return True
    name = path.name.lower()
    if name in SKIP_NAMES:
        return True
    if name.startswith(".env.") and name != ".env.example":
        return True
    return path.suffix.lower() in SKIP_SUFFIXES


def source_files(root: Path = ROOT):
    """Yield only allowlisted runtime files; arbitrary checkout additions stay out."""
    root = Path(root).resolve()
    for current, dirs, files in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        rel_dir = current_path.relative_to(root)
        dirs[:] = sorted(
            directory
            for directory in dirs
            if not (current_path / directory).is_symlink()
            and not should_skip(rel_dir / directory)
            and release_manifest.is_release_directory((rel_dir / directory).as_posix())
        )
        for filename in sorted(files):
            path = current_path / filename
            relative = path.relative_to(root)
            if path.is_symlink() or not path.is_file() or should_skip(relative):
                continue
            if release_manifest.is_release_path_allowed(relative.as_posix()):
                yield path, relative


def release_file_bytes(path: Path, relative: Path) -> bytes:
    """Return deterministic release bytes; Windows batch scripts always use CRLF."""
    data = Path(path).read_bytes()
    if Path(relative).suffix.lower() == ".bat":
        data = data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
        data = data.replace(b"\n", b"\r\n")
    return data


def scan_release_content(relative: str | PurePosixPath, content: bytes) -> tuple[str, ...]:
    """Return credential pattern identifiers found in one distributable file."""
    return tuple(name for name, pattern in _SECRET_PATTERNS if pattern.search(content))


def _validate_release_inputs(root: Path, files: list[tuple[Path, Path]]) -> int:
    included = {relative.as_posix() for _, relative in files}
    missing_required = sorted(release_manifest.REQUIRED_RELEASE_FILES - included)
    if missing_required:
        raise RuntimeError("Release package is missing required runtime files: " + ", ".join(missing_required))

    missing_allowlist = sorted(release_manifest.ALLOWED_FILES - included)
    if missing_allowlist:
        raise RuntimeError(
            "Release allowlist references files missing from this checkout: " + ", ".join(missing_allowlist)
        )

    dependency_count = 0
    for relative in release_manifest.RUNTIME_DEPENDENCY_FILES:
        path = root / relative
        if not path.is_file():
            raise RuntimeError(f"Runtime dependency declaration is missing: {relative}")
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError) as exc:
            raise RuntimeError(f"Runtime dependency declaration cannot be read: {relative}: {exc}") from exc
        entries = [line.strip() for line in lines if line.strip() and not line.lstrip().startswith("#")]
        if not entries:
            raise RuntimeError(f"Runtime dependency declaration is empty: {relative}")
        dependency_count += len(entries)
        if relative not in included:
            raise RuntimeError(f"Runtime dependency declaration is not packaged: {relative}")
    return dependency_count


def _scan_release_files(files: list[tuple[Path, Path]]) -> None:
    findings = []
    for path, relative in files:
        content = path.read_bytes()
        matches = scan_release_content(relative.as_posix(), content)
        if matches:
            findings.append((relative.as_posix(), matches))
    if findings:
        details = "; ".join(f"{name}: {', '.join(patterns)}" for name, patterns in findings)
        raise ReleaseSecurityError("Release stopped: credential-like content detected in allowlisted files: " + details)


def _manifest_payload(files: list[tuple[Path, Path]]) -> bytes:
    payload = {
        "format": release_manifest.PACKAGE_FORMAT,
        "manifest_version": 1,
        "files": sorted(relative.as_posix() for _, relative in files),
        "runtime_dependencies": list(release_manifest.RUNTIME_DEPENDENCY_FILES),
        "runtime_setup": sorted(release_manifest.RUNTIME_SCRIPT_FILES),
    }
    return (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def validate_archive(archive: Path, expected_files: set[str]) -> None:
    """Validate ZIP integrity, safe paths, exact allowlist membership and manifest."""
    try:
        with zipfile.ZipFile(archive, "r") as package:
            names = package.namelist()
            if len(names) != len(set(names)):
                raise RuntimeError("Release ZIP contains duplicate paths")
            expected = set(expected_files) | {release_manifest.PACKAGE_MANIFEST_NAME}
            if set(names) != expected:
                missing = sorted(expected - set(names))
                unexpected = sorted(set(names) - expected)
                raise RuntimeError(
                    "Release ZIP contents differ from the allowlist; "
                    f"missing={missing}, unexpected={unexpected}"
                )
            for info in package.infolist():
                path = PurePosixPath(info.filename)
                if path.is_absolute() or ".." in path.parts or "\\" in info.filename or path.as_posix() != info.filename:
                    raise RuntimeError(f"Release ZIP contains an unsafe path: {info.filename}")
                unix_mode = (info.external_attr >> 16) & 0xFFFF
                if stat.S_ISLNK(unix_mode):
                    raise RuntimeError(f"Release ZIP contains a symbolic link: {info.filename}")
                data = package.read(info.filename)
                findings = scan_release_content(info.filename, data)
                if findings:
                    raise ReleaseSecurityError(
                        f"Release stopped: credential-like content detected in {info.filename}: {', '.join(findings)}"
                    )
            bad_member = package.testzip()
            if bad_member is not None:
                raise RuntimeError(f"Release ZIP CRC validation failed for {bad_member}")
            try:
                manifest = json.loads(package.read(release_manifest.PACKAGE_MANIFEST_NAME))
            except (KeyError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise RuntimeError(f"Release ZIP manifest is unreadable: {exc}") from exc
            if not isinstance(manifest, dict):
                raise RuntimeError("Release ZIP manifest must be a JSON object")
            if manifest.get("format") != release_manifest.PACKAGE_FORMAT or manifest.get("manifest_version") != 1:
                raise RuntimeError("Release ZIP manifest has an unsupported package format or version")
            manifest_files = manifest.get("files")
            if (not isinstance(manifest_files, list) or not all(isinstance(item, str) for item in manifest_files)
                    or len(manifest_files) != len(set(manifest_files)) or set(manifest_files) != expected_files):
                raise RuntimeError("Release ZIP manifest does not match its actual payload")
            if manifest.get("runtime_dependencies") != list(release_manifest.RUNTIME_DEPENDENCY_FILES):
                raise RuntimeError("Release ZIP manifest has an incorrect runtime dependency declaration")
            if manifest.get("runtime_setup") != sorted(release_manifest.RUNTIME_SCRIPT_FILES):
                raise RuntimeError("Release ZIP manifest has an incorrect runtime setup script declaration")
    except zipfile.BadZipFile as exc:
        raise RuntimeError(f"Release ZIP is invalid: {exc}") from exc


def _write_github_output(values: dict[str, str]) -> None:
    target = os.environ.get("GITHUB_OUTPUT")
    if not target:
        return
    with open(target, "a", encoding="utf-8", newline="\n") as fh:
        for key, value in values.items():
            fh.write(f"{key}={value}\n")


def main() -> Path:
    # Mandatory gate: refresh the build stamp from the environment and stop when version metadata,
    # build date/time, developer or the CHANGELOG entry is missing or invalid.
    try:
        metadata = build_metadata.ensure_release_metadata()
    except build_metadata.MetadataError as exc:
        raise SystemExit(f"Release stopped: {exc}") from None

    files = list(source_files(ROOT))
    dependency_count = _validate_release_inputs(ROOT, files)
    _scan_release_files(files)

    stamp = release_stamp()
    archive = DIST / f"ProjectKira_{stamp}.zip"
    DIST.mkdir(parents=True, exist_ok=True)
    temporary_archive = DIST / f".{archive.stem}.tmp.zip"
    if temporary_archive.exists():
        temporary_archive.unlink()

    included = 0
    syntax_checked = 0
    expected_files = {relative.as_posix() for _, relative in files}
    manifest_bytes = _manifest_payload(files)
    try:
        with zipfile.ZipFile(temporary_archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=7) as result:
            for path, relative in files:
                data = release_file_bytes(path, relative)
                if path.suffix.lower() == ".py":
                    try:
                        ast.parse(data.decode("utf-8"), filename=relative.as_posix())
                    except (UnicodeDecodeError, SyntaxError) as exc:
                        raise RuntimeError(f"Python source check failed for {relative}: {exc}") from exc
                    syntax_checked += 1
                result.writestr(relative.as_posix(), data)
                included += 1
            result.writestr(release_manifest.PACKAGE_MANIFEST_NAME, manifest_bytes)

        validate_archive(temporary_archive, expected_files)
        os.replace(temporary_archive, archive)
    except Exception:
        temporary_archive.unlink(missing_ok=True)
        raise

    size = archive.stat().st_size
    print(f"Version metadata: {metadata['version']} | build {metadata['build_date']} {metadata['build_time']} | developer {metadata['developer']}")
    print(f"Release timestamp (Asia/Tehran): {stamp}")
    print(f"Python files syntax-checked: {syntax_checked}")
    print(f"Runtime dependency declarations: {len(release_manifest.RUNTIME_DEPENDENCY_FILES)} files / {dependency_count} entries")
    print(f"Files included by allowlist: {included}")
    print(f"Release ZIP: {archive.relative_to(ROOT).as_posix() if archive.is_relative_to(ROOT) else archive}")
    print(f"ZIP size: {size:,} bytes")
    _write_github_output({
        "stamp": stamp,
        "asset": archive.relative_to(ROOT).as_posix() if archive.is_relative_to(ROOT) else str(archive),
    })
    return archive


if __name__ == "__main__":
    main()
