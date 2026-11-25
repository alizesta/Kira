"""Generate hash-locked Windows dependency groups for Python 3.11 and 3.12.

Run from the repository root with:
    py -3.12 -m pip install --upgrade uv
    py -3.12 scripts/generate_dependency_locks.py

Set --index-url (or KIRA_PYPI_INDEX) to use an accessible package mirror.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PYTHON_VERSIONS = ("3.11", "3.12")
DEFAULT_PLATFORM = "x86_64-pc-windows-msvc"
LOCK_ROOT = ROOT / "dependency-locks" / "windows-x86_64"


@dataclass(frozen=True)
class DependencyGroup:
    name: str
    requirements: str
    constraints: tuple[str, ...] = ()
    no_deps: bool = False


GROUPS = (
    DependencyGroup("core", "requirements.txt", ("constraints.txt",)),
    DependencyGroup("system-optional", "requirements-system-optional.txt", ("constraints.txt",)),
    DependencyGroup("ocr", "requirements-ocr.txt", ("constraints.txt",)),
    DependencyGroup("audio", "requirements-audio.txt", ("constraints.txt",)),
    DependencyGroup("dev", "requirements-dev.txt"),
    DependencyGroup(
        "voice-local",
        "requirements-voice-local.txt",
        ("constraints.txt", "constraints-voice.txt"),
    ),
    DependencyGroup(
        "voice-kitten",
        "requirements-voice-kitten.txt",
        ("constraints.txt", "constraints-voice.txt"),
    ),
    # Kira deliberately installs kittenml with --no-deps to avoid its PyTorch extras.
    DependencyGroup(
        "voice-kitten-engine",
        "requirements-voice-kitten-engine.txt",
        ("constraints.txt",),
        no_deps=True,
    ),
)


class LockGenerationError(RuntimeError):
    """Raised when a generated lock is missing or incomplete."""


def build_compile_command(
    uv_executable: str,
    root: Path,
    group: DependencyGroup,
    python_version: str,
    python_platform: str,
    output_file: Path,
) -> list[str]:
    """Build a deterministic uv command for one OS/Python/group target."""
    command = [
        uv_executable,
        "pip",
        "compile",
        str(root / group.requirements),
        "--python-version",
        python_version,
        "--python-platform",
        python_platform,
        "--generate-hashes",
        "--output-file",
        str(output_file),
    ]
    for constraint in group.constraints:
        command.extend(("--constraint", str(root / constraint)))
    if group.no_deps:
        command.append("--no-deps")
    return command


def _validate_lock(path: Path) -> None:
    """Reject empty, unpinned, or hashless resolver output."""
    if not path.is_file():
        raise LockGenerationError(f"Resolver did not create {path.name}.")
    content = path.read_text(encoding="utf-8")
    if not content.strip():
        raise LockGenerationError(f"Resolver created an empty lock: {path.name}.")
    package_pins = re.findall(r"(?m)^[A-Za-z0-9][A-Za-z0-9_.-]*==[^\s\\]+", content)
    if not package_pins:
        raise LockGenerationError(f"Lock has no exact package pins: {path.name}.")
    if "--hash=sha256:" not in content:
        raise LockGenerationError(f"Lock has no SHA-256 hashes: {path.name}.")


def _parse_versions(raw: str) -> tuple[str, ...]:
    versions = tuple(item.strip() for item in raw.split(",") if item.strip())
    if not versions or any(version not in DEFAULT_PYTHON_VERSIONS for version in versions):
        raise argparse.ArgumentTypeError("Python versions must be selected from 3.11 and 3.12.")
    if len(set(versions)) != len(versions):
        raise argparse.ArgumentTypeError("Python versions must not be repeated.")
    return versions


def generate_locks(
    *,
    root: Path = ROOT,
    output_dir: Path = LOCK_ROOT,
    uv_executable: str | None = None,
    python_versions: Sequence[str] = DEFAULT_PYTHON_VERSIONS,
    python_platform: str = DEFAULT_PLATFORM,
    index_url: str | None = None,
    runner: Callable = subprocess.run,
    out: Callable[[str], None] = print,
) -> int:
    """Generate every lock in a staging directory; publish only after all resolve."""
    root = Path(root).resolve()
    output_dir = Path(output_dir).resolve()
    uv_executable = uv_executable or shutil.which("uv")
    if not uv_executable:
        out("ERROR: uv was not found. Install it with: py -3.12 -m pip install uv")
        return 2

    missing = [
        name
        for group in GROUPS
        for name in (group.requirements, *group.constraints)
        if not (root / name).is_file()
    ]
    if missing:
        out("ERROR: missing dependency inputs: " + ", ".join(sorted(set(missing))))
        return 2

    output_dir.parent.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["UV_CUSTOM_COMPILE_COMMAND"] = "python scripts/generate_dependency_locks.py"
    if index_url:
        # Use the environment to keep credentials out of the generated command header.
        env["UV_DEFAULT_INDEX"] = index_url

    try:
        with tempfile.TemporaryDirectory(
            prefix=".kira-lock-stage-", dir=output_dir.parent
        ) as staging_name:
            staging = Path(staging_name)
            staged_output = staging / output_dir.name
            staged_files: list[Path] = []
            total = len(GROUPS) * len(python_versions)
            completed = 0

            for version in python_versions:
                version_name = "python" + version.replace(".", "")
                for group in GROUPS:
                    staged_file = staged_output / version_name / f"{group.name}.txt"
                    staged_file.parent.mkdir(parents=True, exist_ok=True)
                    command = build_compile_command(
                        uv_executable,
                        root,
                        group,
                        version,
                        python_platform,
                        staged_file,
                    )
                    out(f"[{completed + 1}/{total}] Locking {group.name} for Python {version}...")
                    result = runner(command, cwd=root, env=env, check=False)
                    return_code = getattr(result, "returncode", 1)
                    if return_code:
                        out(
                            f"ERROR: uv could not resolve {group.name} for Python {version}; "
                            "existing lock files were left unchanged."
                        )
                        return int(return_code)
                    _validate_lock(staged_file)
                    staged_files.append(staged_file)
                    completed += 1

            # Swap the complete generated directory so a failed resolver or filesystem
            # operation cannot leave a mixture of old and new lock files.
            backup = staging / "previous-locks"
            had_previous = output_dir.exists()
            if had_previous:
                os.replace(output_dir, backup)
            try:
                os.replace(staged_output, output_dir)
            except OSError:
                if had_previous and backup.exists():
                    os.replace(backup, output_dir)
                raise
            if had_previous:
                shutil.rmtree(backup, ignore_errors=True)
    except (OSError, LockGenerationError) as exc:
        out(f"ERROR: lock generation was not published: {exc}")
        return 2

    out(f"Generated {len(staged_files)} hash-locked requirement files in {output_dir}.")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--python-versions",
        type=_parse_versions,
        default=DEFAULT_PYTHON_VERSIONS,
        help="comma-separated supported targets (default: 3.11,3.12)",
    )
    parser.add_argument(
        "--python-platform",
        default=DEFAULT_PLATFORM,
        help=f"uv target platform (default: {DEFAULT_PLATFORM})",
    )
    parser.add_argument("--index-url", default=os.environ.get("KIRA_PYPI_INDEX"))
    parser.add_argument("--uv", dest="uv_executable", help="path to the uv executable")
    parser.add_argument("--output-dir", type=Path, default=LOCK_ROOT)
    args = parser.parse_args(argv)
    return generate_locks(
        output_dir=args.output_dir,
        uv_executable=args.uv_executable,
        python_versions=args.python_versions,
        python_platform=args.python_platform,
        index_url=args.index_url,
    )


if __name__ == "__main__":
    raise SystemExit(main())
