"""Stable PortAudio device identity helpers for microphone selection.

Windows commonly exposes one physical microphone through multiple host APIs.
A plain device-name setting cannot distinguish those endpoints, so persist the
host API plus device identity while keeping legacy name settings readable.
"""
from __future__ import annotations

import json
from collections import Counter
from typing import Any

_TOKEN_PREFIX = "kira-pa-v1:"


def _device_hostapi_name(device: dict[str, Any], hostapis: list[dict[str, Any]]) -> str:
    try:
        index = int(device.get("hostapi", -1))
    except (TypeError, ValueError):
        return ""
    if 0 <= index < len(hostapis):
        return str(hostapis[index].get("name") or "").strip()
    return ""


def input_device_entries(sd) -> list[dict[str, Any]]:
    """Return every input-capable PortAudio endpoint, preserving host-API duplicates."""
    devices = list(sd.query_devices())
    try:
        hostapis = list(sd.query_hostapis())
    except (AttributeError, OSError, TypeError):
        hostapis = []

    records = []
    for index, device in enumerate(devices):
        try:
            channels = int(device.get("max_input_channels", 0) or 0)
        except (TypeError, ValueError):
            channels = 0
        name = str(device.get("name") or "").strip()
        if channels <= 0 or not name:
            continue
        records.append({
            "index": index,
            "name": name,
            "hostapi": _device_hostapi_name(device, hostapis),
        })

    name_counts = Counter(item["name"].casefold() for item in records)
    labels = []
    for item in records:
        label = item["name"]
        if name_counts[label.casefold()] > 1:
            label = f"{label} — {item['hostapi'] or 'PortAudio'}"
        labels.append(label)

    label_counts = Counter(value.casefold() for value in labels)
    entries = []
    for item, label in zip(records, labels):
        if label_counts[label.casefold()] > 1:
            label = f"{label} (#{item['index']})"
        identity = {
            "index": item["index"],
            "name": item["name"],
            "hostapi": item["hostapi"],
        }
        entries.append({
            **item,
            "label": label,
            "value": _TOKEN_PREFIX + json.dumps(identity, ensure_ascii=False, separators=(",", ":")),
        })
    return entries


def resolve_input_device(sd, selection: str | None) -> int | None:
    """Resolve a stable host-API token or a legacy device name to an input index.

    Empty selection means use PortAudio's current default. Legacy name-only
    settings remain supported and resolve to the first matching input endpoint.
    """
    wanted = str(selection or "").strip()
    if not wanted:
        return None

    devices = list(sd.query_devices())
    try:
        hostapis = list(sd.query_hostapis())
    except (AttributeError, OSError, TypeError):
        hostapis = []

    if wanted.startswith(_TOKEN_PREFIX):
        try:
            identity = json.loads(wanted[len(_TOKEN_PREFIX):])
            desired_name = str(identity.get("name") or "").strip()
            desired_hostapi = str(identity.get("hostapi") or "").strip()
            preferred_index = int(identity.get("index", -1))
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
        if not desired_name:
            return None

        matches = []
        for index, device in enumerate(devices):
            try:
                has_input = int(device.get("max_input_channels", 0) or 0) > 0
            except (TypeError, ValueError):
                has_input = False
            if not has_input or str(device.get("name") or "").strip() != desired_name:
                continue
            hostapi = _device_hostapi_name(device, hostapis)
            if desired_hostapi and hostapi.casefold() != desired_hostapi.casefold():
                continue
            matches.append(index)

        if preferred_index in matches:
            return preferred_index
        return matches[0] if matches else None

    # Backward compatibility for settings written before host-API tokens existed.
    # When several host APIs expose the same name, prefer the endpoint PortAudio
    # currently marks as the system default instead of an arbitrary first match.
    matches = []
    for index, device in enumerate(devices):
        try:
            has_input = int(device.get("max_input_channels", 0) or 0) > 0
        except (TypeError, ValueError):
            has_input = False
        if has_input and str(device.get("name") or "").strip() == wanted:
            matches.append(index)
    if not matches:
        return None
    try:
        default_devices = getattr(getattr(sd, "default", None), "device", None)
        default_input = int(default_devices[0]) if default_devices is not None else -1
    except (IndexError, TypeError, ValueError):
        default_input = -1
    return default_input if default_input in matches else matches[0]
