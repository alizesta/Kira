"""Resolve and install one dependency group without mutating a broken environment.

The resolver preflight is read-only: pip must be able to produce a complete
installation report before the actual installation is attempted. Normal
installs never upgrade already-satisfied packages; upgrades are explicit.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

PIP = [sys.executable, "-m", "pip"]
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


def install(
    path: str | Path,
    runner=None,
    out=print,
    *,
    constraints: tuple[str | Path, ...] | list[str | Path] = (),
    upgrade: bool = False,
) -> int:
    """Preflight, install, and verify a single dependency group.

    A failed resolver preflight never starts an install. There is deliberately
    no package-by-package fallback because it bypasses the complete graph.
    """
    requirement_file = Path(path)
    if not requirement_file.is_file():
        out(f"ERROR: dependency file does not exist: {requirement_file}")
        return 1

    requirements = read_requirements(requirement_file)
    if not requirements:
        out(f"ERROR: no packages found in {requirement_file}")
        return 1

    try:
        constraint_args = _constraint_args(list(constraints))
    except FileNotFoundError as exc:
        out(f"ERROR: {exc}")
        return 1

    upgrade_args = ["--upgrade"] if upgrade else []
    common_args = [*upgrade_args, *constraint_args]

    with tempfile.TemporaryDirectory(prefix="kira-pip-resolution-") as temp_dir:
        report_path = Path(temp_dir) / "resolution.json"
        preflight_args = [
            "install",
            "--dry-run",
            "--report",
            str(report_path),
            *common_args,
            "-r",
            str(requirement_file),
        ]
        code, output = run_pip(preflight_args, runner)
        if code:
            _report_failure(
                "ERROR: dependency resolution failed. No package installation was attempted.",
                output,
                out,
            )
            return code or 1

        out(f"Dependency resolution passed for {requirement_file.name}.")
        install_args = [
            "install",
            *common_args,
            "-r",
            str(requirement_file),
        ]
        code, output = run_pip(install_args, runner)
        if code:
            _report_failure(
                f"ERROR: pip could not install dependency group {requirement_file.name}.",
                output,
                out,
            )
            return code or 1

        code, output = run_pip(["check"], runner)
        if code:
            out("ERROR: pip check found an incompatible or missing installed dependency.")
            if output.strip():
                out(output.strip())
            return code or 1

    out(f"Dependency group {requirement_file.name} installed and verified.")
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
