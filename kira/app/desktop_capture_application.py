"""Qt-free privacy and enablement policy for Live Desktop Vision."""
from __future__ import annotations

import fnmatch
import os
from typing import Any


DEFAULT_BLOCKLIST = {
    "exe": (
        "1password.exe", "bitwarden.exe", "keepass.exe", "keepassxc.exe",
        "lastpass.exe", "dashlane.exe", "keeperpasswordmanager.exe",
        "revolut.exe", "monzo.exe", "wise.exe", "chase.exe",
        "bankofamerica.exe", "citibank.exe", "wellsfargo.exe",
        "capitalone.exe", "ally.exe", "barclays.exe", "hsbc.exe",
        "systemsettings.exe", "systemsettingsbroker.exe", "control.exe",
    ),
    "title": (
        "*incognito*", "*inprivate*", "*private browsing*", "*private window*",
        "*windows settings*", "settings", "* - settings",
        "*bank of america*", "*chase online*", "*wells fargo online*",
        "*citibank online*", "*capital one*",
    ),
    "path": (
        "*\\microsoft\\windows\\immersivecontrolpanel\\*",
        "*\\windows\\system32\\control.exe",
    ),
}
_RULE_KINDS = ("exe", "title", "path")


class DesktopCaptureApplicationService:
    """Own per-session opt-in, selected display and fail-closed privacy rules."""

    def __init__(self, settings: dict[str, Any] | None = None) -> None:
        self.settings = settings if isinstance(settings, dict) else {}
        self.enabled = False
        self.settings["desktop_vision_enabled"] = False
        self.selected_monitor_id = str(self.settings.get("desktop_vision_monitor_id") or "").strip()
        self._blocklist = self._load_blocklist(self.settings.get("desktop_vision_blocklist"))
        self._allowlist = self._load_allowlist(self.settings.get("desktop_vision_allowlist"))

    @staticmethod
    def _normal(value: Any) -> str:
        return str(value or "").strip().replace("/", "\\").casefold()

    @classmethod
    def _load_blocklist(cls, custom) -> dict[str, tuple[str, ...]]:
        custom = custom if isinstance(custom, dict) else {}
        result = {}
        for kind in _RULE_KINDS:
            values = custom.get(kind, ())
            extras = list(values) if isinstance(values, (list, tuple, set)) else []
            result[kind] = tuple(dict.fromkeys(
                cls._normal(value) for value in (*DEFAULT_BLOCKLIST[kind], *extras)
                if str(value).strip()
            ))
        return result

    @classmethod
    def _load_allowlist(cls, values) -> dict[str, set[str]]:
        result = {kind: set() for kind in _RULE_KINDS}
        if isinstance(values, (list, tuple, set)):
            for raw in values:
                if not isinstance(raw, str) or ":" not in raw:
                    continue
                kind, value = raw.split(":", 1)
                kind, value = kind.strip().lower(), cls._normal(value)
                if kind in result and value:
                    result[kind].add(value)
        return result

    @staticmethod
    def _matches(value: str, pattern: str) -> bool:
        return bool(value and fnmatch.fnmatchcase(value, pattern))

    def set_enabled(self, enabled: bool) -> bool:
        self.enabled = bool(enabled)
        self.settings["desktop_vision_enabled"] = self.enabled
        return self.enabled

    def set_selected_monitor(self, monitor_id: str | None) -> str:
        self.selected_monitor_id = str(monitor_id or "").strip()
        self.settings["desktop_vision_monitor_id"] = self.selected_monitor_id
        return self.selected_monitor_id

    def add_allow_rule(self, kind: str, value: str) -> bool:
        """Persist a user's explicit exe/title/path exception for the matching rule dimension."""
        kind, value = str(kind or "").strip().lower(), self._normal(value)
        if kind not in _RULE_KINDS or not value:
            return False
        self._allowlist[kind].add(value)
        self.settings["desktop_vision_allowlist"] = sorted(
            f"{rule_kind}:{pattern}"
            for rule_kind, patterns in self._allowlist.items()
            for pattern in patterns
        )
        return True

    def evaluate_window(self, window_info: dict[str, Any] | None, *,
                        explicit: bool = False) -> tuple[bool, str]:
        if not explicit and not self.enabled:
            return False, "desktop_vision_disabled"
        if not isinstance(window_info, dict):
            return False, "foreground_window_unidentified"
        identity = {
            "exe": self._normal(os.path.basename(str(window_info.get("exe") or ""))),
            "title": self._normal(window_info.get("title")),
            "path": self._normal(window_info.get("path")),
        }
        # The selected monitor is the capture target, not the foreground app.
        # HWND/PID/rect must still be trustworthy, while app metadata may be absent
        # for desktop surfaces, overlays and some games.
        if not window_info.get("hwnd") or not window_info.get("pid") or not window_info.get("rect"):
            return False, "foreground_window_identity_incomplete"
        blocked = [
            (kind, pattern)
            for kind in _RULE_KINDS
            for pattern in self._blocklist[kind]
            if identity[kind] and self._matches(identity[kind], pattern)
        ]
        if not blocked:
            return True, "allowed"
        for kind, _pattern in blocked:
            if not any(self._matches(identity[kind], allow) for allow in self._allowlist[kind]):
                return False, f"blocked_{kind}"
        return True, "explicit_allowlist_exception"
