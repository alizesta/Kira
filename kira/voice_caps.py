"""Which voice controls the speech engines in use really support (so the settings screen only offers real options).

The TTS chain is local Persian Piper -> Windows SAPI -> Edge TTS -> Cloud Voice. A control is offered when at least one engine
in that chain honours it, and the engines that honour it are named next to it. Volume is applied by Kira's own player.
"""
from __future__ import annotations

import importlib.util
import sys

from . import cloud_voice

LOCAL_CAPS = {"edge": {"rate", "pitch"}, "sapi": {"rate"}}
LOCAL_LABELS = {"edge": "Edge", "sapi": "Windows"}
CONTROLS = ("rate", "pitch", "style", "style_degree")


def chain(settings=None) -> list:
    """[(engine label, capability set)] in the order they would be tried."""
    out = []
    # Offline Persian Piper has no exposed rate/pitch/style controls.
    try:
        from . import local_voice
        if local_voice.tts_ready():
            out.append(("Persian Piper", set()))
    except Exception:
        pass
    if sys.platform == "win32":
        out.append((LOCAL_LABELS["sapi"], set(LOCAL_CAPS["sapi"])))
    if importlib.util.find_spec("edge_tts") is not None:
        out.append((LOCAL_LABELS["edge"], set(LOCAL_CAPS["edge"])))
    try:
        svc = cloud_voice.service()
        if svc.store.data["tts"]["use_cloud"]:
            for p in svc.providers_in_use("tts"):
                model = svc.store.data["tts"]["model"].get(p) or next((m["id"] for m in svc.store.models(p, "tts")), "")
                out.append((cloud_voice.LABELS.get(p, p), cloud_voice.tts_caps(p, model)))
    except Exception:                                              # noqa: BLE001 - never let this break the settings screen
        pass
    return out


def supported(settings=None) -> dict:
    """{control: [engine labels that honour it]}; a control with an empty list must not be shown."""
    result = {c: [] for c in CONTROLS}
    for label, caps in chain(settings):
        for c in CONTROLS:
            if c in caps and label not in result[c]:
                result[c].append(label)
    return result
