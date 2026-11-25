"""Generate deterministic, hash-locked dependency groups for Windows Python 3.11/3.12.

Core is resolved first and is the only mandatory lock set. Optional groups are
resolved against the exact core lock; an optional resolution failure is reported
without blocking a usable core installation.

Run from the repository root:
    py -3.12 -m pip install --upgrade uv
    py -3.12 scripts/generate_dependency_locks.py
"""
from __future__ import annotations

import argparse
import hashlib
import json
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
DEFAULT_SNAPSHOT_CUTOFF = "2026-11-25T00:00:00Z"
LOCK_ROOT = ROOT / "dependency-locks" / "windows-x86_64"


@dataclass(frozen=True)
class DependencyGroup:
    name: str
    requirements: str
    constraints: tuple[str, ...] = ()
    no_deps: bool = False
    required: bool = False


GROUPS = (
    DependencyGroup("core", "requirements.txt", ("constraints.txt",), required=True),
    DependencyGroup("system-optional", "requirements-system-optional.txt", ("constraints.txt",)),
    DependencyGroup("ocr", "requirements-ocr.txt", ("constraints.txt",)),
    DependencyGroup("audio", "requirements-audio.txt", ("constraints.txt",)),
    DependencyGroup("dev", "requirements-dev.txt"),
    DependencyGroup("voice-local", "requirements-voice-local.txt", ("constraints.txt", "constraints-voice.txt")),
    DependencyGroup("voice-kitten", "requirements-voice-kitten.txt", ("constraints.txt", "constraints-voice.txt")),
    # Kira deliberately installs kittenml with --no-deps to avoid its PyTorch extras.
    DependencyGroup("voice-kitten-engine", "requirements-voice-kitten-engine.txt", ("constraints.txt",), no_deps=True),
)


class LockGenerationError(RuntimeError):
    """Raised when resolver output is missing, incomplete, or inconsistent."""


_PACKAGE_PIN = re.compile(r"^([A-Za-z0-9][A-Za-z0-9_.-]*)==([^\s\\]+)")
_HASH = re.compile(r"--hash=sha256:[0-9a-fA-F]{64}")


def _normalized_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _lock_stanzas(content: str) -> list[tuple[str, str, str]]:
    """Return normalized package pins and their complete stanza text."""
    lines = content.splitlines()
    starts: list[tuple[int, str, str]] = []
    for index, line in enumerate(lines):
        match = _PACKAGE_PIN.match(line.strip())
        if match:
            starts.append((index, _normalized_name(match.group(1)), match.group(2)))
    stanzas = []
    for position, (start, name, version) in enumerate(starts):
        end = starts[position + 1][0] if position + 1 < len(starts) else len(lines)
        stanzas.append((name, version, "\n".join(lines[start:end])))
    return stanzas


def _validate_lock(path: Path) -> None:
    """Reject empty, unpinned, duplicate/conflicting, or incompletely hashed output."""
    if not path.is_file():
        raise LockGenerationError(f"Resolver did not create {path.name}.")
    content = path.read_text(encoding="utf-8")
    if not content.strip():
        raise LockGenerationError(f"Resolver created an empty lock: {path.name}.")
    stanzas = _lock_stanzas(content)
    if not stanzas:
        raise LockGenerationError(f"Lock has no exact package pins: {path.name}.")
    seen: dict[str, str] = {}
    for name, version, stanza in stanzas:
        previous = seen.get(name)
        if previous is not None:
            reason = "conflicting" if previous != version else "duplicate"
            raise LockGenerationError(f"Lock contains a {reason} pin for {name}: {previous} and {version}.")
        seen[name] = version
        if not _HASH.search(stanza):
            raise LockGenerationError(f"Lock package {name}=={version} has no SHA-256 hash: {path.name}.")


def build_compile_command(
    uv_executable: str,
    root: Path,
    group: DependencyGroup,
    python_version: str,
    python_platform: str,
    output_file: Path,
    *,
    extra_constraints: Sequence[Path] = (),
    snapshot_cutoff: str = DEFAULT_SNAPSHOT_CUTOFF,
) -> list[str]:
    """Build a stable resolver invocation independent of machine-local uv config."""
    command = [
        uv_executable, "pip", "compile", str(root / group.requirements),
        "--python-version", python_version,
        "--python-platform", python_platform,
        "--resolution", "highest",
        "--exclude-newer", snapshot_cutoff,
        "--generate-hashes",
        "--no-header",
        "--no-annotate",
        "--no-emit-index-url",
        "--no-emit-find-links",
        "--no-sources",
        "--no-config",
        "--output-file", str(output_file),
    ]
    constraints = [root / item for item in group.constraints]
    constraints.extend(Path(item) for item in extra_constraints)
    for constraint in constraints:
        command.extend(("--constraint", str(constraint)))
    if group.no_deps:
        command.append("--no-deps")
    return command


