"""Which voice controls the speech engines in use really support (so the settings screen only offers real options).

The chain that can speak a sentence is: Cloud Voice providers (when switched on and ready, in the user's order) -> Microsoft Edge neural
voices (package edge-tts) -> Windows voices (SAPI). A control is offered when at least one engine of that chain honours it, and the
engines that honour it are named next to it. Volume is applied by Kira's own player, so it always works.
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
    try:
        svc = cloud_voice.service()
        if svc.store.data["tts"]["use_cloud"]:
            for p in svc.providers_in_use("tts"):
                model = svc.store.data["tts"]["model"].get(p) or next((m["id"] for m in svc.store.models(p, "tts")), "")
                out.append((cloud_voice.LABELS.get(p, p), cloud_voice.tts_caps(p, model)))
    except Exception:                                              # noqa: BLE001 - never let this break the settings screen
        pass
    if importlib.util.find_spec("edge_tts") is not None:
        out.append((LOCAL_LABELS["edge"], set(LOCAL_CAPS["edge"])))
    if sys.platform == "win32":
        out.append((LOCAL_LABELS["sapi"], set(LOCAL_CAPS["sapi"])))
    return out


def supported(settings=None) -> dict:
    """{control: [engine labels that honour it]}; a control with an empty list must not be shown."""
    result = {c: [] for c in CONTROLS}
    for label, caps in chain(settings):
        for c in CONTROLS:
            if c in caps and label not in result[c]:
                result[c].append(label)
    return result
