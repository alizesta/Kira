"""Version/build metadata gate for Ai1 (Project Kira).

The developer name is never typed by hand: it is detected from the build metadata (the build
environment, the recorded build stamp, or the git author) and must be one of Codex / OpenCode /
Claude Code / ChatGPT. `kira/build_info.py` is stamped from that detection, then the version, build
date, build time, developer and the CHANGELOG entry are validated. Any gap stops the release.

Usage:
    python scripts/build_metadata.py            # detect + stamp kira/build_info.py + validate (build/release)
    python scripts/build_metadata.py --check    # validate the committed metadata only (CI gate)
    python scripts/build_metadata.py --print    # print the metadata as JSON (also validates)

Exit code 1 means the release must not be published. See PROJECT_CONTEXT.md and
docs/VERSION_METADATA_FA.md.
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from kira import build_rules  # noqa: E402

BUILD_INFO = ROOT / "kira" / "build_info.py"
CONFIG = ROOT / "kira" / "config.py"
CHANGELOG = ROOT / "CHANGELOG.md"
TIMEZONE = "Asia/Tehran"

#: Explicit override. It must name one of build_rules.DEVELOPERS.
ENV_DEVELOPER = "KIRA_DEVELOPER"
#: Tool markers exposed by build/release hosts, in priority order. A fixed name is used as-is;
#: a None value means the variable's value is normalised (e.g. AI_AGENT=opencode).
ENV_MARKERS = (
    ("CLAUDECODE", "Claude Code"),
    ("CLAUDE_CODE_ENTRYPOINT", "Claude Code"),
    ("CODEX_SANDBOX", "Codex"),
    ("CODEX_HOME", "Codex"),
    ("OPENCODE", "OpenCode"),
    ("OPENCODE_SESSION_ID", "OpenCode"),
    ("AI_AGENT", None),
    ("AGENT", None),
)


class MetadataError(RuntimeError):
    """The version/build metadata is incomplete; publishing must stop."""


def _module_constants(path: Path) -> dict[str, str]:
    """Read simple `NAME = "value"` assignments without importing (and running) the module."""
    try:
        tree = ast.parse(Path(path).read_text(encoding="utf-8"), filename=str(path))
    except (OSError, UnicodeDecodeError, SyntaxError) as exc:
        raise MetadataError(f"{path} cannot be read: {exc}") from exc
    values: dict[str, str] = {}
    for node in tree.body:
        targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AnnAssign) else []
        for target in targets:
            if isinstance(target, ast.Name):
                try:
                    value = ast.literal_eval(node.value)
                except ValueError:
                    continue
                if isinstance(value, str):
                    values[target.id] = value
    return values


def read_version(root: Path = ROOT) -> str:
    values = _module_constants(Path(root) / "kira" / "config.py")
    version = values.get("VERSION")
    if version is None:
        raise MetadataError(f"VERSION is missing from {(Path(root) / 'kira' / 'config.py')}")
    return version


def recorded_developer(root: Path = ROOT) -> str | None:
    """The developer recorded in the last build stamp (used when no build host marker is present)."""
    path = Path(root) / "kira" / "build_info.py"
    if not path.is_file():
        return None
    try:
        return build_rules.normalize_developer(_module_constants(path).get("DEVELOPER"))
    except MetadataError:
        return None


def git_identities(root: Path = ROOT) -> list[str]:
    """Author and committer names of the last commit; empty outside a usable git checkout."""
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--format=%an%n%cn"],
            cwd=str(root), capture_output=True, timeout=15, text=True,
            encoding="utf-8", errors="replace",
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if result.returncode != 0:
        return []
    return [line.strip() for line in (result.stdout or "").splitlines() if line.strip()]


def detect_developer(root: Path = ROOT, env: dict | None = None) -> str:
    """Resolve the developer tool automatically: explicit override, build marker, recorded stamp, git author."""
    environment = os.environ if env is None else env

    explicit = str(environment.get(ENV_DEVELOPER) or "").strip()
    if explicit:
        found = build_rules.normalize_developer(explicit)
        if not found:
            raise MetadataError(
                f"{ENV_DEVELOPER}={explicit!r} is not one of: {', '.join(build_rules.DEVELOPERS)}"
            )
        return found

    for name, fixed in ENV_MARKERS:
        raw = str(environment.get(name) or "").strip()
        if not raw:
            continue
        found = build_rules.normalize_developer(fixed or raw)
        if found:
            return found

    found = recorded_developer(root)
    if found:
        return found

    for identity in git_identities(root):
        found = build_rules.normalize_developer(identity)
        if found:
            return found

    raise MetadataError(
        "the developer could not be determined from the build metadata; set "
        f"{ENV_DEVELOPER}={build_rules.DEVELOPERS[0]}|{'|'.join(build_rules.DEVELOPERS[1:])} "
        "in the build/release environment"
    )


def stamp(root: Path = ROOT, now: datetime | None = None, developer: str | None = None) -> dict[str, str]:
    """Write kira/build_info.py from the detected developer and the current Asia/Tehran build time."""
    root = Path(root)
    name = build_rules.normalize_developer(developer) if developer else detect_developer(root)
    problem = build_rules.developer_error(name)
    if problem:
        raise MetadataError(problem)

    if now is None:
        now = datetime.now(ZoneInfo(TIMEZONE))
    elif now.tzinfo is not None:
        now = now.astimezone(ZoneInfo(TIMEZONE))
    build_date = now.strftime("%Y-%m-%d")
    build_time = now.strftime("%H:%M")

    text = (
        '"""Build metadata shown in the About section.\n'
        "\n"
        "GENERATED by scripts/build_metadata.py on every build and release: do not edit by hand.\n"
        "The version itself is maintained in kira/config.py. See PROJECT_CONTEXT.md.\n"
        '"""\n'
        "\n"
        f'BUILD_DATE = "{build_date}"      # Gregorian, YYYY-MM-DD (Asia/Tehran build time)\n'
        f'BUILD_TIME = "{build_time}"          # 24-hour HH:MM (Asia/Tehran build time)\n'
        f'DEVELOPER = "{name}"             # auto-detected by the build; never hand-edited\n'
    )
    target = root / "kira" / "build_info.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8", newline="\n")
    return {"version": read_version(root), "build_date": build_date, "build_time": build_time, "developer": name}


