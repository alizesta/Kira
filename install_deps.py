"""Resolve and install one dependency group transactionally.

The resolver preflight is read-only. Before pip can mutate the active
environment, the installer's package and script directories are snapshotted.
Any install or post-install verification failure restores that snapshot.
"""
from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
import sysconfig
import tempfile
from pathlib import Path

PIP = [sys.executable, "-m", "pip"]
LOCK_GROUPS = {
    "requirements.txt": "core",
    "requirements-system-optional.txt": "system-optional",
    "requirements-ocr.txt": "ocr",
    "requirements-audio.txt": "audio",
    "requirements-dev.txt": "dev",
    "requirements-voice-local.txt": "voice-local",
    "requirements-voice-kitten.txt": "voice-kitten",
    "requirements-voice-kitten-engine.txt": "voice-kitten-engine",
}
LOCK_NO_DEPS = {"requirements-voice-kitten-engine.txt"}
DNS_MARKERS = (
    "failed to resolve",
    "nameresolutionerror",
    "getaddrinfo failed",
    "temporary failure in name resolution",
    "connection aborted",
    "max retries exceeded",
)


def read_requirements(path: str | Path) -> list[str]:
    """Read non-empty requirement lines while preserving environment markers."""
    items = []
    with Path(path).open(encoding="utf-8") as handle:
        for line in handle:
            line = line.split("#", 1)[0].strip()
            if line:
                items.append(line)
    return items


def _find_dependency_lock(
    requirement_file: str | Path,
    root: str | Path | None = None,
    *,
    python_version: tuple[int, int] | None = None,
    platform_name: str | None = None,
    machine: str | None = None,
) -> Path | None:
    """Return a generated lock for the current supported Windows target, if present."""
    group = LOCK_GROUPS.get(Path(requirement_file).name)
    if group is None:
        return None
    python_version = python_version or sys.version_info[:2]
    platform_name = platform_name or platform.system()
    machine = machine or platform.machine()
    if platform_name.casefold() != "windows" or machine.casefold() not in {"amd64", "x86_64"}:
        return None
    if python_version not in {(3, 11), (3, 12)}:
        return None
    project_root = Path(root) if root is not None else Path(__file__).resolve().parent
    version_name = f"python{python_version[0]}{python_version[1]}"
    candidate = (
        project_root
        / "dependency-locks"
        / "windows-x86_64"
        / version_name
        / f"{group}.txt"
    )
    return candidate if candidate.is_file() else None


def run_pip(args: list[str], runner=None) -> tuple[int, str]:
    """Run pip, stream output live, and return (returncode, full_output)."""
    command = PIP + list(args)
    if runner is not None:
        return runner(command)

    proc = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    lines = []
    for line in proc.stdout:
        print(line, end="")
        lines.append(line)
    proc.wait()
    return proc.returncode, "".join(lines)


def _constraint_args(paths: list[str | Path]) -> list[str]:
    args = []
    for raw_path in paths:
        path = Path(raw_path)
        if not path.is_file():
            raise FileNotFoundError(f"Constraint file does not exist: {path}")
        args.extend(["--constraint", str(path)])
    return args


def _report_failure(message: str, output: str, out) -> None:
    out(message)
    if any(marker in output.casefold() for marker in DNS_MARKERS):
        out("This looks like a DNS / internet connectivity problem.")
        out("Check VPN, DNS, and access to files.pythonhosted.org, then retry.")


def _environment_paths() -> list[Path]:
    """Return the active environment's import and console-script directories."""
    candidates = (
        sysconfig.get_path("purelib"),
        sysconfig.get_path("platlib"),
        sysconfig.get_path("scripts"),
    )
    paths = []
    seen = set()
    for raw_path in candidates:
        if not raw_path:
            continue
        path = Path(raw_path).resolve()
        if path not in seen:
            seen.add(path)
            paths.append(path)
    return paths


def _remove_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.exists():
        shutil.rmtree(path)


def _snapshot_environment(paths: list[Path], backup_root: Path) -> list[tuple[Path, Path | None]]:
    """Copy all pip-managed import/script locations before the first mutation."""
    snapshots = []
    for index, original in enumerate(paths):
        if not original.exists():
            snapshots.append((original, None))
            continue
        backup = backup_root / str(index)
        shutil.copytree(original, backup, symlinks=True)
        snapshots.append((original, backup))
    return snapshots


