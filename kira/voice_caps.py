"""Capabilities reported by the registered local voice adapters."""
from __future__ import annotations

CONTROLS = ("rate",)


def chain(settings=None, manager=None) -> list:
    """Return only local engines with a validated runtime and selected model."""
    from . import local_voice
    if manager is None:
        from .asr_manager import ASRManager
        manager = ASRManager()
    values = settings or {}
    engines = []
    asr = manager.discover(values)
    if asr.get("ready"):
        engines.append((
            str(asr.get("engine_name") or asr.get("engine_id")),
            set(asr.get("capabilities") or ()),
        ))
    state = local_voice.status(str(values.get("local_voice_tts_model") or ""))
    if state.get("tts_installed"):
        engines.append(("Piper محلی", {"rate"}))
    return engines


def supported(settings=None, manager=None) -> dict:
    """Return controls exposed by currently usable local adapters."""
    result = {control: [] for control in CONTROLS}
    for label, capabilities in chain(settings, manager=manager):
        for control in CONTROLS:
            if control in capabilities and label not in result[control]:
                result[control].append(label)
    return result
