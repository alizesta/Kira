"""Optional offline Persian speech engines used before Cloud Voice.

ASR: Qwen3-ASR 0.6B via the official qwen-asr package.
TTS: Mana Persian Piper via persian-speech.
This module performs speech conversion only; it contains no chat or agent logic.
"""
from __future__ import annotations

import threading

_asr_lock = threading.RLock()
_tts_lock = threading.RLock()
_asr = None
_tts = None
_asr_error = None
_tts_error = None


def asr_ready() -> bool:
    try:
        import qwen_asr  # noqa: F401
        return True
    except ImportError:
        return False


def tts_ready() -> bool:
    try:
        import persian_speech_runtime  # noqa: F401
        return True
    except ImportError:
        return False


def transcribe(audio, sample_rate=16000, language="fa", prompt="", model_name="Qwen/Qwen3-ASR-0.6B") -> str:
    """Transcribe one mono float32 numpy segment locally. Returns empty text on empty input.

    Model loading is lazy. The first call downloads Qwen/Qwen3-ASR-0.6B unless it is cached.
    """
    global _asr, _asr_error
    import numpy as np

    samples = np.asarray(audio, dtype=np.float32).reshape(-1)
    if samples.size == 0:
        return ""
    with _asr_lock:
        if _asr is None:
            try:
                import torch
                from qwen_asr import Qwen3ASRModel
                _asr = Qwen3ASRModel.from_pretrained(
                    str(model_name or "Qwen/Qwen3-ASR-0.6B"),
                    dtype=torch.float32,
                    device_map="cpu",
                    max_inference_batch_size=1,
                    max_new_tokens=256,
                )
                _asr_error = None
            except Exception as exc:
                _asr_error = exc
                raise RuntimeError(f"Qwen3-ASR load failed: {type(exc).__name__}: {exc}") from exc
        lang = {"fa": "Persian", "en": "English", "ar": "Arabic"}.get(language, None)
        results = _asr.transcribe(
            audio=(samples, int(sample_rate)),
            language=lang,
            prompt=(prompt or None),
        )
        if not results:
            return ""
        return str(getattr(results[0], "text", "") or "").strip()


def synthesize_persian(text: str) -> bytes:
    """Return a complete WAV payload from the local Mana Persian Piper engine."""
    global _tts, _tts_error
    clean = str(text or "").strip()
    if not clean:
        return b""
    with _tts_lock:
        if _tts is None:
            try:
                from persian_speech_runtime import PiperSpeechEngine
                _tts = PiperSpeechEngine()
                _tts_error = None
            except Exception as exc:
                _tts_error = exc
                raise RuntimeError(f"Persian Piper load failed: {type(exc).__name__}: {exc}") from exc
        try:
            payload = _tts.stream(clean)
        except Exception as exc:
            raise RuntimeError(f"Persian Piper synthesis failed: {type(exc).__name__}: {exc}") from exc
    if not isinstance(payload, (bytes, bytearray)) or not payload.startswith(b"RIFF"):
        raise RuntimeError("Persian Piper returned invalid WAV data")
    return bytes(payload)


def status() -> dict:
    """Small diagnostic snapshot; does not load either model."""
    return {
        "asr_installed": asr_ready(),
        "tts_installed": tts_ready(),
        "asr_loaded": _asr is not None,
        "tts_loaded": _tts is not None,
        "asr_error": str(_asr_error)[:240] if _asr_error else "",
        "tts_error": str(_tts_error)[:240] if _tts_error else "",
    }
