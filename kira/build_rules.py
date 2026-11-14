"""Mandatory version/build-metadata rules (the contract enforced by the build and release gate).

The rule itself is documented in PROJECT_CONTEXT.md ("Version metadata and developer attribution")
and docs/VERSION_METADATA_FA.md. This module stays free of Qt, network and kira.config imports so the
build scripts and the portable CI job can use exactly the same checks as the application.
"""
from __future__ import annotations

import re
from datetime import date as _date

# The only tools allowed to appear as "Developer". The build never accepts a hand-typed value.
DEVELOPERS = ("Codex", "OpenCode", "Claude Code", "ChatGPT")

# Version strings such as "1 stable", "2", "2.0.1" or "1.4-beta": one line, starts with a digit.
VERSION_RE = re.compile(r"^[0-9][0-9A-Za-z._+ -]{0,39}$")
# Build date is Gregorian and always YYYY-MM-DD.
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# Build time is 24-hour HH:MM (no seconds, no AM/PM).
TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")

_ALIASES = {
    "codex": "Codex",
    "openai codex": "Codex",
    "opencode": "OpenCode",
    "open code": "OpenCode",
    "claude": "Claude Code",
    "claude code": "Claude Code",
    "claudecode": "Claude Code",
    "chatgpt": "ChatGPT",
    "chat gpt": "ChatGPT",
    "openai": "ChatGPT",
}


def _key(value: str) -> str:
    return re.sub(r"\s+", " ", str(value).replace("-", " ").replace("_", " ")).strip().lower()


def normalize_developer(value) -> str | None:
    """Return the canonical developer name for a tool identifier, or None when it is unknown."""
    text = str(value or "").strip()
    if text in DEVELOPERS:
        return text
    return _ALIASES.get(_key(text))


def version_error(version) -> str | None:
    if not isinstance(version, str) or not version.strip():
        return "VERSION is empty"
    if version != version.strip():
        return f"VERSION {version!r} has leading or trailing spaces"
    if not VERSION_RE.match(version):
        return f"VERSION {version!r} must be one line starting with a digit (e.g. '1 stable' or '2.0.1')"
    return None


def date_error(value) -> str | None:
    text = str(value or "").strip()
    if not DATE_RE.match(text):
        return f"BUILD_DATE {text!r} must be the Gregorian date format YYYY-MM-DD"
    try:
        _date.fromisoformat(text)
    except ValueError:
        return f"BUILD_DATE {text!r} is not a real calendar date"
    return None


def time_error(value) -> str | None:
    text = str(value or "").strip()
    if not TIME_RE.match(text):
        return f"BUILD_TIME {text!r} must be 24-hour HH:MM (00:00 to 23:59)"
    return None


def developer_error(value) -> str | None:
    text = str(value or "").strip()
    if text not in DEVELOPERS:
        return f"DEVELOPER {text!r} must be one of: {', '.join(DEVELOPERS)}"
    return None


def changelog_error(version, changelog_text) -> str | None:
    """The changelog and the version must move together (PROJECT_CONTEXT.md, requirement 4)."""
    text = str(changelog_text or "")
    if not text.strip():
        return "CHANGELOG.md is missing or empty"
    if str(version or "").strip() not in text:
        return f"CHANGELOG.md does not mention the current version {version!r}"
    return None
