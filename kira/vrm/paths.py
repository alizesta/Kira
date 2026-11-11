"""Resolve the built-in Kira avatar and per-character custom VRM paths."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

# Keep the creator-provided model at its original repository-root path.
DEFAULT_KIRA_VRM = Path(__file__).resolve().parents[2] / "kira sample.vrm"


def resolve_avatar_path(profile: Mapping[str, Any] | None) -> str:
    """Prefer an explicit per-character path, then Kira's optional default."""
    if not isinstance(profile, Mapping):
        return ""
    custom_path = str(profile.get("avatar_model_path") or "").strip()
    if custom_path:
        return custom_path
    if str(profile.get("id") or "") != "kira":
        return ""
    if not bool(profile.get("avatar_default_enabled", True)):
        return ""
    return str(DEFAULT_KIRA_VRM) if DEFAULT_KIRA_VRM.is_file() else ""