def _parse_versions(raw: str) -> tuple[str, ...]:
    versions = tuple(item.strip() for item in raw.split(",") if item.strip())
    if not versions or any(version not in DEFAULT_PYTHON_VERSIONS for version in versions):
        raise argparse.ArgumentTypeError("Python versions must be selected from 3.11 and 3.12.")
    if len(set(versions)) != len(versions):
        raise argparse.ArgumentTypeError("Python versions must not be repeated.")
    return versions


def _group_inputs(root: Path, group: DependencyGroup) -> list[str]:
    return [name for name in (group.requirements, *group.constraints) if not (root / name).is_file()]


def _input_fingerprint(root: Path, python_versions: Sequence[str], python_platform: str, snapshot_cutoff: str, index_url: str | None = None) -> str:
    """Fingerprint all resolver inputs and generator semantics for lock reuse."""
    digest = hashlib.sha256()
    digest.update(Path(__file__).read_bytes())
    digest.update(json.dumps({
        "python_versions": list(python_versions),
        "python_platform": python_platform,
        "snapshot_cutoff": snapshot_cutoff,
        "index_identity": hashlib.sha256((index_url or "https://pypi.org/simple").encode("utf-8")).hexdigest(),
    }, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    for group in GROUPS:
        for name in (group.requirements, *group.constraints):
            path = root / name
            digest.update(name.encode("utf-8"))
            digest.update(path.read_bytes() if path.is_file() else b"<missing>")
    return digest.hexdigest()


def _reusable_locks(output_dir: Path, fingerprint: str, python_versions: Sequence[str]) -> bool:
    """Reuse generated locks only when every input and every existing lock validates."""
    try:
        manifest = json.loads((output_dir / "lock-manifest.json").read_text(encoding="utf-8"))
        if manifest.get("schema") != 1 or manifest.get("fingerprint") != fingerprint:
            return False
        for version in python_versions:
            core_lock = output_dir / ("python" + version.replace(".", "")) / "core.txt"
            _validate_lock(core_lock)
        for version in python_versions:
            version_dir = output_dir / ("python" + version.replace(".", ""))
            core_lock = version_dir / "core.txt"
            expected_constraints = "".join(
                f"{name}=={version_pin}\n"
                for name, version_pin, _stanza in _lock_stanzas(core_lock.read_text(encoding="utf-8"))
            )
            if (version_dir / "core-constraints.txt").read_text(encoding="utf-8") != expected_constraints:
                return False
        for lock_file in output_dir.glob("python*/*.txt"):
            if lock_file.name != "core-constraints.txt":
                _validate_lock(lock_file)
        return True
    except (OSError, ValueError, LockGenerationError):
        return False


def _write_core_constraints(core_lock: Path, output_file: Path) -> None:
    """Convert a hash lock to a plain pin-only constraints file for uv's resolver."""
    stanzas = _lock_stanzas(core_lock.read_text(encoding="utf-8"))
    if not stanzas:
        raise LockGenerationError(f"Core lock has no package pins: {core_lock.name}.")
    output_file.write_text(
        "".join(f"{name}=={version}\n" for name, version, _stanza in stanzas),
        encoding="utf-8",
    )


def _compile_group(
    *,
    runner: Callable,
    uv_executable: str,
    root: Path,
    group: DependencyGroup,
    version: str,
    python_platform: str,
    output_file: Path,
    core_lock: Path | None,
    env: dict[str, str],
    snapshot_cutoff: str,
) -> tuple[bool, int]:
    output_file.parent.mkdir(parents=True, exist_ok=True)
    shared_constraints = (core_lock,) if core_lock is not None and group.name != "core" else ()
    command = build_compile_command(
        uv_executable, root, group, version, python_platform, output_file,
        extra_constraints=shared_constraints, snapshot_cutoff=snapshot_cutoff,
    )
    result = runner(command, cwd=root, env=env, check=False)
    return_code = int(getattr(result, "returncode", 1))
    if return_code:
        return False, return_code
    _validate_lock(output_file)
    return True, 0


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
    refresh: bool = False,
    snapshot_cutoff: str = DEFAULT_SNAPSHOT_CUTOFF,
) -> int:
    """Stage all locks; require core, tolerate isolated optional resolver failures."""
    root = Path(root).resolve()
    output_dir = Path(output_dir).resolve()
    uv_executable = uv_executable or shutil.which("uv")
    if not uv_executable:
        out("ERROR: uv was not found. Install it with: py -3.12 -m pip install uv")
        return 2

    core = next(group for group in GROUPS if group.required)
    missing_core = _group_inputs(root, core)
    if missing_core:
        out("ERROR: missing core dependency inputs: " + ", ".join(missing_core))
        return 2

    output_dir.parent.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    # Ignore ambient uv configuration and index variables. One explicit index defines
    # the resolver source; credentials and index URLs are never emitted into lock files.
    ignored_resolver_environment = {
        "PIP_INDEX_URL", "PIP_EXTRA_INDEX_URL", "PIP_FIND_LINKS",
        "PIP_NO_INDEX", "PIP_CONSTRAINT", "PIP_REQUIREMENT",
    }
    for key in tuple(env):
        if key.startswith("UV_") or key in ignored_resolver_environment:
            env.pop(key, None)
    env["UV_CUSTOM_COMPILE_COMMAND"] = "python scripts/generate_dependency_locks.py"
    env["UV_NO_PROGRESS"] = "1"
    selected_index = index_url or os.environ.get("KIRA_PYPI_INDEX")
    if selected_index:
        env["UV_DEFAULT_INDEX"] = selected_index

    fingerprint = _input_fingerprint(root, python_versions, python_platform, snapshot_cutoff, selected_index)
    if not refresh and _reusable_locks(output_dir, fingerprint, python_versions):
        out("Dependency locks are current; reusing the existing hash-locked environment.")
        return 0

    generated: list[Path] = []
    optional_failures: list[str] = []
    try:
        with tempfile.TemporaryDirectory(prefix=".kira-lock-stage-", dir=output_dir.parent) as staging_name:
            staging = Path(staging_name)
            staged_output = staging / output_dir.name

            # Core must resolve for every supported interpreter before optional work.
            for version in python_versions:
                version_name = "python" + version.replace(".", "")
                target = staged_output / version_name / "core.txt"
                try:
                    ok, code = _compile_group(
                        runner=runner, uv_executable=uv_executable, root=root,
                        group=core, version=version, python_platform=python_platform,
                        output_file=target, core_lock=None, env=env,
                        snapshot_cutoff=snapshot_cutoff,
                    )
                except (OSError, LockGenerationError) as exc:
                    out(f"ERROR: core lock validation failed for Python {version}: {exc}")
                    return 2
                if not ok:
                    out(f"ERROR: core dependencies could not be resolved for Python {version}; previous locks were preserved.")
                    return code or 2
                generated.append(target)

            # Every optional group is constrained by the exact core resolution. An
            # optional resolver failure omits only that feature's lock, never core.
            for version in python_versions:
                version_name = "python" + version.replace(".", "")
                core_lock = staged_output / version_name / "core.txt"
                core_constraints = staged_output / version_name / "core-constraints.txt"
                try:
                    _write_core_constraints(core_lock, core_constraints)
                except (OSError, LockGenerationError) as exc:
                    out(f"ERROR: could not derive Core constraints for Python {version}: {exc}")
                    return 2
                for group in (item for item in GROUPS if not item.required):
                    missing = _group_inputs(root, group)
                    if missing:
                        optional_failures.append(f"{group.name} (missing {', '.join(missing)})")
                        continue
                    target = staged_output / version_name / f"{group.name}.txt"
                    try:
                        ok, code = _compile_group(
                            runner=runner, uv_executable=uv_executable, root=root,
                            group=group, version=version, python_platform=python_platform,
                            output_file=target, core_lock=core_constraints, env=env,
                            snapshot_cutoff=snapshot_cutoff,
                        )
                    except (OSError, LockGenerationError) as exc:
                        target.unlink(missing_ok=True)
                        optional_failures.append(f"{group.name} for Python {version} ({exc})")
                        continue
                    if not ok:
                        target.unlink(missing_ok=True)
                        optional_failures.append(f"{group.name} for Python {version} (resolver exit {code})")
                        continue
                    generated.append(target)

            (staged_output / "lock-manifest.json").write_text(
                json.dumps({"schema": 1, "fingerprint": fingerprint}, sort_keys=True, indent=2) + "\n",
                encoding="utf-8",
            )

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
    except OSError as exc:
        out(f"ERROR: lock generation was not published: {exc}")
        return 2

    out(f"Generated {len(generated)} hash-locked files; core is complete for {len(python_versions)} Python targets.")
    if optional_failures:
        out("WARNING: optional dependency locks were not generated: " + "; ".join(optional_failures))
        out("Core installation remains available; affected optional features will be resolved separately and may be skipped.")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python-versions", type=_parse_versions, default=DEFAULT_PYTHON_VERSIONS,
                        help="comma-separated supported targets (default: 3.11,3.12)")
    parser.add_argument("--python-platform", default=DEFAULT_PLATFORM,
                        help=f"uv target platform (default: {DEFAULT_PLATFORM})")
    parser.add_argument("--index-url", default=os.environ.get("KIRA_PYPI_INDEX"))
    parser.add_argument("--uv", dest="uv_executable", help="path to the uv executable")
    parser.add_argument("--output-dir", type=Path, default=LOCK_ROOT)
    parser.add_argument("--refresh", action="store_true",
                        help="explicitly re-resolve every group; normal setup reuses matching locks")
    parser.add_argument("--snapshot-cutoff", default=DEFAULT_SNAPSHOT_CUTOFF,
                        help="package publication cutoff (advance only for intentional dependency upgrades)")
    args = parser.parse_args(argv)
    return generate_locks(
        output_dir=args.output_dir, uv_executable=args.uv_executable,
        python_versions=args.python_versions, python_platform=args.python_platform,
        index_url=args.index_url, refresh=args.refresh,
        snapshot_cutoff=args.snapshot_cutoff,
    )


if __name__ == "__main__":
    raise SystemExit(main())