def _restore_environment(snapshots: list[tuple[Path, Path | None]]) -> None:
    """Restore the exact pre-install directory contents."""
    errors = []
    for original, backup in reversed(snapshots):
        try:
            _remove_path(original)
            if backup is not None:
                original.parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(backup, original, symlinks=True)
        except OSError as exc:
            errors.append(f"{original}: {exc}")
    if errors:
        raise RuntimeError(
            "Environment rollback was incomplete: " + "; ".join(errors)
        )


def install(
    path: str | Path,
    runner=None,
    out=print,
    *,
    constraints: tuple[str | Path, ...] | list[str | Path] = (),
    upgrade: bool = False,
    project_root: str | Path | None = None,
) -> int:
    """Preflight, snapshot, install, verify, and roll back on any failure."""
    requirement_file = Path(path)
    if not requirement_file.is_file():
        out(f"ERROR: dependency file does not exist: {requirement_file}")
        return 1

    requirements = read_requirements(requirement_file)
    if not requirements:
        out(f"ERROR: no packages found in {requirement_file}")
        return 1

    lock_file = _find_dependency_lock(requirement_file, root=project_root)
    if lock_file and upgrade:
        out("ERROR: --upgrade cannot be used with a hash-locked dependency group; regenerate its lock instead.")
        return 1

    effective_constraints = list(constraints)
    if lock_file is None and requirement_file.name in LOCK_GROUPS and requirement_file.name != "requirements.txt":
        core_lock = _find_dependency_lock("requirements.txt", root=project_root)
        if core_lock is not None:
            core_constraints = core_lock.parent / "core-constraints.txt"
            if core_constraints.is_file():
                effective_constraints.append(core_constraints)

    try:
        constraint_args = [] if lock_file else _constraint_args(effective_constraints)
    except FileNotFoundError as exc:
        out(f"ERROR: {exc}")
        return 1

    upgrade_args = ["--upgrade"] if upgrade else []
    no_deps_args = ["--no-deps"] if lock_file and requirement_file.name in LOCK_NO_DEPS else []
    hash_args = ["--require-hashes"] if lock_file else []
    common_args = [*upgrade_args, *constraint_args, *no_deps_args, *hash_args]
    install_source = lock_file or requirement_file
    source_description = (
        f"{requirement_file.name} (hash-locked: {lock_file.name})"
        if lock_file
        else requirement_file.name
    )

    with tempfile.TemporaryDirectory(prefix="kira-pip-resolution-") as temp_dir:
        temp_root = Path(temp_dir)
        report_path = temp_root / "resolution.json"
        preflight_args = [
            "install",
            "--dry-run",
            "--report",
            str(report_path),
            *common_args,
            "-r",
            str(install_source),
        ]
        code, output = run_pip(preflight_args, runner)
        if code:
            _report_failure(
                "ERROR: dependency resolution failed. No package installation was attempted.",
                output,
                out,
            )
            return code or 1

        out(f"Dependency resolution passed for {source_description}.")

        try:
            snapshots = _snapshot_environment(
                _environment_paths(), temp_root / "environment-backup"
            )
        except OSError as exc:
            out(f"ERROR: could not snapshot the Python environment; installation was not attempted: {exc}")
            return 1

        install_args = [
            "install",
            *common_args,
            "-r",
            str(install_source),
        ]
        code, output = run_pip(install_args, runner)
        failure = None
        if code:
            _report_failure(
                f"ERROR: pip could not install dependency group {requirement_file.name}.",
                output,
                out,
            )
            failure = f"pip install exited with status {code}"
        else:
            code, output = run_pip(["check"], runner)
            if code:
                out("ERROR: pip check found an incompatible or missing installed dependency.")
                if output.strip():
                    out(output.strip())
                failure = f"pip check exited with status {code}"

        if failure:
            out("Restoring the Python environment to its pre-install state...")
            try:
                _restore_environment(snapshots)
            except (OSError, RuntimeError) as exc:
                out(f"CRITICAL: {failure}; automatic rollback failed: {exc}")
                out("Do not launch Kira with this environment. Restore the environment backup or recreate the virtual environment.")
                return 2
            out("Rollback completed. The Python environment was restored.")
            return code or 1

    out(f"Dependency group {source_description} installed and verified.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("requirements", nargs="?", default="requirements.txt")
    parser.add_argument(
        "-c",
        "--constraints",
        action="append",
        default=[],
        help="constraint file; may be supplied more than once",
    )
    parser.add_argument(
        "--upgrade",
        action="store_true",
        help="explicitly upgrade packages in this dependency group",
    )
    args = parser.parse_args(argv)
    return install(
        args.requirements,
        constraints=args.constraints,
        upgrade=args.upgrade,
    )


if __name__ == "__main__":
    raise SystemExit(main())