def validate(root: Path = ROOT) -> dict[str, str]:
    """Return the metadata or raise MetadataError listing every incomplete/invalid field."""
    root = Path(root)
    problems: list[str] = []

    version = ""
    try:
        version = read_version(root)
    except MetadataError as exc:
        problems.append(str(exc))
    else:
        problem = build_rules.version_error(version)
        if problem:
            problems.append(problem)

    stamp_values: dict[str, str] = {}
    try:
        stamp_values = _module_constants(root / "kira" / "build_info.py")
    except MetadataError as exc:
        problems.append(f"{exc} (run: python scripts/build_metadata.py)")

    build_date = stamp_values.get("BUILD_DATE", "")
    build_time = stamp_values.get("BUILD_TIME", "")
    developer = stamp_values.get("DEVELOPER", "")
    for problem in (build_rules.date_error(build_date),
                    build_rules.time_error(build_time),
                    build_rules.developer_error(developer)):
        if problem:
            problems.append(problem)

    changelog = root / "CHANGELOG.md"
    changelog_text = ""
    if changelog.is_file():
        try:
            changelog_text = changelog.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            problems.append(f"CHANGELOG.md cannot be read: {exc}")
    problem = build_rules.changelog_error(version, changelog_text)
    if problem:
        problems.append(problem)

    if problems:
        raise MetadataError(
            "version metadata is incomplete, so the release must not be published:\n  - "
            + "\n  - ".join(problems)
        )
    return {"version": version, "build_date": build_date, "build_time": build_time, "developer": developer}


def ensure_release_metadata(root: Path = ROOT, now: datetime | None = None) -> dict[str, str]:
    """Stamp the current build and validate it; raises MetadataError (release stops) when incomplete."""
    stamp(root=root, now=now)
    return validate(root)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Stamp and validate Ai1 version/build metadata.")
    parser.add_argument("--check", action="store_true", help="validate the committed metadata only")
    parser.add_argument("--print", dest="print_metadata", action="store_true", help="print the metadata as JSON")
    args = parser.parse_args(argv)
    try:
        if args.check or args.print_metadata:
            metadata = validate()
        else:
            metadata = ensure_release_metadata()
    except MetadataError as exc:
        print(f"BUILD METADATA ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(metadata, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
