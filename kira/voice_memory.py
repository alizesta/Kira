"""Release Kira's resident speech models on demand (for example while a game needs the RAM).

Piper (TTS) and Shenava (ASR) stay loaded after first use. This module drops them without deleting any
downloaded file: the next spoken sentence or recognition reloads the model lazily through the normal
`local_voice` paths. Nothing here raises; every step reports whether something was actually released.
"""
from __future__ import annotations

import gc
import logging

_LOG = logging.getLogger(__name__)


def unload_tts() -> bool:
    """Drop the loaded Piper voice. Waits for a running synthesis (it holds the same lock)."""
    from . import local_voice

    with local_voice._tts_lock:
        previous = local_voice._tts
        local_voice._tts = None
        local_voice._tts_model_path = ""
        local_voice._tts_model_label = ""
        local_voice._tts_model_signature = None
        local_voice._tts_error = None
    released = previous is not None
    del previous
    gc.collect()
    return released


def unload_asr() -> bool:
    """Drop the loaded Shenava recognizer (reuses local_voice.unload_shenava)."""
    from . import local_voice

    loaded = local_voice._shenava_recognizer is not None
    local_voice.unload_shenava()
    return loaded


def unload_ezafe() -> bool:
    """Drop the optional Persian ezafe detector if that module exposes an unload hook."""
    try:
        from . import persian_ezafe
    except Exception:  # noqa: BLE001 - optional component
        return False
    hook = getattr(persian_ezafe, "unload", None)
    if not callable(hook):
        return False
    hook()
    return True


def release_voice_models(*, tts: bool = True, asr: bool = True, ezafe: bool = True) -> dict[str, bool]:
    """Release the selected resident voice models and report what was really freed."""
    report = {"tts": False, "asr": False, "ezafe": False}
    steps = (("tts", tts, unload_tts), ("asr", asr, unload_asr), ("ezafe", ezafe, unload_ezafe))
    for name, wanted, action in steps:
        if not wanted:
            continue
        try:
            report[name] = bool(action())
        except Exception:  # noqa: BLE001 - freeing memory must never break the app
            _LOG.exception("Releasing the %s model failed", name)
    return report
