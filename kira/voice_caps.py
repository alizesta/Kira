"""Capability summary for the local-only speech pipeline."""

from __future__ import annotations

CONTROLS = ("rate",)


def chain(settings=None) -> list:
    """Return the local engines that are installed; never inspect network providers."""
    settings = settings or {}
    try:
        from . import local_voice
        diagnostics = local_voice.diagnostics(str(settings.get("local_voice_tts_model") or ""))
        engines = []
        if diagnostics.get("tts_installed"):
            engines.append(("Piper محلی", {"rate"}))
        if diagnostics.get("asr_installed"):
            engines.append(("Qwen3-ASR محلی", set()))
        try:
            import faster_whisper  # noqa: F401
            engines.append(("Whisper محلی", set()))
        except ImportError:
            pass
        return engines
    except Exception:
        return []


def supported(settings=None) -> dict:
    """Return controls exposed by the installed local speech engines."""
    result = {control: [] for control in CONTROLS}
    for label, capabilities in chain(settings):
        for control in CONTROLS:
            if control in capabilities and label not in result[control]:
                result[control].append(label)
    return result
